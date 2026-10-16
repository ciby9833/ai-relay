"""主动引擎：同步数据源 → 判断 → 推送 / 简报。由 worker 周期性调用。"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.feishu.client import FeishuClient, FeishuError, needs_reauth
from app.home import ConversationBusy, post
from app.llm.base import LLMError
from app.memory import service as memory_service
from app.models import FollowUp, Signal, SourceState, User
from app.proactive import cards, items
from app.proactive.llm import complete_structured, complete_text
from app.proactive.push import push
from app.proactive.prompts import BRIEF_SYSTEM, TEAM_DIGEST_SYSTEM, TRIAGE_SYSTEM
from app import i18n
from app.sources import approval as approval_source
from app.i18n import user_language
from app.proactive.settings import language_of, in_quiet_hours, get_settings_row, is_workday, merged
from app.sources import SYNCERS, calendar, docs

logger = logging.getLogger("relay.proactive")

MENTION_WAIT = timedelta(hours=2)
WEEKDAYS = "一二三四五六日"

TRIAGE_TOOL = {
    "name": "classify_mail",
    "description": "给出这封邮件对用户的重要程度判断",
    "input_schema": {
        "type": "object",
        "properties": {
            "importance": {"type": "string", "enum": ["urgent", "normal", "low"]},
            "notify_now": {"type": "boolean"},
            "needs_reply": {"type": "boolean"},
            "action_type": {"type": "string", "enum": ["reply", "review", "fyi"]},
            "due": {"type": "string", "enum": ["today", "this_week", "none"]},
            "summary": {"type": "string"},
            "reason": {"type": "string", "description": "一句话说明为什么这样判断"},
        },
        "required": ["importance", "notify_now", "needs_reply", "action_type", "due", "summary", "reason"],
        "additionalProperties": False,
    },
}


async def _state(session: AsyncSession, user: User, source: str) -> SourceState:
    state = await session.get(SourceState, (user.id, source))
    if state is None:
        state = SourceState(user_id=user.id, source=source, cursor={})
        session.add(state)
        await session.flush()
    return state


async def _alert_reauth(session: AsyncSession, feishu: FeishuClient, user: User, reason: str | None = None) -> None:
    """用户授权失效或缺新权限时提醒他重新登录，24 小时内最多一次。"""
    state = await _state(session, user, "auth")
    last = state.cursor.get("alerted_at")
    if last and datetime.fromisoformat(last) > datetime.now(UTC) - timedelta(hours=24):
        return
    try:
        await feishu.send_text(
            user.feishu_open_id,
            (reason or "Relay 读取你的日历和邮件需要重新授权")
            + f"，请打开 {get_settings().frontend_url} 用飞书登录一次（授权页里同意即可）。",
        )
    except FeishuError:
        logger.warning("发送重新登录提醒失败: %s", user.name)
        return
    state.cursor = {**state.cursor, "alerted_at": datetime.now(UTC).isoformat()}


async def sync_sources(session: AsyncSession, feishu: FeishuClient, user: User, settings: dict, force: bool = False) -> None:
    now = datetime.now(UTC)
    reauth = False
    for source, (sync, interval) in SYNCERS.items():
        if not settings["sources"].get(source):
            continue
        state = await _state(session, user, source)
        if not force and state.last_synced_at and state.last_synced_at > now - timedelta(seconds=interval):
            continue
        try:
            async with session.begin_nested():
                created = await sync(session, feishu, user, state)
            state.last_error = None
            if created:
                logger.info("%s 的 %s 新增 %s 条", user.name, source, created)
        except FeishuError as exc:
            state.last_error = str(exc)[:500]
            # 授权过期，或 token 缺少用户身份权限（报错里写着 "under the user identity"）：都要重新登录
            reauth |= needs_reauth(exc)
            logger.warning("%s 同步 %s 失败: %s", user.name, source, exc)
        state.last_synced_at = now
        await session.commit()
    if reauth:
        await _alert_reauth(session, feishu, user)
        await session.commit()
    elif user.feishu_refresh_token_enc or user.feishu_access_token_enc:
        granted = set(await feishu.granted_user_scopes())
        missing = granted - set((user.feishu_scopes or "").split())
        if missing:
            examples = "、".join(sorted(missing)[:3])
            await _alert_reauth(session, feishu, user, f"Relay 新增了 {len(missing)} 项能力需要你授权（例如 {examples}）")
            await session.commit()


async def _profile(session: AsyncSession, user: User) -> str:
    memories = await memory_service.list_memories(session, user.id, "profile", 30)
    return "\n".join(f"- {m.content}" for m in reversed(memories)) or "（暂无）"


async def triage(session: AsyncSession, user: User) -> None:
    # 新邮件；以及第一次同步时进来、还没分过级的存量邮件（分级后只静默建档，不打扰）
    result = await session.execute(
        select(Signal).where(
            Signal.user_id == user.id, Signal.kind == "mail",
            or_(Signal.status == "new", and_(Signal.status == "digest", Signal.importance.is_(None))),
        ).order_by(Signal.id).limit(20)
    )
    signals = list(result.scalars())
    if not signals:
        return
    profile = await _profile(session, user)
    lang = await language_of(session, user)
    for signal in signals:
        mail = signal.payload
        prompt = (
            f"用户：{user.name}\n关于用户：\n{profile}\n\n"
            f"<mail>\n发件人：{mail.get('from')}\n收件人：{'、'.join(mail.get('to') or [])}\n"
            f"抄送：{'、'.join(mail.get('cc') or [])}\n主题：{signal.title}\n\n{(signal.body or '')[:6000]}\n</mail>"
        )
        try:
            decision = await complete_structured(TRIAGE_SYSTEM, prompt + "\n\nsummary " + i18n.instruction(lang), TRIAGE_TOOL)
        except Exception:
            logger.exception("邮件分级失败 #%s", signal.id)
            signal.status = "digest"
            continue
        signal.importance = decision["importance"]
        signal.needs_reply = decision["needs_reply"] or decision["action_type"] == "reply"
        signal.payload = {**signal.payload, "action_type": decision["action_type"], "due": decision["due"]}
        signal.summary = decision["summary"]
        signal.reason = decision["reason"]
        if signal.status == "digest":
            continue  # 存量邮件：保持静默
        if decision["importance"] == "low" or decision["action_type"] == "fyi":
            signal.status = "ignored"
        else:
            # 需要他处理的都实时建成跟进事项并告诉他
            signal.status = "notify"
    await session.commit()


async def watch_mentions(session: AsyncSession, user: User) -> None:
    """群里@了他、两小时还没在那个群里说话的，提醒一次。"""
    result = await session.execute(
        select(Signal).where(
            Signal.user_id == user.id, Signal.kind == "mention", Signal.status == "watching",
            Signal.occurred_at < datetime.now(UTC) - MENTION_WAIT,
        )
    )
    for signal in result.scalars():
        signal.status, signal.importance = "notify", "normal"
    await session.commit()


def _local(moment: datetime, user: User) -> str:
    return moment.astimezone(ZoneInfo(user.timezone)).strftime("%H:%M")


async def meeting_briefs(session: AsyncSession, feishu: FeishuClient, user: User, settings: dict) -> None:
    now = datetime.now(UTC)
    lead = timedelta(minutes=settings["meeting_brief_minutes"])
    result = await session.execute(
        select(Signal).where(
            Signal.user_id == user.id, Signal.kind == "meeting", Signal.status == "scheduled",
            Signal.occurred_at > now, Signal.occurred_at <= now + lead,
        )
    )
    for meeting in result.scalars():
        payload = meeting.payload
        meeting.status = "notified"
        if payload.get("all_day") or payload.get("rsvp") == "decline":
            continue
        attendees = payload.get("attendees") or [
            a["name"] for a in await calendar.attendees_for(feishu, user, payload) if a["open_id"] != user.feishu_open_id
        ]
        mails = (await session.execute(
            select(Signal).where(
                Signal.user_id == user.id, Signal.source == "mail",
                Signal.occurred_at > now - timedelta(days=14),
                or_(
                    Signal.title.ilike(f"%{meeting.title[:20]}%"),
                    *[Signal.payload["from_name"].astext == name for name in attendees],
                ),
            ).order_by(Signal.occurred_at.desc()).limit(5)
        )).scalars().all()
        try:
            related_docs = await docs.search(feishu, user, meeting.title, limit=3)
        except FeishuError:
            related_docs = []
        material = (
            f"会议：{meeting.title}\n时间：{_local(meeting.occurred_at, user)}\n"
            f"组织者：{payload.get('organizer')}\n参会人：{'、'.join(attendees)}\n地点：{payload.get('location') or '-'}\n"
            f"议程/描述：{payload.get('description') or '-'}\n\n"
            "相关邮件：\n" + ("\n".join(f"- {m.payload.get('from')}《{m.title}》：{m.summary or (m.body or '')[:200]}" for m in mails) or "无") +
            "\n\n相关文档：\n" + ("\n".join(f"- {d['title']}：{d['summary']}" for d in related_docs) or "无")
        )
        try:
            text = await complete_text(BRIEF_SYSTEM, f"写一份会前准备（这个会 {_local(meeting.occurred_at, user)} 开始）。{i18n.instruction(user_language(settings))}\n\n{material}")
        except LLMError:
            text = material
        message_cards = [cards.event_card(meeting)] + [cards.mail_card(m) for m in mails[:3]]
        try:
            await post(session, user, event=f"会议《{meeting.title}》即将开始，给用户发会前准备", text=text, cards=message_cards)
        except ConversationBusy:
            await session.rollback()
            return
        meeting.status, meeting.notified_at = "notified", now
        await session.commit()
        try:
            await push(session, feishu, user, f"🗓 {_local(meeting.occurred_at, user)} {meeting.title}", text, message_cards[:1])
        except FeishuError:
            logger.exception("会前准备推送失败")
        await session.commit()


async def morning_brief(session: AsyncSession, feishu: FeishuClient, user: User, settings: dict, force: bool = False) -> bool:
    """给管理者的简报：要拍板的、要回复的、今天的日程、风险、在等别人的、团队动态。

    先给一段汇总，每件事附明细和操作（网页里是卡片，飞书里是可折叠面板）。
    """
    row = await get_settings_row(session, user)
    tz = ZoneInfo(user.timezone)
    local_now = datetime.now(tz)
    today = local_now.strftime("%Y-%m-%d")
    if not force:
        hour, minute = map(int, settings["brief_time"].split(":"))
        if row.last_brief_date == today or not is_workday(user.timezone) or (local_now.hour, local_now.minute) < (hour, minute):
            return False
    now = datetime.now(UTC)
    day_end = local_now.replace(hour=23, minute=59, second=59).astimezone(UTC)

    open_items = (await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == "open")
        .order_by(FollowUp.importance.desc(), FollowUp.due_at.asc().nulls_last(), FollowUp.id)
    )).scalars().all()
    decide = [i for i in open_items if i.owner == "me" and i.kind in ("approval", "invitation")]
    handle = [i for i in open_items if i.owner == "me" and i not in decide]
    waiting = [i for i in open_items if i.owner == "others"]
    risks = [
        i for i in open_items
        if (i.due_at and i.due_at < now) or (i.kind == "approval" and i.created_at < now - timedelta(days=2))
    ]
    meetings = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind == "meeting", Signal.status != "ignored",
                             Signal.occurred_at.between(now - timedelta(minutes=30), day_end))
        .order_by(Signal.occurred_at)
    )).scalars().all()
    team_digest = await _team_digest(session, user)

    def ids(group):
        return [{"kind": "item", "item_id": i.id} for i in group[:8]]

    risk_notes = [
        {"kind": "note", "text": f"⚠️ {i.title}：" + ("已过截止时间" if i.due_at and i.due_at < now else f"已经等了 {(now - i.created_at).days} 天")}
        for i in risks[:5]
    ]
    sections = [
        ["要你拍板", ids(decide)],
        ["要你回复 / 处理", ids(handle)],
        ["今天的日程", [cards.event_card(m) for m in meetings[:8]]],
        ["风险与逾期", risk_notes],
        ["在等别人", ids(waiting)],
        ["团队动态", [{"kind": "note", "text": team_digest}] if team_digest else []],
    ]
    material = (
        f"今天是 {today} 周{WEEKDAYS[local_now.weekday()]}，用户：{user.name}\n"
        f"要他拍板 {len(decide)} 件：" + "；".join(items.describe(i) for i in decide[:6]) + "\n"
        f"要他处理的事和具体要做什么：" + "；".join(f"{i.title}→{items.ask(i, None)}" for i in handle[:6]) + "\n"
        f"要他回复/处理 {len(handle)} 件：" + "；".join(i.title for i in handle[:6]) + "\n"
        f"今天还有 {len(meetings)} 个会：" + "；".join(f"{_local(m.occurred_at, user)} {m.title}" for m in meetings[:6]) + "\n"
        f"风险/逾期 {len(risks)} 件：" + "；".join(i.title for i in risks[:5]) + "\n"
        f"在等别人 {len(waiting)} 件\n团队动态：{team_digest or '无'}"
    )
    try:
        text = await complete_text(BRIEF_SYSTEM, material + "\n\n" + i18n.instruction(user_language(settings)))
    except LLMError:
        text = f"要你拍板 {len(decide)} 件，要你处理 {len(handle)} 件，今天还有 {len(meetings)} 个会。"

    message_cards = ids(decide) + ids(handle) + [cards.event_card(m) for m in meetings[:4]]
    note = f"\n\n**团队动态**\n{team_digest}" if team_digest else ""
    try:
        await post(session, user, event="用户要一份简报", text=text + note, cards=message_cards)
    except ConversationBusy:
        await session.rollback()
        return False
    row.last_brief_date = today
    await session.commit()
    title = f"Relay 简报｜拍板 {len(decide)} · 处理 {len(handle)} · 会议 {len(meetings)}"
    try:
        await push(session, feishu, user, title, text, sections=sections)
    except FeishuError:
        logger.exception("简报推送失败")
    await session.commit()
    return True


async def _team_digest(session: AsyncSession, user: User) -> str | None:
    """被判为“知会即可”的通知类邮件（需求进度、系统通知……）：不打扰，但在简报里归纳成几句团队动态。"""
    notices = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind.in_(["mail", "biz_event", "approval_update"]), Signal.status == "ignored",
                             Signal.occurred_at > datetime.now(UTC) - timedelta(days=1))
        .order_by(Signal.occurred_at.desc()).limit(40)
    )).scalars().all()
    # 人事类审批（请假、离职、补卡、薪酬补贴……）不进简报
    notices = [n for n in notices if not (n.kind == "approval_update" and approval_source.is_personal(n.payload or {}))]
    if not notices:
        return None
    material = "\n".join(
        f"- [抄送给他的审批] {n.title}" if n.kind == "approval_update"
        else f"- [{n.payload.get('integration')}] {n.title}" if n.kind == "biz_event"
        else f"- {n.payload.get('from_name') or n.payload.get('from')}《{n.title}》{n.summary or ''}"
        for n in notices
    )
    try:
        return await complete_text(TEAM_DIGEST_SYSTEM, f"<mails>\n{material}\n</mails>\n\n" + i18n.instruction(await language_of(session, user)))
    except LLMError:
        return None


async def run_for_user(session: AsyncSession, feishu: FeishuClient, user: User) -> None:
    settings = merged((await get_settings_row(session, user)).data)
    await session.commit()
    if not settings["proactive"]:
        return
    await sync_sources(session, feishu, user, settings)
    await triage(session, user)
    await watch_mentions(session, user)
    await items.track(session, feishu, user)
    await items.refresh_approvals(session, user)
    await items.advance(session, user)
    reminders = await items.due_reminders(session, feishu, user)
    # 免打扰时段先不取，留到结束后再告诉他
    results = [] if in_quiet_hours(settings, user.timezone) else await items.result_facts(session, user)
    await items.announce(session, feishu, user, settings, [fact for _, fact in reminders] + results)
    await meeting_briefs(session, feishu, user, settings)
    if settings["brief_enabled"]:
        await morning_brief(session, feishu, user, settings)
