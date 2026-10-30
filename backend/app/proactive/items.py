"""跟进事项：把信号归并成“事”，推进状态，到点提醒，并在主线里告诉用户。

一件事的生命周期（以回邮件为例）：
    新邮件 → 等你回复（Relay 先起草好）→ 你确认发送 → 等对方回复（3 天没回就提醒，并起草跟进邮件）
    → 对方回了 → 又变成等你回复 ……
所有对外的操作都只准备、不执行，由用户确认。
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.judgements.record import judged
from app.feishu.client import FeishuClient, FeishuError
from app.home import ConversationBusy, post
from app.llm.base import LLMError
from app.models import ChatMessage, FollowUp, PendingAction, Signal, User
from app.proactive import actions, attention, cards
from app.proactive.llm import complete_text
from app.proactive.prompts import APPROVAL_SUMMARY_SYSTEM, FOLLOWUP_SYSTEM, NARRATE_SYSTEM, PROGRESS_SYSTEM, REPLY_STATE_SYSTEM
from app.proactive.push import push
from app.sources import approval as approval_source
from app.sources.base import add_signal
from app import automation, i18n, insights
from app.proactive.settings import in_quiet_hours, language_of

logger = logging.getLogger("relay.items")

APPROVAL_REMIND = timedelta(days=2)
WAITING_REMIND = timedelta(days=3)
MAX_NUDGES = 2
OPEN = "open"
# 候选：拿不准要不要跟的（私聊里一句没头没尾的问话……），先留在后台，不上看板、不推送；有新证据再定，2 天没有就作废（expired）
CANDIDATE, EXPIRED = "candidate", "expired"
HIDDEN = (CANDIDATE, EXPIRED)


def local_day(moment: datetime, user: User) -> str:
    return moment.astimezone(ZoneInfo(user.timezone)).strftime("%Y-%m-%d")


async def get_item(session: AsyncSession, user: User, key: str) -> FollowUp | None:
    result = await session.execute(select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.key == key))
    return result.scalars().first()


async def upsert(session: AsyncSession, user: User, key: str, signal: Signal | None, *, silent: bool, **fields) -> FollowUp:
    """创建或更新一件事。已关闭的同键事项会被重新打开（例如等对方回复 → 对方回了 → 等你回复）。"""
    item = await get_item(session, user, key)
    now = datetime.now(UTC)
    if item is None:
        await session.execute(
            insert(FollowUp).values(user_id=user.id, key=key, **{k: v for k, v in fields.items() if k in ("kind", "owner", "title")})
            .on_conflict_do_nothing(constraint="uq_follow_ups_user_key")
        )
        item = await get_item(session, user, key)
        item.signal_ids = []
    elif item.status != OPEN and not may_reopen(item, signal):
        # 迟到的旧消息（比这件事结束得还早）、或者他说过不归他/不值得/重复的：只记下依据，不重新打开
        if signal is not None and signal.id not in item.signal_ids:
            item.signal_ids = item.signal_ids + [signal.id]
        return item
    for name, value in fields.items():
        setattr(item, name, value)
    if signal is not None and signal.id not in item.signal_ids:
        item.signal_ids = item.signal_ids + [signal.id]
    if item.status != OPEN:
        item.status, item.closed_at, item.resolution = OPEN, None, None
    item.updated_at = now
    item.announced_at = now if silent else None
    return item


# 他明确说过不用再跟的：后来同一件事又有消息也不自动重新打开（“暂时不跟进”的，有新消息可以重新打开）
FINAL_DISMISSALS = ("你说这件不归你", "你说不值得提醒", "你说和别的重复了", "你说这类以后少提醒")


def may_reopen(item: FollowUp, signal: Signal | None) -> bool:
    if item.status == CANDIDATE:
        return True
    if item.resolution in FINAL_DISMISSALS:
        return False
    if signal is None or item.closed_at is None:
        return signal is not None
    at = signal.occurred_at or signal.created_at
    return at is not None and at > item.closed_at


# ---------- 同一件事跨渠道：关联和依据 ----------

MAX_EVIDENCE = 12


def add_evidence(item: FollowUp, channel: str, text: str, at: datetime | None = None, ref: str | None = None) -> None:
    """这件事每一次进展的依据（来自哪个渠道、什么时候、谁说了什么），各自保留，不覆盖。
    ref 指向原文（chat:<会话> / mail:<邮件> / doc:<链接>），在“相关材料”里可以打开看。"""
    entry = {"channel": channel, "at": (at or datetime.now(UTC)).isoformat(), "text": (text or "")[:300], **({"ref": ref} if ref else {})}
    evidence = [e for e in (item.facets or {}).get("evidence") or [] if e != entry]
    item.facets = {**(item.facets or {}), "evidence": (evidence + [entry])[-MAX_EVIDENCE:]}


def _people(item: FollowUp) -> set[str]:
    names = {str(p).lower() for p in (item.facets or {}).get("people") or [] if p}
    if item.waiting_on:
        names.add(item.waiting_on.lower())
    return names


def _overlap(names: set[str], others: set[str]) -> bool:
    return any(a and b and (a in b or b in a) for a in names for b in others)


async def related_open_items(session: AsyncSession, user: User, text: str, people: set[str] | None = None,
                             exclude: set[int] | None = None, limit: int = 5) -> list[FollowUp]:
    """可能是同一件事的、还没结的事（不管来自哪个渠道）：说到了这件事的关键词（人名不算），给了 people 时还要是同一个人。
    只是同一个人、说的是别的事的，不算——宁可漏关联，也不要把两件事并成一件。最后由模型对照内容判断。"""
    from app.proactive.casefile import _terms

    low = (text or "").lower()
    people = {p.lower() for p in people or set() if p}
    scored = []
    for item in (await session.execute(select(FollowUp).where(
            FollowUp.user_id == user.id, FollowUp.status == OPEN, FollowUp.id.notin_(exclude or {0})))).scalars():
        names = _people(item)
        if people and not _overlap(names, people):
            continue
        terms = {t for t in _terms(item.title, item.summary) if not _overlap({t}, names)}
        hits = {t for t in terms if t in low}
        if hits:
            scored.append((len(hits), item))
    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored[:limit]]


CHANNEL = {"mail-thread": "邮件", "batch": "邮件", "chat": "聊天", "mention": "群聊", "meeting": "会议纪要",
           "approval": "审批", "invite": "会议邀请", "task": "飞书任务"}


def channel_of(item: FollowUp) -> str:
    return CHANNEL.get(item.key.split(":", 1)[0], "其他")


def close(item: FollowUp, status: str, resolution: str) -> None:
    item.status, item.resolution, item.closed_at = status, resolution, datetime.now(UTC)
    item.updated_at = item.closed_at


async def link_action(session: AsyncSession, user: User, action: PendingAction) -> None:
    """对话里起草的回复也挂到对应的事上。"""
    if action.kind != "send_mail" or not action.signal_id:
        return
    signal = await session.get(Signal, action.signal_id)
    thread = signal.payload.get("thread_id") or signal.external_id
    item = await get_item(session, user, f"mail-thread:{thread}")
    if item and item.status == OPEN:
        item.action_id = action.id


# ---------- 信号 → 事项 ----------


def why_line(mail: dict, signal: Signal) -> str:
    """为什么和他有关 + 什么时候；没约定时间就写“未约定”，不编。"""
    why = mail.get("why_me") or ("还不确定是不是要你负责" if mail.get("responsible") == "unclear" else signal.reason or "")
    return f"{why}（时间：{mail.get('when') or '未约定'}）".strip()


def ask_line(mail: dict, default: str) -> str:
    ask = mail.get("ask") or default
    return f"{ask}（先确认这件事是不是归你）" if mail.get("responsible") == "unclear" else ask


async def mail_context(session: AsyncSession, user: User, signal: Signal) -> dict:
    """要他处理的邮件附带哪些上下文（只数数量和名字，原文在详情里按需打开）。"""
    from app.proactive import casefile

    mail = signal.payload or {}
    thread = mail.get("thread_id")
    earlier = await session.scalar(select(func.count(Signal.id)).where(
        Signal.user_id == user.id, Signal.kind.in_(("mail", "mail_sent")), Signal.id != signal.id,
        Signal.payload["thread_id"].astext == thread)) if thread else 0
    subject = (mail.get("subject") or "").lower()
    meeting = None
    for m in (await session.execute(select(Signal).where(
            Signal.user_id == user.id, Signal.kind == "meeting", Signal.occurred_at > datetime.now(UTC) - timedelta(days=14),
            Signal.occurred_at < datetime.now(UTC) + timedelta(days=7)).order_by(Signal.occurred_at.desc()).limit(40))).scalars():
        if len((m.title or "").strip()) >= 4 and m.title.strip().lower() in subject:
            meeting = m.title
            break
    return {"thread": earlier or 0, "attachments": [a["filename"] for a in mail.get("attachments") or []][:5],
            "links": len(casefile._links(mail.get("body"))), "meeting": meeting}


async def _from_mail(session: AsyncSession, feishu: FeishuClient, user: User, signal: Signal, fresh: bool) -> None:
    mail = signal.payload
    sender = mail.get("from_name") or mail.get("from_address") or "对方"
    action_type = mail.get("action_type") or ("reply" if signal.needs_reply else "fyi")
    if action_type == "reply":
        thread = mail.get("thread_id") or signal.external_id
        key = f"mail-thread:{thread}"
        previous = await get_item(session, user, key)
        resumed = previous is not None and previous.kind == "waiting" and previous.status == OPEN
        item = await upsert(
            session, user, key, signal, silent=not fresh,
            kind="reply", owner="me", title=f"回复 {sender}：{signal.title}",
            summary=signal.summary, waiting_on=None, remind_at=None, nudges=0,
            importance="urgent" if signal.importance == "urgent" else "normal",
            next_step=ask_line(mail, "回复这封邮件") + ("；Relay 已起草，确认后发送" if fresh else ""),
            recommendation=("对方回复了你之前的邮件。" if resumed else "") + why_line(mail, signal),
            due_at=_due(mail.get("due"), user),
        )
        item.facets = {**(item.facets or {}), "context": await mail_context(session, user, signal)}
        add_evidence(item, "邮件", f"{mail.get('from_name') or mail.get('from') or ''}：{signal.summary or signal.title}", signal.occurred_at,
                     ref=f"mail:{signal.id}")
        if fresh:
            try:
                action = await actions.prepare_mail_reply(session, feishu, user, signal.id)
                item.action_id = action.id
            except (actions.ActionError, LLMError):
                logger.exception("自动起草失败 #%s", signal.id)
                item.next_step = "回复这封邮件（自动起草失败，可以让 Relay 重试）"
    elif await close_waiting_thread(session, user, signal, fresh) and action_type == "fyi":
        return
    if action_type == "review":
        day = local_day(signal.occurred_at or datetime.now(UTC), user)
        key = f"batch:{mail.get('from_address')}:{day}"
        item = await get_item(session, user, key)
        count = len(item.signal_ids) + 1 if item else 1
        subjects = await _subjects(session, (item.signal_ids if item else []) + [signal.id])
        item = await upsert(
            session, user, key, signal, silent=not fresh,
            kind="review", owner="me",
            title=f"{sender} 发来 {count} 封邮件需要你看" if count > 1 else f"看一下 {sender} 的《{signal.title}》",
            summary="；".join(subjects[:8]) + ("……" if len(subjects) > 8 else ""),
            next_step=ask_line(mail, "审阅后回复对方"),
            recommendation=why_line(mail, signal),
            importance="urgent" if signal.importance == "urgent" else "normal",
            due_at=_due(mail.get("due"), user),
        )
        item.facets = {**(item.facets or {}), "context": await mail_context(session, user, signal)}
        add_evidence(item, "邮件", f"{mail.get('from_name') or mail.get('from') or ''}：{signal.summary or signal.title}", signal.occurred_at,
                     ref=f"mail:{signal.id}")
    signal.status = "tracked"


PROGRESS_TOOL = {
    "name": "judge_progress",
    "description": "这条新消息对“在等的事”意味着什么",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["done", "committed", "ack", "unrelated"]},
            "evidence": {"type": "string"},
            "due": {"type": "string"},
        },
        "required": ["verdict", "evidence"],
        "additionalProperties": False,
    },
}


async def judge_progress(session: AsyncSession, user: User, item: FollowUp, signal: Signal) -> dict:
    """对方的新消息对这件事意味着什么：办完了 / 答应了时间 / 只是回应 / 无关。模型出错时当作只是回应（不关闭）。"""
    from app.proactive.llm import complete_structured

    tz = ZoneInfo(user.timezone)
    waiting_for = f"{item.title}" + (f"（{item.summary}）" if item.summary else "")
    sender = (signal.payload or {}).get("from_name") or (signal.payload or {}).get("from") or "对方"
    try:
        return await judged(
            "mail_progress", user.id, f"item:{item.id}", complete_structured, PROGRESS_SYSTEM,
            f"<now>{datetime.now(tz):%Y-%m-%d %H:%M %A}</now>\n在等的事：{waiting_for}\n\n"
            f"<message>\n{sender}：《{signal.title}》\n{(signal.body or signal.summary or '')[:3000]}\n</message>\n\n"
            + "evidence " + i18n.instruction(await language_of(session, user)),
            PROGRESS_TOOL,
        )
    except Exception:  # noqa: BLE001 - 判断失败时不关闭任何事
        logger.exception("判断进展失败 #%s", item.id)
        return {"verdict": "ack", "evidence": f"{sender} 回复了《{signal.title}》"}


async def apply_mail_progress(session: AsyncSession, user: User, item: FollowUp, signal: Signal, verdict: dict) -> None:
    """按判断推进：办完 → 结束（起草的跟进邮件作废）；答应了时间 → 到时再核实；只是回应 → 不再催，记下对方说了什么。都告诉他。"""
    kind, evidence = verdict.get("verdict"), verdict.get("evidence") or signal.title
    who = item.waiting_on or "对方"
    if kind == "unrelated":
        return
    add_evidence(item, "邮件", evidence, signal.occurred_at, ref=f"mail:{signal.id}")
    pending = await session.get(PendingAction, item.action_id) if item.action_id else None
    if kind == "done":
        close(item, "done", evidence)
        if pending and pending.status == "pending":
            actions.cancel(pending)  # 起草好的跟进邮件用不上了
        note = f"{who} 那边有结果了：{evidence}"
    else:
        if pending and pending.status == "pending":
            actions.cancel(pending)  # 对方已经回应了，起草的“跟进一下”不合适了
            item.action_id = None
        item.summary = ("对方答应了：" if kind == "committed" else "对方回复了：") + evidence
        due = None
        if kind == "committed" and verdict.get("due"):
            try:
                due = datetime.fromisoformat(verdict["due"])
                due = due if due.tzinfo else due.replace(tzinfo=ZoneInfo(user.timezone))
            except ValueError:
                due = None
        item.remind_at = due or datetime.now(UTC) + WAITING_REMIND
        item.due_at = due or item.due_at
        item.nudges = 0
        item.next_step = "Relay 会在对方答应的时间核实" if due else "Relay 继续盯着，没结果会提醒你"
        item.updated_at = datetime.now(UTC)
        note = f"{who} " + ("答应了：" if kind == "committed" else "回复了：") + evidence
    if signal.id not in (item.signal_ids or []) and signal.kind != "invitation":
        item.signal_ids = (item.signal_ids or []) + [signal.id]
    await add_signal(session, user, "mail", f"progress:{item.id}:{signal.id}", kind="progress", title=note,
                     payload={"item_id": item.id}, occurred_at=datetime.now(UTC), status="result")


async def close_waiting_thread(session: AsyncSession, user: User, signal: Signal, fresh: bool) -> bool:
    """对方在正在等回复的线程里回了信，但不需要他再回（告知、确认、致谢）：这件事结束了，告诉他对方说了什么。"""
    """对方在正在等回复的线程里回了信（不需要他再回的那种）：对照在等的事判断，办完了才结束。"""
    mail = signal.payload or {}
    thread = mail.get("thread_id")
    waiting = await get_item(session, user, f"mail-thread:{thread}") if thread else None
    if waiting is None or waiting.status != OPEN or waiting.kind != "waiting":
        return False
    verdict = await judge_progress(session, user, waiting, signal)
    if verdict.get("verdict") == "unrelated":
        verdict = {**verdict, "verdict": "ack"}  # 同一个线程里的回信总归是对这件事的回应
    await apply_mail_progress(session, user, waiting, signal, verdict)
    signal.status = "done"
    return True


async def _subjects(session: AsyncSession, signal_ids: list[int]) -> list[str]:
    result = await session.execute(select(Signal.title).where(Signal.id.in_(signal_ids)).order_by(Signal.id))
    return list(result.scalars())


def _due(hint: str | None, user: User) -> datetime | None:
    local = datetime.now(ZoneInfo(user.timezone))
    if hint == "today":
        return local.replace(hour=18, minute=0, second=0, microsecond=0).astimezone(UTC)
    if hint == "this_week":
        friday = local + timedelta(days=max(0, 4 - local.weekday()))
        return friday.replace(hour=18, minute=0, second=0, microsecond=0).astimezone(UTC)
    return None


async def _from_invitation(session: AsyncSession, user: User, signal: Signal, fresh: bool) -> None:
    conflicts = await cards.conflicts_for(session, signal)
    suggested = "tentative" if conflicts else "accept"
    item = await upsert(
        session, user, f"invite:{signal.payload['event_id']}", signal, silent=not fresh,
        kind="invitation", owner="me", title=f"会议邀请：{signal.title}",
        summary=f"{signal.payload.get('organizer') or '有人'}邀请你参加，时间 "
        f"{signal.occurred_at.astimezone(ZoneInfo(user.timezone)):%m-%d %H:%M}",
        next_step="回复这个邀请", due_at=signal.occurred_at,
        recommendation=(f"和「{'、'.join(conflicts)}」时间冲突，建议先回复待定" if conflicts else "那个时段你没有别的安排，建议接受"),
        url=signal.payload.get("app_link"),
    )
    action = await actions.prepare_rsvp(session, user, signal.id, suggested)
    item.action_id = action.id
    signal.status = "tracked"


APPROVAL_STALL = timedelta(days=3)


async def _from_approval_update(session: AsyncSession, user: User, signal: Signal, fresh: bool) -> None:
    """我发起的审批：审批中 → 等别人（3 天没结果提醒）；驳回/撤回 → 等你重新提交；通过 → 只通知一次。
    抄送不会走到这里（同步时就标为 ignored）。"""
    from app.sources.approval import RUNNING, SENT_BACK

    p = signal.payload
    key = f"approval-update:{signal.external_id}"
    title = p.get("title") or p.get("definition_name") or "审批"
    status = str(p.get("process_status"))
    if p.get("category") != "initiated":
        signal.status = "ignored"
        return
    if status in RUNNING:
        await upsert(
            session, user, key, signal, silent=True, kind="waiting", owner="others", title=f"等审批：{title}",
            summary=None, waiting_on="审批人", next_step="Relay 盯着审批进度，3 天没结果会提醒你催一下",
            url=signal.url, remind_at=datetime.now(UTC) + APPROVAL_STALL, nudges=0,
        )
        signal.status = "tracked"
    elif status in SENT_BACK:
        await upsert(
            session, user, key, signal, silent=not fresh, kind="review", owner="me",
            title=f"{title}（{'被驳回' if status in ('3', 'Rejected', 'REJECTED') else '已撤回'}）",
            summary=signal.body, next_step="看一下原因，修改后重新提交", url=signal.url, remind_at=None,
        )
        signal.status = "tracked"
    else:
        # 通过（或其他终态）：关闭“等审批”，只告诉他一声，不留待办
        item = await get_item(session, user, key)
        if item and item.status == OPEN:
            close(item, "done", f"审批{signal.body or '已结束'}")
        signal.status = "result" if fresh else "done"


async def result_facts(session: AsyncSession, user: User) -> list[str]:
    """有了结果、只需要告诉一声的事（例如我发起的审批通过了），取出后标为已告知。"""
    signals = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.status == "result").order_by(Signal.id)
    )).scalars().all()
    for signal in signals:
        signal.status = "done"
    return [
        f"{s.payload.get('from_name') or s.payload.get('from') or '对方'} 回复了《{s.title}》：{s.summary or ''}".rstrip("：")
        if s.kind == "mail" else s.title
        for s in signals
    ]


async def leave_overlap(session: AsyncSession, user: User, signal: Signal) -> str | None:
    """同一时间段还有谁请假（只看得到他能看到的审批：要他审批的、抄送他的）。"""
    mine = (signal.payload.get("detail") or {}).get("leave")
    if not mine:
        return None
    start, end = datetime.fromisoformat(mine[0]), datetime.fromisoformat(mine[1])
    me = set(signal.payload.get("initiators") or [])
    rows = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind.in_(["approval_pending", "approval_update"]),
                             Signal.id != signal.id, Signal.payload["detail"]["leave"].isnot(None))
        .order_by(Signal.id.desc()).limit(300)
    )).scalars().all()
    others = {}
    for row in rows:
        other = row.payload["detail"]["leave"]
        if not other or set(row.payload.get("initiators") or []) & me:
            continue
        if str(row.payload.get("process_status")) in ("3", "4", "REJECTED", "CANCELED", "Rejected", "Canceled"):
            continue
        if datetime.fromisoformat(other[0]) < end and start < datetime.fromisoformat(other[1]):
            name = "、".join(row.payload.get("initiator_names") or []) or "有人"
            others.setdefault(name, f"{datetime.fromisoformat(other[0]):%m-%d}~{datetime.fromisoformat(other[1]) - timedelta(minutes=1):%m-%d}")
    if not others:
        return "同期没有看到其他人请假（只统计要你审批或抄送你的请假单）"
    return "同期也请假的：" + "；".join(f"{n}（{r}）" for n, r in list(others.items())[:5])


async def _from_simple(session: AsyncSession, user: User, signal: Signal, fresh: bool) -> None:
    if signal.kind == "approval_update":
        await _from_approval_update(session, user, signal, fresh)
        return
    elif signal.kind == "approval_pending":
        initiators = "、".join(signal.payload.get("initiator_names") or []) or "有人"
        await upsert(
            session, user, f"approval:{signal.external_id}", signal, silent=not fresh,
            kind="approval", owner="me", title=f"{initiators}：{signal.title}",
            summary=await summarize_approval(signal, await language_of(session, user)), next_step=approval_next_step(signal), url=signal.url,
            recommendation=await leave_overlap(session, user, signal),
            remind_at=datetime.now(UTC) + APPROVAL_REMIND,
        )
    elif signal.kind == "attendance_missing":
        await upsert(
            session, user, f"attendance:{signal.external_id}", signal, silent=not fresh,
            kind="attendance", owner="me", title=signal.title, summary=signal.body,
            next_step="去飞书打卡，或者申请补卡", importance="urgent",
        )
    elif signal.kind == "biz_event":
        p = signal.payload
        due = datetime.fromisoformat(p["due_at"]) if p.get("due_at") else None
        await upsert(
            session, user, f"biz:{p['integration_key']}:{p['group_key']}", signal, silent=not fresh,
            kind="biz", owner="me", title=f"{p['integration']}：{signal.title}",
            summary=(signal.body or "")[:300] or None, next_step=p.get("action_hint") or f"去{p['integration']}处理",
            url=signal.url, due_at=due, importance="urgent" if signal.importance == "urgent" else "normal",
        )
    elif signal.kind == "task":
        p = signal.payload or {}
        creator = p.get("creator_name") or "同事"
        await upsert(
            session, user, f"task:{signal.external_id}", signal, silent=not fresh,
            kind="task", owner="me", title=f"{creator} 派给你的任务：{signal.title}", summary=(signal.body or "")[:300] or None,
            next_step="完成后在飞书任务里勾选完成", url=signal.url,
            due_at=datetime.fromisoformat(p["due"]) if p.get("due") else None,
            facets={"people": [creator], "open_ids": [p.get("creator_open_id")]},
        )
    elif signal.kind == "mention":
        p = signal.payload or {}
        chat = p.get("chat_name") or "群聊"
        await upsert(
            session, user, f"mention:{signal.external_id}", signal, silent=not fresh,
            kind="mention", owner="me",
            # 读过上下文、确认是在问他的，标题直接写问的是什么
            title=f"{p.get('sender_name') or '有人'} 在{chat}问你：{p['ask']}" if p.get("ask") else f"{chat}里@你的消息还没回",
            summary=signal.body, next_step="在群里回复",
            url=signal.url or (f"https://applink.feishu.cn/client/chat/open?openChatId={p['chat_id']}" if p.get("chat_id") else None),
            facets={"people": [p.get("sender_name")] if p.get("sender_name") else [], "chat": p.get("chat_name")},
        )
    signal.status = "tracked"


def approval_next_step(signal: Signal) -> str:
    """需要审批人补填/分配的单子只能去飞书原生审批处理；拿不到明细时也保守处理。"""
    detail = signal.payload.get("detail")
    if approval_source.needs_input(detail):
        hint = (detail or {}).get("input_hint")
        return "去飞书审批" + (f"（需要填写：{hint}）" if hint else "")
    return "批准或驳回"


NO_DETAIL = "表单内容暂时读不到，需要在飞书里看原单"


async def summarize_approval(signal: Signal, lang: str = "zh") -> str | None:
    """一句话说清这张单子要批什么；没有明细时退回到发起人信息。"""
    detail = signal.payload.get("detail")
    if not detail or not detail.get("fields"):
        return NO_DETAIL  # 标题里已经有发起人；读不到表单就直说，不复述发起人
    if detail.get("leave") or len(detail["fields"]) <= 4:
        return None  # 请假、补卡这类字段很少的单子：卡片上的申请内容一眼就能看完，不再加一句复述
    fields = "\n".join(f"{f['name']}：{f['value']}" for f in detail["fields"])
    try:
        return await judged(
            "approval_summary", signal.user_id, f"signal:{signal.id}", complete_text, APPROVAL_SUMMARY_SYSTEM,
            f"<approval>\n审批类型：{detail.get('approval_name')}\n发起人：{'、'.join(signal.payload.get('initiator_names') or [])}\n{fields}\n</approval>\n\n"
            + i18n.instruction(lang),
        )
    except LLMError:
        return signal.body


async def refresh_approvals(session: AsyncSession, user: User) -> None:
    """明细是后补的：补到之后重新概括（摘要还停留在“发起人：……”时），并更新要他做什么。"""
    result = await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.kind == "approval", FollowUp.status == OPEN)
    )
    for item in result.scalars():
        signal = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
        if signal is None:
            continue
        item.next_step = approval_next_step(signal)
        if item.summary in (None, NO_DETAIL) or item.summary.startswith("发起人："):
            if (signal.payload.get("detail") or {}).get("fields"):
                item.summary = await summarize_approval(signal, await language_of(session, user))
        if item.recommendation is None:
            item.recommendation = await leave_overlap(session, user, signal)
    await session.commit()


async def track(session: AsyncSession, feishu: FeishuClient, user: User) -> None:
    """把判断完的信号归并成事项。fresh（刚到的）会通知用户，存量的只静默建档。"""
    result = await session.execute(
        select(Signal).where(
            Signal.user_id == user.id,
            Signal.status.in_(["notify", "digest", "notified", "digested"]),
            Signal.kind.in_(["mail", "invitation", "approval_pending", "approval_update", "attendance_missing", "mention", "biz_event", "task"]),
        ).order_by(Signal.id)
    )
    for signal in result.scalars():
        fresh = signal.status == "notify"
        try:
            async with session.begin_nested():
                if signal.kind == "mail":
                    if signal.importance is None:
                        continue  # 还没分级（存量邮件分批分级），下一轮再处理
                    if signal.importance in ("urgent", "normal"):
                        await _from_mail(session, feishu, user, signal, fresh)
                    elif not await close_waiting_thread(session, user, signal, fresh):
                        signal.status = "ignored"
                elif signal.kind == "invitation":
                    await _from_invitation(session, user, signal, fresh)
                else:
                    await _from_simple(session, user, signal, fresh)
        except Exception:
            logger.exception("建立跟进事项失败 #%s", signal.id)
            signal.status = "ignored"
    await session.commit()


# ---------- 自动推进与关闭 ----------


REPLY_STATE_TOOL = {
    "name": "reply_state",
    "description": "判断他回复之后还要不要等对方",
    "input_schema": {
        "type": "object",
        "properties": {"state": {"type": "string", "enum": ["done", "waiting", "mine"]}, "summary": {"type": "string"}},
        "required": ["state", "summary"],
        "additionalProperties": False,
    },
}


async def _my_reply(session: AsyncSession, user: User, thread: str | None, action: PendingAction | None, after) -> Signal | str | None:
    """他刚回的那封：Relay 替他发的用草稿正文，他自己在飞书里回的用已发送邮件的正文。"""
    if action and action.status == "done" and action.kind == "send_mail":
        return action.payload.get("body")
    if not thread:
        return None
    sent = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind == "mail_sent", Signal.payload["thread_id"].astext == thread,
                             Signal.occurred_at > after).order_by(Signal.occurred_at.desc()).limit(1)
    )).scalars().first()
    return sent.body if sent else None


def reply_state_input(their_text: str, mine: str, lang: str) -> str:
    """回复状态（reply_state）的输入：对方上一封 + 他的回复。线上和回放共用。"""
    return f"<mail>\n对方上一封：{their_text}\n\n他的回复：\n{mine[:3000]}\n</mail>\n\nsummary " + i18n.instruction(lang)


async def judge_reply(theirs: Signal | None, mine: str | None, lang: str = "zh") -> tuple[str, str | None]:
    """他回复之后这件事在谁手里：done 办完了 / waiting 等对方 / mine 他答应了但还没给（“晚点看”“还在处理”）。
    拿不到正文或模型出错时，保守地当作等对方（不关掉）。"""
    if not mine:
        return "waiting", None
    their_text = f"{theirs.payload.get('from')}：《{theirs.title}》\n{(theirs.body or '')[:3000]}" if theirs else "（不知道）"
    try:
        from app.proactive.llm import complete_structured

        result = await judged(
            "reply_state", theirs.user_id if theirs else None, f"signal:{theirs.id}" if theirs else None, complete_structured, REPLY_STATE_SYSTEM,
            reply_state_input(their_text, mine, lang), REPLY_STATE_TOOL,
        )
        return result.get("state") or "waiting", (result.get("summary") or None)
    except Exception:  # noqa: BLE001 - 判断失败不影响主流程
        logger.exception("判断回复状态失败")
        return "waiting", None


def after_my_reply(item: FollowUp, last: Signal | None, state: str, summary: str | None) -> None:
    """按他回了什么推进同一个事项：办完就结束；等对方就转成等对方；他答应了还没给就留在他这里（不重新提醒，明天再看）。"""
    now = datetime.now(UTC)
    if state == "done":
        close(item, "done", summary or "你已经回复了")
        return
    if state == "mine":
        # 记下这次回复已经判断过：之后只有他再回一封才重新判断，不是每轮都问一次模型
        item.facets = {**(item.facets or {}), "replied_seen": now.isoformat()}
        item.summary = summary or "你回复了，但答应的事还没给"
        item.next_step = "把答应的给对方"
        item.action_id, item.remind_at, item.nudges, item.updated_at = None, now + timedelta(days=1), 0, now
        return
    who = (last.payload.get("from_name") or last.payload.get("from_address")) if last else None
    # 转成“等对方”时，所有描述“该你做什么”的字段一起换掉，不能留下“紧急、今天截止、回复对方”这类旧内容
    item.kind, item.owner, item.waiting_on = "waiting", "others", who
    item.title = f"等 {who or '对方'} 回复"
    item.summary = summary or (f"你已回复《{last.title}》" if last else "你已回复")
    item.next_step = "Relay 盯着对方的回复，3 天没回会提醒你"
    item.recommendation, item.action_id, item.importance, item.due_at = None, None, "normal", None
    item.remind_at, item.nudges, item.updated_at = now + WAITING_REMIND, 0, now


def _who(signal: Signal | None) -> tuple[str | None, str | None]:
    if signal is None:
        return None, None
    p = signal.payload or {}
    return (p.get("from_address") or "").lower() or None, p.get("from_name") or None


async def _counterpart_activity(session: AsyncSession, user: User, item: FollowUp, last: Signal | None) -> Signal | None:
    """他回复之后，对方在别处有没有动静：另一封邮件、会议邀请。有就说明对方已经回应了，不该再催。"""
    address, name = _who(last)
    if not (address or name):
        return None
    thread = (last.payload or {}).get("thread_id") if last else None
    conditions = []
    if address:
        conditions.append(func.lower(Signal.payload["from_address"].astext) == address)
    if name:
        conditions.append(Signal.payload["from_name"].astext == name)
        conditions.append(Signal.payload["organizer"].astext == name)
    rows = (await session.execute(
        select(Signal).where(
            Signal.user_id == user.id, Signal.kind.in_(["mail", "invitation"]), or_(*conditions),
            # 邮件看收到时间；会议邀请的 occurred_at 是开会时间，看它进来的时间
            or_(and_(Signal.kind == "mail", Signal.occurred_at > item.updated_at),
                and_(Signal.kind == "invitation", Signal.created_at > item.updated_at)),
            Signal.id.notin_(item.signal_ids or [0]),
        ).order_by(Signal.occurred_at).limit(10)
    )).scalars().all()
    return next((s for s in rows if (not thread or (s.payload or {}).get("thread_id") != thread)
                 and item.id not in (s.payload or {}).get("judged_items", [])), None)


async def advance(session: AsyncSession, user: User) -> None:
    result = await session.execute(select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == OPEN))
    for item in result.scalars():
        action = await session.get(PendingAction, item.action_id) if item.action_id else None
        signals = [await session.get(Signal, sid) for sid in item.signal_ids[-1:]]
        last = signals[0] if signals else None
        replied_elsewhere = False
        if item.kind == "reply" and last and not (action and action.status == "done"):
            thread = last.payload.get("thread_id")
            replied_elsewhere = bool(thread) and bool(await session.scalar(
                select(Signal.id).where(Signal.user_id == user.id, Signal.kind == "mail_sent",
                                        Signal.payload["thread_id"].astext == thread,
                                        Signal.occurred_at > seen_after(item, last.occurred_at or item.created_at)).limit(1)
            ))
            if replied_elsewhere and action and action.status == "pending":
                actions.cancel(action)  # Relay 起草的那版用不上了
        if item.kind == "reply" and ((action and action.status == "done") or replied_elsewhere):
            # 回复已发出：看他回了什么，判断是已经办完，还是要等对方回应
            mine = await _my_reply(session, user, (last.payload or {}).get("thread_id") if last else None, action,
                                   seen_after(item, (last.occurred_at if last else None) or item.created_at))
            state, summary = await judge_reply(last, mine, await language_of(session, user))
            after_my_reply(item, last, state, summary)
        elif item.kind == "waiting" and item.key.startswith("mail-thread:"):
            # 对方在别的线程来信、发来会议邀请：对照在等的事判断是不是对这件事的回应，不是一有动静就关
            activity = await _counterpart_activity(session, user, item, last)
            if activity is not None:
                activity.payload = {**(activity.payload or {}), "judged_items": [*(activity.payload or {}).get("judged_items", []), item.id]}
                await apply_mail_progress(session, user, item, activity, await judge_progress(session, user, item, activity))
        elif item.kind == "invitation" and last:
            meeting = (await session.execute(
                select(Signal).where(Signal.user_id == user.id, Signal.kind == "meeting",
                                     Signal.payload["event_id"].astext == last.payload.get("event_id"))
            )).scalars().first()
            rsvp = (meeting.payload if meeting else last.payload).get("rsvp")
            if action and action.status == "done":
                close(item, "done", action.result or "已回复邀请")
            elif rsvp and rsvp != "needs_action":
                close(item, "done", "你已经回复了这个邀请")
            elif last.occurred_at and last.occurred_at < datetime.now(UTC):
                close(item, "dismissed", "会议已经开始，不再跟进")
        elif item.kind == "approval" and last and last.status == "done":
            close(item, "done", "审批已处理")
        elif item.kind == "task" and last and last.status == "done":
            close(item, "done", "你在飞书任务里完成了（或任务已取消）")
        elif item.kind == "mention" and last and last.status == "done":
            close(item, "done", "你已经在群里回复了")
        elif item.kind == "attendance" and item.created_at < datetime.now(UTC) - timedelta(hours=12):
            close(item, "dismissed", "已过期")
        elif item.kind == "review":
            reason = await review_closure(session, user, item)
            if reason and reason[0] == "replied":
                # 他回了信不一定就办完了：看他回了什么——结束，还是转成等对方
                thread = (last.payload or {}).get("thread_id") if last else None
                mine = await _my_reply(session, user, thread, None, seen_after(item, (last.occurred_at if last else None) or item.created_at))
                state, summary = await judge_reply(last, mine, await language_of(session, user))
                after_my_reply(item, last, state, summary)
            elif reason:
                close(item, *reason)
    # 事情已经结束（在 Relay 之外回了信、在飞书里审批了……）：还没发出的草稿、跟进邮件作废，不再让他确认
    await session.flush()
    stale = (await session.execute(select(PendingAction).where(
        PendingAction.user_id == user.id, PendingAction.status == "pending",
        PendingAction.id.in_(select(FollowUp.action_id).where(
            FollowUp.user_id == user.id, FollowUp.status.in_(("done", "dismissed")), FollowUp.action_id.isnot(None))),
    ))).scalars().all()
    for action in stale:
        actions.cancel(action)
        action.result = "事情已经结束，这份草稿作废"
    await session.commit()


REVIEW_QUIET = timedelta(days=3)
DUE_SOON = timedelta(hours=3)


def seen_after(item: FollowUp, default: datetime) -> datetime:
    """他的回复判断到哪了：判断过的回复不再判断。"""
    seen = (item.facets or {}).get("replied_seen")
    return max(default, datetime.fromisoformat(seen)) if seen else default


async def review_closure(session: AsyncSession, user: User, item: FollowUp) -> tuple[str, str] | None:
    """邮件里“请你看一下”的事什么时候结束（以前没有规则，14 天里 386 件只结了 27 件）：
    - 他在这些邮件的线程里回复了 → 办完；
    - 写了期限的，过期一天 → 不再跟进；
    - 没写期限、不紧急，3 天没有新的往来 → 不再跟进（在进展里能找到，需要时再翻）。"""
    now = datetime.now(UTC)
    threads = set()
    for sid in item.signal_ids or []:
        signal = await session.get(Signal, sid)
        if signal is not None and (signal.payload or {}).get("thread_id"):
            threads.add(signal.payload["thread_id"])
    if threads and await session.scalar(select(Signal.id).where(
            Signal.user_id == user.id, Signal.kind == "mail_sent", Signal.payload["thread_id"].astext.in_(threads),
            Signal.occurred_at > seen_after(item, item.created_at - timedelta(minutes=5))).limit(1)):
        return "replied", "你已经回复了"
    if item.due_at is not None:
        return ("dismissed", "期限已过，不再跟进") if item.due_at < now - timedelta(days=1) else None
    if item.importance != "urgent" and (item.updated_at or item.created_at) < now - REVIEW_QUIET:
        return "dismissed", "3 天没有新的往来，不再跟进"
    return None


async def due_reminders(session: AsyncSession, feishu: FeishuClient, user: User) -> list[tuple[FollowUp, str]]:
    """到了提醒时间的事项。等别人的会顺手起草一封跟进邮件（同样等用户确认）。"""
    now = datetime.now(UTC)
    result = await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == OPEN,
                               FollowUp.remind_at <= now, FollowUp.nudges < MAX_NUDGES)
    )
    reminders = []
    for item in result.scalars():
        days = (now - item.updated_at).days or 1
        if item.key.startswith("approval-update:"):
            fact = f"他发起的《{item.title.removeprefix('等审批：')}》已经 {days} 天没有结果，可以催一下审批人"
            item.next_step = "催一下审批人，或在飞书里查看卡在哪个节点"
        elif item.kind == "waiting":
            last = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
            fact = f"{item.waiting_on or '对方'} 已经 {days} 天没回复《{last.title if last else item.title}》"
            if last:
                try:
                    body = await judged(
                        "followup_draft", user.id, f"item:{item.id}", complete_text, FOLLOWUP_SYSTEM,
                        f"我是 {user.name}。<mail>\n原邮件：{last.title}\n{(last.body or '')[:3000]}\n</mail>\n"
                        f"我已经回复过，对方 {days} 天没回。写一封简短礼貌的跟进邮件正文。",
                    )
                    action = PendingAction(
                        user_id=user.id, kind="send_mail", signal_id=last.id,
                        summary=f"跟进 {item.waiting_on or '对方'}：{last.title}",
                        payload={"to": last.payload.get("from_address"), "subject": f"Re: {last.title}", "body": body},
                    )
                    session.add(action)
                    await session.flush()
                    item.action_id = action.id
                    fact += "，你已经替他起草了一封跟进邮件"
                except LLMError:
                    pass
            item.next_step = "确认是否发出跟进邮件"
        elif item.kind == "approval":
            fact = f"审批《{item.title}》已经等他处理 {days} 天了"
        else:
            fact = f"《{item.title}》还没处理"
        item.nudges += 1
        item.remind_at = now + (WAITING_REMIND if item.kind == "waiting" else timedelta(days=1))
        item.announced_at = None  # 让它出现在这次的通知里
        reminders.append((item, fact))
    # 临近明确的截止时间（3 小时内）还没处理：再说一次，每个截止时间只说一次；没约定时间的不会因此提醒
    soon = (await session.execute(select(FollowUp).where(
        FollowUp.user_id == user.id, FollowUp.status == OPEN, FollowUp.owner == "me", FollowUp.pushed_at.isnot(None),
        FollowUp.due_at > now, FollowUp.due_at <= now + DUE_SOON,
    ))).scalars().all()
    for item in soon:
        if (item.facets or {}).get("due_alerted") == item.due_at.isoformat() or item.pushed_at >= item.due_at - DUE_SOON:
            continue  # 这个截止时间已经说过（或者刚提醒时就已经很近了）
        hours = max(1, int((item.due_at - now).total_seconds() // 3600))
        item.facets = {**(item.facets or {}), "due_alerted": item.due_at.isoformat()}
        item.announced_at = None
        reminders.append((item, f"《{item.title}》约 {hours} 小时后到截止时间"))
    # 有人在等他：提醒过一次、过了一天还没处理，再提醒一次（说清楚谁、等了多久），之后不再催
    stalled = (await session.execute(select(FollowUp).where(
        FollowUp.user_id == user.id, FollowUp.status == OPEN, FollowUp.owner == "me", FollowUp.kind.in_(attention.ASK_KINDS),
        FollowUp.pushed_at <= now - timedelta(days=1), FollowUp.nudges == 0, FollowUp.remind_at.is_(None),
    ))).scalars().all()
    for item in stalled:
        signal = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
        person = attention.asker(item, attention.facets(item, signal))
        if not person:
            continue
        fact = f"{person} 已经等你 {attention._span(attention.waited(item, signal, now) or timedelta(days=1))}：{item.title}"
        item.nudges, item.remind_at, item.announced_at = 1, now + timedelta(days=1), None
        item.attention_note = f"{person} 还在等你"
        reminders.append((item, fact))
    await session.flush()
    return reminders


# ---------- 在主线里告诉用户 ----------


ask = cards.ask


def describe(item: FollowUp, action: PendingAction | None = None) -> str:
    parts = [item.title]
    if item.summary:
        parts.append(item.summary)
    if item.recommendation:
        parts.append(f"建议：{item.recommendation}")
    if item.action_id:
        parts.append("已经替他准备好了")
    parts.append(f"需要他：{ask(item, action)}")
    return "——".join(parts)


async def _refresh_last_card(session: AsyncSession, feishu: FeishuClient, user: User, item: FollowUp) -> None:
    """同一件事刚发过卡片：按最新状态原地更新那张卡片，而不是再发一条。"""
    from app.models import FeishuCard
    from app.proactive.push import refresh

    record = (await session.execute(
        select(FeishuCard).where(FeishuCard.user_id == user.id,
                                 FeishuCard.sections.contains([[[{"kind": "item", "item_id": item.id}]]]))
        .order_by(FeishuCard.created_at.desc()).limit(1)
    )).scalars().first()
    if record is None:
        return
    try:
        await refresh(session, feishu, user, record.message_id)
    except FeishuError:
        logger.warning("原地更新卡片失败 #%s", item.id)


CARD_LIFE = timedelta(days=3)
PUSH_RETRIES = 3


def _card_items(record) -> set[int]:
    return {c.get("item_id") for _, group in record.sections or [] for c in group if c.get("kind") == "item"}


async def supersede(session: AsyncSession, feishu: FeishuClient, user: User, item_ids: list[int], keep: str | None) -> None:
    """这几件事另发了新提醒：旧卡片上它们收成一行（没有按钮），指向新的那条。"""
    from app.models import FeishuCard
    from app.proactive.push import refresh

    if not item_ids:
        return
    ids = set(item_ids)
    records = (await session.execute(select(FeishuCard).where(
        FeishuCard.user_id == user.id, FeishuCard.created_at > datetime.now(UTC) - CARD_LIFE, FeishuCard.message_id != (keep or ""),
    ))).scalars().all()
    for record in records:
        if not _card_items(record) & ids:
            continue
        record.sections = [[label, [({**c, "moved": True} if c.get("kind") == "item" and c.get("item_id") in ids else c) for c in group]]
                           for label, group in record.sections]
        try:
            await refresh(session, feishu, user, record.message_id)
        except FeishuError:
            logger.warning("旧卡片收起失败 %s", record.message_id)


async def sync_cards(session: AsyncSession, feishu: FeishuClient, user: User, limit: int = 20) -> int:
    """卡片跟着事项走：最近 3 天的卡片里，有事项状态变了（办完、有了进展、转成等对方……）就原地更新，不另发。"""
    from app.models import FeishuCard
    from app.proactive.push import refresh

    records = (await session.execute(select(FeishuCard).where(
        FeishuCard.user_id == user.id, FeishuCard.created_at > datetime.now(UTC) - CARD_LIFE,
    ).order_by(FeishuCard.created_at.desc()).limit(60))).scalars().all()
    updated = 0
    for record in records:
        ids = _card_items(record)
        if not ids:
            continue
        changed = await session.scalar(select(func.max(FollowUp.updated_at)).where(FollowUp.id.in_(ids)))
        if changed is None or changed <= (record.refreshed_at or record.created_at):
            continue
        try:
            await refresh(session, feishu, user, record.message_id)
            updated += 1
        except FeishuError:
            logger.warning("同步卡片状态失败 %s", record.message_id)
        if updated >= limit:
            break
    await session.commit()
    return updated


async def unread_context(session: AsyncSession, pending: list[FollowUp]) -> set[int]:
    """推送前复查：聊天里来的事，如果那段会话还有没读过的新消息（可能就是答复或结论），先不说，等读完再判断。"""
    held = set()
    for item in pending:
        if not item.key.startswith(("chat:", "mention:")) or not item.url or "openChatId=" not in item.url:
            continue
        chat_id = item.url.split("openChatId=", 1)[1]
        newer = await session.scalar(select(ChatMessage.id).where(
            ChatMessage.tenant_id == select(User.tenant_id).where(User.id == item.user_id).scalar_subquery(),
            ChatMessage.chat_id == chat_id, ChatMessage.processed.is_(False), ChatMessage.created_at >= item.created_at - timedelta(hours=1),
        ).limit(1))
        if newer is not None:
            held.add(item.id)
    return held


async def announce(
    session: AsyncSession, feishu: FeishuClient, user: User, settings: dict,
    reminders: list[tuple[FollowUp, str]] | None = None,
) -> None:
    """把还没告诉他的事按档位告诉他（见 attention）：

    - critical（紧急、上级链、他说过随时告诉的）马上说，不受次数限制；紧急的在免打扰时段也说；
    - 一般的“今天要处理”受每小时次数限制，名额用完就等空出来，有 critical 要说时顺带一起说；
    - 打扰他的时候，手上攒着的不急的事附在后面；不急的事否则攒到汇总时间；只放简报的留给简报；静默的只在看板里；
    - 同一件事刚发过（REPEAT_COOLDOWN 内）又有动静：原地更新那张卡片，不另发，升级成紧急的除外；
    - “有结果了”这类消息跟着下一次说，不单独打扰。
    """
    now = datetime.now(UTC)
    pending = list((await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == OPEN, FollowUp.announced_at.is_(None))
        .order_by(FollowUp.id)
    )).scalars())
    held_for_context = await unread_context(session, pending)
    pending = [i for i in pending if i.id not in held_for_context]
    reminded = {i.id for i, _ in reminders or []}  # 到了提醒时间 / 对方等太久：要另发一条，不只是原地更新
    for item in [i for i in pending if i.id not in reminded and attention.is_repeat(i, now)]:
        item.announced_at = now
        await _refresh_last_card(session, feishu, user, item)
        pending.remove(item)
    groups, critical_ids = await attention.apply(session, feishu, user, pending, now)
    quiet = in_quiet_hours(settings, user.timezone)
    critical = [i for i in groups["now"] if i.id in critical_ids and (not quiet or i.importance == "urgent")]
    regular = [] if quiet else [i for i in groups["now"] if i.id not in critical_ids]
    later = groups["batch"] + ([] if settings.get("brief_enabled", True) else groups["brief"])
    if regular and not critical and await attention.interrupts_left(session, user, settings) <= 0:
        for item in regular:  # 这一小时提醒得够多了：等名额空出来再说，不降到汇总
            item.attention_note = f"{(item.attention_note or '今天要处理').split('（')[0]}（这一小时已经提醒过你几次，稍后就告诉你）"
        held, regular = regular, []
    else:
        held = []
    interrupt = critical + regular
    digest = not interrupt and attention.digest_due(settings, user, await attention.last_digest(session, user), now)
    if not interrupt and not digest:
        await session.commit()
        return
    riding = [] if quiet else later  # 打扰他的时候，手上攒着的不急的事一起给他，省得过会儿再打断一次
    head = interrupt if interrupt else held + later  # 到了汇总时间：等名额的也一起说
    shown = head + (riding if interrupt else [])
    # 有了结果、只需告诉一声的事放进汇总；打断他的这张卡片只说要他处理的事（标题的数量和正文说的是同一批）
    results = [] if quiet or interrupt else await result_facts(session, user)
    if not shown and not results:
        if digest:
            await attention.note_digest(session, user, now)
        await session.commit()
        return
    by_item = {item.id: fact for item, fact in reminders or []}
    about = [by_item.get(i.id) or describe(i, await session.get(PendingAction, i.action_id) if i.action_id else None) for i in head]
    facts = results + about
    lang = i18n.user_language(settings)
    if len(head) <= 1 and not results:
        text = ""  # 只有一件事：卡片已经说清楚了，不再加一句复述（顺带的不急的事在下面单独一组，不用说）
    else:
        try:
            text = await judged("notice_text", user.id, f"user:{user.id}", complete_text, NARRATE_SYSTEM, f"用户：{user.name}\n\n发生的事：\n" + "\n".join(f"- {f}" for f in facts)
                                       + "\n\n" + i18n.instruction(lang))
        except LLMError:
            text = "\n".join(f"- {f}" for f in results)
    limit = 8 if interrupt else 12
    sections = [["", [{"kind": "item", "item_id": i.id} for i in head[:limit]]]]
    if interrupt and riding:
        sections.append([i18n.t(lang, "also_pending"), [{"kind": "item", "item_id": i.id} for i in riding[:limit]]])
    overflow = max(0, len(head) - limit) + (max(0, len(riding) - limit) if interrupt else 0)
    if overflow:
        sections.append(["", [{"kind": "note", "text": f"还有 {overflow} 件在网页看板里"}]])
    flat = [card for _, group in sections for card in group]
    try:
        await post(session, user, event="Relay 告诉用户：\n" + "\n".join(facts), text=text, cards=flat,
                   notice="interrupt" if interrupt else "digest")
    except ConversationBusy:
        await session.rollback()
        return
    renotified = {i.id for i in shown if i.pushed_at is not None}
    before = {i.id: (i.pushed_at, i.pushed_importance, (i.facets or {}).get("pushed_state")) for i in shown}
    for item in shown:
        item.announced_at = item.pushed_at = now
        item.pushed_importance = item.importance
        item.facets = {**(item.facets or {}), "pushed_state": attention.pushed_state(item)}
    if interrupt:
        await attention.note_interrupt(session, user, now)
    else:
        await attention.note_digest(session, user, now)
    await session.commit()
    try:
        title = (i18n.t(lang, "things_to_know", n=len(interrupt)) if interrupt
                 else i18n.t(lang, "digest", n=len(head) + len(results)) if head or results else i18n.t(lang, "update"))
        message_id = await push(session, feishu, user, title, text, sections=sections)
        # 同一件事以前的卡片：收成一行指向这条新的，不留两张都能操作的卡片
        await supersede(session, feishu, user, [i.id for i in shown if i.id in renotified], message_id)
    except FeishuError:
        # 没发出去：下一轮再发（恢复成没推送过的样子），同一件事最多重试 3 次，避免一直失败一直试
        logger.exception("推送到飞书失败")
        for item in shown:
            failures = int((item.facets or {}).get("push_failures") or 0) + 1
            if failures > PUSH_RETRIES:
                continue
            pushed_at, importance, state = before[item.id]
            item.announced_at, item.pushed_at, item.pushed_importance = None, pushed_at, importance
            item.facets = {**(item.facets or {}), "push_failures": failures, "pushed_state": state}
    await session.commit()


async def context_line(session: AsyncSession, item: FollowUp, timezone: str) -> str:
    """对话里给模型看的一行：不只是标题，还有最近一次往来——谁什么时候说了什么、他回了没有。"""
    tz = ZoneInfo(timezone)
    parts = [f"#{item.id} [{'等他' if item.owner == 'me' else '等别人'}] {item.title}"]
    last = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
    if last is not None and last.kind == "mail":
        who = last.payload.get("from_name") or last.payload.get("from") or "对方"
        when = (last.occurred_at or item.created_at).astimezone(tz)
        parts.append(f"{who} {when:%m-%d %H:%M} 来信：{(last.summary or last.title)[:80]}")
        thread = last.payload.get("thread_id")
        if thread:
            mine = (await session.execute(
                select(Signal).where(Signal.user_id == item.user_id, Signal.kind == "mail_sent",
                                     Signal.payload["thread_id"].astext == thread, Signal.occurred_at > last.occurred_at)
                .order_by(Signal.occurred_at.desc()).limit(1)
            )).scalars().first()
            if mine is not None:
                parts.append(f"你 {mine.occurred_at.astimezone(tz):%m-%d %H:%M} 已回复：{(mine.body or '')[:80]}")
    elif item.summary:
        parts.append(item.summary[:100])
    if item.action_id:
        parts.append(f"待确认操作 #{item.action_id}")
    if item.attention == "mute" or (item.announced_at is None and item.attention in ("batch", "brief")):
        when = {"batch": "攒到下次汇总再说", "brief": "留到早上简报", "mute": "不提醒，只在看板跟踪"}[item.attention]
        parts.append(f"还没告诉他：{when}" + (f"（{item.attention_note}）" if item.attention_note else ""))
    return "；".join(parts)


async def item_json(session: AsyncSession, item: FollowUp) -> dict:
    action = await session.get(PendingAction, item.action_id) if item.action_id else None
    last = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
    return {
        "id": item.id, "kind": item.kind, "owner": item.owner, "title": item.title, "summary": item.summary,
        "next_step": item.next_step, "recommendation": item.recommendation, "waiting_on": item.waiting_on,
        "url": item.url, "open_url": insights.open_link(item), "importance": item.importance, "status": item.status, "resolution": item.resolution,
        "due_at": cards.iso(item.due_at), "remind_at": cards.iso(item.remind_at),
        "updated_at": cards.iso(item.updated_at), "count": len(item.signal_ids),
        "attention": item.attention, "attention_note": item.attention_note, "announced": item.announced_at is not None,
        # 能不能按“这一类”设规则（审批按类型、邮件按发件人、群里的按群）
        "quieter": item.owner == "me" and item.attention not in ("brief", "mute") and attention.quieter_match(item, last) is not None,
        "action": actions_json(action) if action else None,
        "ask": ask(item, action),
        "ask_ui": cards.ask_ui(item, action),
        "source": cards.signal_card(last) if last else None,
        "detail": ((last.payload.get("detail") or {}).get("fields") or []) if last and item.kind == "approval" else [],
        # 可以在 Relay 里直接批准/驳回（不需要审批人补填内容）
        "quick_approve": bool(last and item.kind == "approval" and not approval_source.needs_input(last.payload.get("detail"))),
        # 邮件：这封信的上下文（线程里之前的往来、附件、正文里的文档、相关会议）和它的编号（转发用）
        "context": (item.facets or {}).get("context"),
        "mail_id": last.id if last and last.kind == "mail" else None,
        "is_mail": item.key.startswith(("mail-thread:", "batch:")),
        "evidence": (item.facets or {}).get("evidence") or [],
        # 和同事的协作：在协作里接受、提交、验收（“完成”按钮不能代替）
        "collab": {k: (item.facets or {}).get(k) for k in ("delegation_id", "role", "collab_status", "counterpart")}
        if item.kind == "collab" else None,
    }


def actions_json(action: PendingAction) -> dict:
    p = action.payload
    return {
        "id": action.id, "kind": action.kind, "summary": action.summary, "status": action.status,
        "result": action.result, "to": p.get("to"), "subject": p.get("subject"),
        "body": p.get("body"), "rsvp": p.get("status"), "references": p.get("references"),
        "start": p.get("start"), "end": p.get("end"), "due": p.get("due"),
        "reply_all": p.get("reply_all", False),
        "others": [o.get("name") or o.get("mail_address") for o in p.get("others") or []],
        # 回复全部时原收件人仍是收件人、原抄送仍是抄送；以及为什么这样选
        "to_extra": [o.get("name") or o.get("mail_address") for o in p.get("to_extra") or []],
        "cc": [o.get("name") or o.get("mail_address") for o in p.get("cc") or []] if isinstance(p.get("cc"), list) else [],
        "reply_all_why": p.get("reply_all_why"),
        "attachments": p.get("attachments") if action.kind == "forward_mail" else None,
        "link": (p.get("task") or {}).get("url") or (p.get("event") or {}).get("app_link"),
        "mission_id": action.mission_id,
        "auto": action.auto, "undone_at": action.undone_at.isoformat() if action.undone_at else None,
        "undoable": automation.undoable(action),
        # 定时任务里准备、还在等确认：卡片上可以“确认，以后直接办”
        "grantable": bool(action.scheduled_task_id) and action.status == "pending",
        "shown": p.get("shown") if action.kind == "base_record" else None,
        "cells": p.get("cells") if p.get("operation") == "fill_sheet_cells" or action.kind == "local_edit" else None,
        "notes": p.get("notes") if p.get("operation") == "fill_sheet_cells" or action.kind == "local_edit" else None,
    }
