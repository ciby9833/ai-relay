"""记录用户怎么处理每件事，回答两个问题：

1. Relay 有没有帮他省时间：处理一件事时，他还要不要打开原文（open_original），用了多久。
2. 哪一类事他总是同样处理：以后可以提议“这类我直接办”，但必须他授权后才会自动执行。

只记录用户本人的决定（网页按钮、飞书卡片按钮、在对话里说“发吧”），以及按他授权自动执行的操作（via=auto）。
系统自己关闭的事（对方回了、审批在别处处理了）不记。
"""

import hashlib
import hmac
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import FollowUp, PendingAction, Signal, User, UserDecision

# 这次决定是从哪里来的：入口处设置（网页请求 / 飞书卡片回调 / 对话 / 任务自动执行）
via: ContextVar[str] = ContextVar("relay_decision_via", default="system")

ACTION_SUBJECT = {
    "approval_decision": "approval", "calendar_rsvp": "invitation", "send_mail": "send_mail", "send_chat": "send_chat",
    "create_task": "create_task", "create_event": "create_event", "cloud_write": "cloud_write",
}


def category_of(subject: str, signal: Signal | None, action: PendingAction | None = None) -> str | None:
    """“同一类事”的依据。只用稳定的标识（审批类型、组织者、对方地址），不用标题。"""
    p = (signal.payload or {}) if signal else {}
    a = (action.payload or {}) if action else {}
    if subject == "approval":
        return p.get("definition_name") or (p.get("detail") or {}).get("approval_name")
    if subject == "invitation":
        return p.get("organizer") or p.get("organizer_email")
    if subject in ("reply", "review", "send_mail"):
        return a.get("to") or p.get("from_address") or p.get("from")
    if subject == "send_chat":
        return a.get("to") or a.get("receive_id")
    if subject == "mention":
        return p.get("chat_name") or p.get("chat_id")
    if subject == "biz":
        return p.get("integration")
    return None


async def record(
    session: AsyncSession, user: User, decision: str, *,
    item: FollowUp | None = None, action: PendingAction | None = None, detail: dict | None = None,
) -> None:
    """记一条用户决定（不提交，由调用方提交）。"""
    source = via.get()
    if source == "system":
        return
    if item is None and action is not None:
        item = (await session.execute(
            select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.action_id == action.id).limit(1)
        )).scalars().first()
    if item is None and action is not None and action.signal_id:
        # 卡片上直接批准/回复邀请时操作没挂到事项上：按来源记录找回对应的事
        item = (await session.execute(
            select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.signal_ids.contains([action.signal_id]))
            .order_by(FollowUp.id.desc()).limit(1)
        )).scalars().first()
    signal = None
    if action is not None and action.signal_id:
        signal = await session.get(Signal, action.signal_id)
    elif item is not None and item.signal_ids:
        signal = await session.get(Signal, item.signal_ids[-1])
    subject = ACTION_SUBJECT.get(action.kind, action.kind) if action is not None else (item.kind if item else "unknown")
    started = (item.created_at if item is not None else None) or (action.created_at if action is not None else None)
    session.add(UserDecision(
        user_id=user.id, subject=subject, category=(category_of(subject, signal, action) or "")[:255] or None,
        decision=decision, via=source, item_id=item.id if item else None, action_id=action.id if action else None,
        seconds_to_decide=int((datetime.now(UTC) - started).total_seconds()) if started else None,
        detail=detail or {},
    ))


def action_decision(action: PendingAction) -> str:
    """执行成功的操作对应的决定。"""
    if action.kind == "approval_decision":
        return "approve" if action.payload.get("approve") else "reject"
    if action.kind == "calendar_rsvp":
        return action.payload.get("status") or "rsvp"
    return "confirm"


# ---------- “在飞书查看”的跳转链接：先记一笔，再跳到原文 ----------


def _sign(item_id: int, user_id: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"open:{item_id}:{user_id}".encode(), hashlib.sha256).hexdigest()[:32]


def open_link(item: FollowUp, source: str = "web") -> str | None:
    """带签名的跳转地址：飞书内置浏览器里没有 Relay 的登录态，所以不靠 cookie 认人。"""
    if not item.url:
        return None
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/api/open/{item.id}?u={item.user_id}&s={_sign(item.id, str(item.user_id))}&f={source}"


def verify(item_id: int, user_id: str, signature: str) -> bool:
    return hmac.compare_digest(_sign(item_id, user_id), signature or "")


# ---------- 汇总 ----------


async def summary(session: AsyncSession, user: User, days: int = 7) -> dict:
    """一段时间里的处理情况：总数、打开原文的比例、自动办掉的数量、按类别的决定分布。"""
    since = datetime.now(UTC) - timedelta(days=days)
    base = select(UserDecision).where(UserDecision.user_id == user.id, UserDecision.created_at >= since)
    rows = (await session.execute(base)).scalars().all()
    handled = [r for r in rows if r.decision != "open_original"]
    opened_items = {r.item_id for r in rows if r.decision == "open_original" and r.item_id}
    handled_items = {r.item_id for r in handled if r.item_id}
    patterns: dict[tuple, dict] = {}
    for r in handled:
        if r.via == "auto" or not r.category:
            continue
        entry = patterns.setdefault((r.subject, r.category), {"subject": r.subject, "category": r.category, "decisions": {}})
        entry["decisions"][r.decision] = entry["decisions"].get(r.decision, 0) + 1
    seconds = sorted(r.seconds_to_decide for r in handled if r.seconds_to_decide is not None and r.via != "auto")
    ignored = await session.scalar(
        select(func.count(FollowUp.id)).where(
            FollowUp.user_id == user.id, FollowUp.created_at >= since, FollowUp.status != "open",
            FollowUp.announced_at.isnot(None), FollowUp.id.notin_(handled_items | {0}),
        )
    )
    return {
        "days": days,
        "handled": len([r for r in handled if r.via != "auto"]),
        "handled_without_original": len(handled_items - opened_items),
        "opened_original": len(opened_items),
        "auto": len([r for r in handled if r.via == "auto"]),
        "closed_without_action": ignored or 0,
        "median_seconds_to_decide": seconds[len(seconds) // 2] if seconds else None,
        "by_via": {v: len([r for r in handled if r.via == v]) for v in {r.via for r in handled}},
        "patterns": sorted(patterns.values(), key=lambda p: -sum(p["decisions"].values()))[:20],
    }
