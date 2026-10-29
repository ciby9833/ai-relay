"""主动引擎：同步数据源 → 判断 → 推送 / 简报。由 worker 周期性调用。"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.feishu.client import FeishuClient, FeishuError, needs_reauth
from app.home import ConversationBusy, post
from app.llm.base import LLMError
from app.memory import service as memory_service
from app.models import FollowUp, Signal, SourceState, User
from app.feishu.cards import esc
from app.proactive import attention, cards, items, meetings
from app.proactive.llm import complete_structured, complete_text
from app.proactive.push import push
from app.proactive.prompts import BRIEF_SYSTEM, TEAM_DIGEST_SYSTEM, TRIAGE_SYSTEM
from app import i18n
from app.sources import approval as approval_source
from app.i18n import user_language
from app.proactive.settings import language_of, get_settings_row, is_workday, merged
from app.sources import REQUIRED_SCOPES, SYNCERS
from app.sources import unavailable as source_unavailable

logger = logging.getLogger("relay.proactive")

MENTION_WAIT = timedelta(hours=2)
UNAVAILABLE_RETRY = timedelta(days=1)
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
            "ask": {"type": "string", "description": "reply / review 时必填：邮件里对他（或包括他的一群人）的具体要求（回复什么、确认什么、看什么）"},
            "why_me": {"type": "string", "description": "为什么和他有关：谁点名要他、他负责的哪件事、他是审批/决策人……写具体依据；从邮件和往来里看不出来就留空"},
            "responsible": {"type": "string", "enum": ["me", "unclear"], "description": "责任是不是明确在他：me 明确是他；unclear 有要求但看不出是不是归他"},
            "when": {"type": "string", "description": "邮件里写了时间才填（原样，例如“周五前”）；没写就留空，不要猜"},
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
        cursor = state.cursor or {}
        if cursor.get("unavailable_until") and datetime.fromisoformat(cursor["unavailable_until"]) > now:
            continue  # 他没有开通这项服务（例如没有邮箱）：先跳过，到时间再试一次
        needed = REQUIRED_SCOPES.get(source)
        if needed and not set(needed) & set((user.feishu_scopes or "").split()):
            # 没授权这一项：设置页里说明，不当作故障、不反复提醒重新登录（应用开通后会按“新增能力”提醒一次）
            state.last_error = f"需要重新登录一次，授权 Relay 读取这一项（{' 或 '.join(needed)}）"
            state.last_synced_at = now
            await session.commit()
            continue
        try:
            async with session.begin_nested():
                created = await sync(session, feishu, user, state)
            state.last_error = None
            if cursor.get("unavailable_until"):
                state.cursor = {k: v for k, v in (state.cursor or {}).items() if k != "unavailable_until"}
                logger.info("%s 的 %s 已恢复", user.name, source)
            if created:
                logger.info("%s 的 %s 新增 %s 条", user.name, source, created)
        except FeishuError as exc:
            if source_unavailable(source, exc):
                # 例如没有开通飞书邮箱：不算故障、不提醒重新登录，一天后自动再检测
                state.cursor = {**cursor, "unavailable_until": (now + UNAVAILABLE_RETRY).isoformat()}
                state.last_error = f"没有开通这项服务，{UNAVAILABLE_RETRY.days} 天后自动再检测：{exc}"[:500]
                state.last_synced_at = now
                await session.commit()
                continue
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
    own = {user.email} if user.email else set()  # 不额外调接口：同步邮件时已经知道他的地址
    for signal in signals:
        mail = signal.payload
        mine = {a.lower() for a in own}
        position = ("收件人" if any((a.get("mail_address") or "").lower() in mine for a in mail.get("to_addresses") or [])
                    else "只在抄送里" if any((a.get("mail_address") or "").lower() in mine for a in mail.get("cc_addresses") or [])
                    else "不在收件人和抄送里（群发 / 邮件组）")
        from app.proactive import casefile

        earlier = await casefile.thread_history(session, user, signal, limit=3)
        prompt = (
            f"用户：{user.name}（{'、'.join(sorted(own)) or '邮箱未知'}）。这封信里他是：{position}。\n关于用户：\n{profile}\n\n"
            + (f"<thread>\n同一线程里之前的往来（判断这件事是不是归他）：\n" + "\n".join(earlier) + "\n</thread>\n\n" if earlier else "")
            + f"<mail>\n发件人：{mail.get('from')}\n收件人：{'、'.join(mail.get('to') or [])}\n"
            f"抄送：{'、'.join(mail.get('cc') or [])}\n主题：{signal.title}\n\n{(signal.body or '')[:6000]}\n</mail>"
        )
        try:
            decision = await complete_structured(TRIAGE_SYSTEM, prompt + "\n\nsummary " + i18n.instruction(lang), TRIAGE_TOOL)
        except Exception:
            logger.exception("邮件分级失败 #%s", signal.id)
            signal.status = "digest"
            continue
        # 有明确的行动要求才进待处理；没写时间不是不用处理（时间标“未约定”），看不出是不是归他也不是不用处理（先请他确认）
        if decision["action_type"] in ("reply", "review") and not (decision.get("ask") or "").strip():
            decision["action_type"], decision["needs_reply"] = "fyi", False
        signal.importance = decision["importance"]
        signal.needs_reply = decision["needs_reply"] or decision["action_type"] == "reply"
        signal.payload = {**signal.payload, "action_type": decision["action_type"], "due": decision["due"],
                          "why_me": decision.get("why_me"), "ask": decision.get("ask"), "when": (decision.get("when") or "").strip() or None,
                          "responsible": decision.get("responsible") or ("me" if decision.get("why_me") else "unclear")}
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
    """会前准备（见 meetings）：只用确实相关的材料；有值得看的才推送，其余只放在“会议”页面。"""
    now = datetime.now(UTC)
    lead = timedelta(minutes=settings["meeting_brief_minutes"])
    result = await session.execute(
        select(Signal).where(
            Signal.user_id == user.id, Signal.kind == "meeting", Signal.status == "scheduled",
            Signal.occurred_at > now, Signal.occurred_at <= now + lead,
        )
    )
    lang = user_language(settings)
    handled = list((await session.execute(select(Signal).where(
        Signal.user_id == user.id, Signal.kind == "meeting", Signal.status == "notified",
        Signal.occurred_at > now - timedelta(hours=2)))).scalars())
    for meeting in result.scalars():
        payload = meeting.payload or {}
        meeting.status, meeting.notified_at = "notified", now
        if any(meetings.same_meeting(meeting, m) for m in handled):
            continue  # 同一个会的另一条日历记录已经准备过了
        handled.append(meeting)
        if payload.get("all_day") or payload.get("rsvp") == "decline":
            continue
        prep = await meetings.prepare(session, feishu, user, meeting, lang)
        await session.commit()
        if not prep["worth_pushing"]:
            continue  # 没找到值得看的材料：飞书日历自己会提醒开会，Relay 不再多说一遍
        try:
            await push(session, feishu, user, f"🗓 {_local(meeting.occurred_at, user)} {meeting.title}", prep["text"],
                       [cards.event_card(meeting)])
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
    unannounced = [i for i in open_items if i.announced_at is None]
    open_items = [i for i in open_items if i.attention != "mute"]  # 他说过不用提醒的，简报里也不提
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
        {"kind": "note", "text": f"⚠️ {esc(i.title)}：" + ("已过截止时间" if i.due_at and i.due_at < now else f"已经等了 {(now - i.created_at).days} 天")}
        for i in risks[:5]
    ]
    sections = [
        ["要你拍板", ids(decide)],
        ["要你回复 / 处理", ids(handle)],
        ["今天的日程", [cards.event_card(m) for m in meetings[:8]]],
        ["风险与逾期", risk_notes],
        ["在等别人", ids(waiting)],
        ["团队动态", [{"kind": "note", "text": team_digest}] if team_digest else []],
        # 从他以前的偏好整理出的候选规则：他点“启用”才生效
        ["要你确认的提醒偏好", [{"kind": "rule", "rule_id": r.id} for r in await attention.proposals_to_show(session, user)]],
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
        await post(session, user, event="用户要一份简报", text=text + note, cards=message_cards, notice="brief")
    except ConversationBusy:
        await session.rollback()
        return False
    row.last_brief_date = today
    for item in unannounced:
        item.announced_at = now  # 攒着的、只放简报的事：简报里说过了，不再单独说
    await attention.note_digest(session, user, now)
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
    if await attention.propose_from_memories(session, user):
        logger.info("%s：从以前的偏好整理出候选提醒规则，等他确认", user.name)
    await session.commit()
    await triage(session, user)
    await watch_mentions(session, user)
    await items.track(session, feishu, user)
    await items.refresh_approvals(session, user)
    await items.advance(session, user)
    reminders = await items.due_reminders(session, feishu, user)
    await items.announce(session, feishu, user, settings, reminders)
    try:
        await items.sync_cards(session, feishu, user)  # 卡片跟着事项状态走，不另发
    except Exception:  # noqa: BLE001 - 同步卡片失败不影响别的
        logger.exception("同步卡片状态失败")
    await meeting_briefs(session, feishu, user, settings)
    try:
        await meetings.collect_minutes(session, feishu, user)
    except FeishuError:
        logger.exception("找会议纪要失败")
    if settings["brief_enabled"]:
        await morning_brief(session, feishu, user, settings)
