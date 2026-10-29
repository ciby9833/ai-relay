"""用户在真实卡片上的反馈：飞书卡片和网页共用同一套。

“已处理”：提醒之后他处理了（没提醒过就是他自己标的）。
“不用跟了”再选原因：提醒前就处理了 / 不归我 / 不值得提醒 / 这类以后少提醒 / 重复了。
每种都结束这件事（只结束这一件，合并展示的其他事不受影响），并记一条反馈用来算准确率和迟到率。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import i18n, insights
from app.models import ChatMessage, FollowUp, ItemFeedback, PendingAction, User
from app.proactive import actions, attention, items

# 不用跟了的原因（按卡片上的顺序）
REASONS = ("handled_before", "not_mine", "not_worth", "quieter", "duplicate", "paused")
OUTCOMES = ("handled_after", "handled", *REASONS)
RESOLUTION = {
    "handled_after": "你标记为已处理", "handled": "你标记为已处理", "handled_before": "提醒前你就处理了",
    "not_mine": "你说这件不归你", "not_worth": "你说不值得提醒", "quieter": "你说这类以后少提醒", "duplicate": "你说和别的重复了",
    "paused": "你说暂时不跟进",
}
UNDO_WINDOW = timedelta(days=1)


async def undo(session: AsyncSession, user: User, item: FollowUp) -> str:
    """撤销“已处理 / 不用跟了”：只重新打开这一件，删掉那条反馈。外部已经执行的操作（审批、发送）不能这样撤销。"""
    last = (await session.execute(select(ItemFeedback).where(
        ItemFeedback.user_id == user.id, ItemFeedback.item_id == item.id).order_by(ItemFeedback.id.desc()).limit(1))).scalars().first()
    if last is None or item.status == items.OPEN or last.created_at < datetime.now(UTC) - UNDO_WINDOW:
        raise ValueError("这件事不能撤销（不是你刚标记的）")
    await session.delete(last)
    item.status, item.resolution, item.closed_at = items.OPEN, None, None
    item.updated_at, item.announced_at = datetime.now(UTC), datetime.now(UTC)  # 回到待处理，不再重新提醒
    return "已撤销，这件事回到待处理"


async def source_of(session: AsyncSession, item: FollowUp) -> str:
    """这件事的来源类别（只有类别，不含内容）：私聊和群聊要分开看。"""
    prefix = item.key.split(":", 1)[0]
    if prefix in ("chat", "mention"):
        if (item.facets or {}).get("private") is not None:
            return "p2p" if item.facets["private"] else "group"
        message_id = item.key.split(":")[1] if ":" in item.key else ""
        owner = (await session.execute(
            select(ChatMessage.owner_user_id).where(ChatMessage.message_id == message_id).limit(1))).first()
        return "p2p" if owner and owner[0] is not None else "group"
    return {"mail-thread": "mail", "batch": "mail", "invite": "invitation", "approval-update": "approval"}.get(prefix, prefix)[:16]


async def give(session: AsyncSession, user: User, item: FollowUp, outcome: str, via: str) -> str:
    """记下反馈并结束这件事，返回给用户看的一句话。不提交，由调用方提交。"""
    if outcome not in OUTCOMES:
        raise ValueError("不认识的反馈")
    if outcome in ("handled", "handled_after"):
        outcome = "handled_after" if item.pushed_at else "handled"
    message = RESOLUTION[outcome]
    if outcome == "quieter":
        try:
            message = await attention.quieter(session, user, item)
        except ValueError:
            outcome, message = "not_worth", RESOLUTION["not_worth"]
    now = datetime.now(UTC)
    session.add(ItemFeedback(
        user_id=user.id, item_id=item.id, kind=item.kind, source=await source_of(session, item), outcome=outcome, via=via,
        pushed_at=item.pushed_at, seconds_after_push=int((now - item.pushed_at).total_seconds()) if item.pushed_at else None,
    ))
    if item.status == items.OPEN:
        items.close(item, "done" if outcome.startswith("handled") else "dismissed", RESOLUTION[outcome])
        if item.action_id:
            action = await session.get(PendingAction, item.action_id)
            if action and action.status == "pending":
                actions.cancel(action)
    await insights.record(session, user, "done" if outcome.startswith("handled") else "dismiss", item=item,
                          detail={"outcome": outcome})
    return message


def label(outcome: str) -> str:
    return i18n.ui(f"fb_{outcome}")
