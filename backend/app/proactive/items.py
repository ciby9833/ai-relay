"""跟进事项：把信号归并成“事”，推进状态，到点提醒，并在主线里告诉用户。

一件事的生命周期（以回邮件为例）：
    新邮件 → 等你回复（Relay 先起草好）→ 你确认发送 → 等对方回复（3 天没回就提醒，并起草跟进邮件）
    → 对方回了 → 又变成等你回复 ……
所有对外的操作都只准备、不执行，由用户确认。
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
from app.home import ConversationBusy, post
from app.llm.base import LLMError
from app.models import FollowUp, PendingAction, Signal, User
from app.proactive import actions, cards
from app.proactive.llm import complete_text
from app.proactive.prompts import APPROVAL_SUMMARY_SYSTEM, FOLLOWUP_SYSTEM, NARRATE_SYSTEM
from app.proactive.push import push
from app.sources import approval as approval_source
from app import i18n
from app.proactive.settings import in_quiet_hours, language_of

logger = logging.getLogger("relay.items")

APPROVAL_REMIND = timedelta(days=2)
WAITING_REMIND = timedelta(days=3)
MAX_NUDGES = 2
OPEN = "open"


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
    for name, value in fields.items():
        setattr(item, name, value)
    if signal is not None and signal.id not in item.signal_ids:
        item.signal_ids = item.signal_ids + [signal.id]
    if item.status != OPEN:
        item.status, item.closed_at, item.resolution = OPEN, None, None
    item.updated_at = now
    item.announced_at = now if silent else None
    return item


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
            next_step="看一下 Relay 起草的回复，确认后发送" if fresh else "回复这封邮件",
            recommendation=("对方回复了你之前的邮件。" if resumed else "") + (signal.reason or ""),
            due_at=_due(mail.get("due"), user),
        )
        if fresh:
            try:
                action = await actions.prepare_mail_reply(session, feishu, user, signal.id)
                item.action_id = action.id
            except (actions.ActionError, LLMError):
                logger.exception("自动起草失败 #%s", signal.id)
                item.next_step = "回复这封邮件（自动起草失败，可以让 Relay 重试）"
    elif action_type == "review":
        day = local_day(signal.occurred_at or datetime.now(UTC), user)
        key = f"batch:{mail.get('from_address')}:{day}"
        item = await get_item(session, user, key)
        count = len(item.signal_ids) + 1 if item else 1
        subjects = await _subjects(session, (item.signal_ids if item else []) + [signal.id])
        await upsert(
            session, user, key, signal, silent=not fresh,
            kind="review", owner="me",
            title=f"{sender} 发来 {count} 封邮件需要你看" if count > 1 else f"看一下 {sender} 的《{signal.title}》",
            summary="；".join(subjects[:8]) + ("……" if len(subjects) > 8 else ""),
            next_step="审阅后回复对方" , recommendation=signal.reason,
            importance="urgent" if signal.importance == "urgent" else "normal",
            due_at=_due(mail.get("due"), user),
        )
    signal.status = "tracked"


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
    return [f"{s.title}" for s in signals]


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
    elif signal.kind == "mention":
        await upsert(
            session, user, f"mention:{signal.external_id}", signal, silent=not fresh,
            kind="mention", owner="me", title=f"{signal.payload.get('chat_name') or '群聊'}里@你的消息还没回",
            summary=signal.body, next_step="在群里回复", url=signal.url,
        )
    signal.status = "tracked"


def approval_next_step(signal: Signal) -> str:
    """需要审批人补填/分配的单子只能去飞书原生审批处理；拿不到明细时也保守处理。"""
    detail = signal.payload.get("detail")
    if approval_source.needs_input(detail):
        hint = (detail or {}).get("input_hint")
        return "去飞书审批" + (f"（需要填写：{hint}）" if hint else "")
    return "批准或驳回"


async def summarize_approval(signal: Signal, lang: str = "zh") -> str | None:
    """一句话说清这张单子要批什么；没有明细时退回到发起人信息。"""
    detail = signal.payload.get("detail")
    if not detail or not detail.get("fields"):
        return signal.body
    fields = "\n".join(f"{f['name']}：{f['value']}" for f in detail["fields"])
    try:
        return await complete_text(
            APPROVAL_SUMMARY_SYSTEM,
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
        if (item.summary or "").startswith("发起人：") and (signal.payload.get("detail") or {}).get("fields"):
            item.summary = await summarize_approval(signal, await language_of(session, user))
    await session.commit()


async def track(session: AsyncSession, feishu: FeishuClient, user: User) -> None:
    """把判断完的信号归并成事项。fresh（刚到的）会通知用户，存量的只静默建档。"""
    result = await session.execute(
        select(Signal).where(
            Signal.user_id == user.id,
            Signal.status.in_(["notify", "digest", "notified", "digested"]),
            Signal.kind.in_(["mail", "invitation", "approval_pending", "approval_update", "attendance_missing", "mention", "biz_event"]),
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
                    else:
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
                                        Signal.occurred_at > (last.occurred_at or item.created_at)).limit(1)
            ))
            if replied_elsewhere and action and action.status == "pending":
                actions.cancel(action)  # Relay 起草的那版用不上了
        if item.kind == "reply" and ((action and action.status == "done") or replied_elsewhere):
            # 回复已发出：转为等对方回复
            item.kind, item.owner = "waiting", "others"
            item.waiting_on = (last.payload.get("from_name") or last.payload.get("from_address")) if last else None
            item.title = f"等 {item.waiting_on or '对方'} 回复"
            item.next_step = "Relay 盯着对方的回复，3 天没回会提醒你"
            item.recommendation, item.action_id = None, None
            item.remind_at, item.nudges = datetime.now(UTC) + WAITING_REMIND, 0
            item.updated_at = datetime.now(UTC)
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
        elif item.kind == "mention" and last and last.status == "done":
            close(item, "done", "你已经在群里回复了")
        elif item.kind == "attendance" and item.created_at < datetime.now(UTC) - timedelta(hours=12):
            close(item, "dismissed", "已过期")
    await session.commit()


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
                    body = await complete_text(
                        FOLLOWUP_SYSTEM,
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


async def announce(
    session: AsyncSession, feishu: FeishuClient, user: User, settings: dict, extra_facts: list[str]
) -> None:
    """把新出现、需要用户知道的事用一条消息告诉他（实时，遵守免打扰）。"""
    result = await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == OPEN, FollowUp.announced_at.is_(None))
        .order_by(FollowUp.id)
    )
    items = list(result.scalars())
    if not items and not extra_facts:
        await session.commit()
        return
    if in_quiet_hours(settings, user.timezone) and not any(i.importance == "urgent" for i in items):
        await session.commit()  # 免打扰时段：留到结束后再说
        return
    described = [describe(i, await session.get(PendingAction, i.action_id) if i.action_id else None) for i in items]
    facts = extra_facts + described
    try:
        text = await complete_text(NARRATE_SYSTEM, f"用户：{user.name}\n\n发生的事：\n" + "\n".join(f"- {f}" for f in facts)
                                   + "\n\n" + i18n.instruction(i18n.user_language(settings)))
    except LLMError:
        text = "\n".join(f"- {f}" for f in facts)
    message_cards = [{"kind": "item", "item_id": i.id} for i in items[:8]]
    try:
        await post(session, user, event="Relay 告诉用户：\n" + "\n".join(facts), text=text, cards=message_cards)
    except ConversationBusy:
        await session.rollback()
        return
    now = datetime.now(UTC)
    for item in items:
        item.announced_at = now
    await session.commit()
    try:
        lang = i18n.user_language(settings)
        title = i18n.t(lang, "things_to_know", n=len(items)) if items else i18n.t(lang, "update")
        await push(session, feishu, user, title, text, message_cards)
    except FeishuError:
        logger.exception("推送到飞书失败")
    await session.commit()


async def item_json(session: AsyncSession, item: FollowUp) -> dict:
    action = await session.get(PendingAction, item.action_id) if item.action_id else None
    last = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
    return {
        "id": item.id, "kind": item.kind, "owner": item.owner, "title": item.title, "summary": item.summary,
        "next_step": item.next_step, "recommendation": item.recommendation, "waiting_on": item.waiting_on,
        "url": item.url, "importance": item.importance, "status": item.status, "resolution": item.resolution,
        "due_at": cards.iso(item.due_at), "remind_at": cards.iso(item.remind_at),
        "updated_at": cards.iso(item.updated_at), "count": len(item.signal_ids),
        "action": actions_json(action) if action else None,
        "ask": ask(item, action),
        "source": cards.signal_card(last) if last else None,
        "detail": ((last.payload.get("detail") or {}).get("fields") or []) if last and item.kind == "approval" else [],
        # 可以在 Relay 里直接批准/驳回（不需要审批人补填内容）
        "quick_approve": bool(last and item.kind == "approval" and not approval_source.needs_input(last.payload.get("detail"))),
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
        "link": (p.get("task") or {}).get("url") or (p.get("event") or {}).get("app_link"),
        "mission_id": action.mission_id,
        "cells": p.get("cells") if p.get("operation") == "fill_sheet_cells" else None,
        "notes": p.get("notes") if p.get("operation") == "fill_sheet_cells" else None,
    }
