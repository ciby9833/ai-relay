"""长期任务的生命周期：创建 → 醒来推进一步 → 等时间/等事件/等用户 → …… → 完成。

每个任务有自己的对话（channel=mission），Relay 每次醒来都在这条对话里接着干，
所以能记得之前做过什么。醒来的原因（到点了、对方回信了、用户确认了……）作为一条新消息追加进去。
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
from app.home import ConversationBusy, post
from app.llm.base import LLMError
from app.models import ChatMessage, Conversation, Mission, MissionLog, PendingAction, Signal, User
from app.proactive.actions import GRANTABLE

logger = logging.getLogger("relay.missions")

OPEN = ("active", "waiting", "asking")
MAX_RUNS = 60  # 单个任务最多醒来的次数，防止失控
DEFAULT_RECHECK = timedelta(hours=6)
DEFAULT_WAIT_TIMEOUT = timedelta(hours=24)


WORK_START, WORK_END = 9, 18  # 以用户时区计的工作时间（对外发消息、催人只在这个时间段）
MAX_NUDGES = 2  # 同一个人：第一次之外最多自动再催 2 次，之后要问用户


def next_work_morning(timezone: str, after: datetime | None = None) -> datetime:
    """下一个工作日上午 9:30（用户时区）。"""
    local = (after or datetime.now(UTC)).astimezone(ZoneInfo(timezone))
    day = local.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, 9, 30, tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def in_work_hours(timezone: str, moment: datetime | None = None) -> bool:
    local = (moment or datetime.now(UTC)).astimezone(ZoneInfo(timezone))
    return local.weekday() < 5 and WORK_START <= local.hour < WORK_END


async def log(session: AsyncSession, mission: Mission, kind: str, text: str) -> None:
    session.add(MissionLog(mission_id=mission.id, kind=kind, text=text[:4000]))


async def create(
    session: AsyncSession, user: User, title: str, goal: str, instruction: str | None = None, due_at: datetime | None = None
) -> Mission:
    conversation = Conversation(user_id=user.id, channel="mission", title=title)
    session.add(conversation)
    await session.flush()
    mission = Mission(
        user_id=user.id, conversation_id=conversation.id, title=title, goal=goal,
        instruction=instruction, due_at=due_at, status="active", next_run_at=datetime.now(UTC), plan=[], grants=[],
    )
    session.add(mission)
    await session.flush()
    await log(session, mission, "step", f"接下任务：{goal}")
    return mission


def card(mission: Mission) -> dict:
    return {"kind": "mission", "mission_id": mission.id}


# ---------- 什么时候醒 ----------


REPLY_MARK = "[对方回复了]"


async def _poll_chat(session: AsyncSession, feishu: FeishuClient, mission: Mission, wait: dict, since: datetime) -> list[str]:
    """以用户本人身份拉取等待中的会话（群聊或私聊）里的新消息。

    机器人只收得到它所在群的消息；以用户身份发出的私聊、机器人不在的群，只能这样主动查。
    """
    from app.sources import im

    user = await session.get(User, mission.user_id)
    hours = max(1, min(336, int((datetime.now(UTC) - since).total_seconds() // 3600) + 1))
    try:
        messages = await im.recent_messages(feishu, user, wait["chat_id"], hours=hours, limit=50)
    except FeishuError as exc:
        if not wait.get("poll_error"):
            # 只记一次（例如没有读取私聊的权限），之后靠超时兜底
            mission.wait_for = {**wait, "poll_error": str(exc)[:300]}
            await log(session, mission, "step", f"读不到这个会话的新消息，只能到点再看：{exc}")
        return []
    lines = []
    for m in messages:
        if m["at"] <= since or m["sender_type"] != "user" or m["sender"] == user.feishu_open_id:
            continue
        if wait.get("from_open_id") and m["sender"] != wait["from_open_id"]:
            continue
        name = wait.get("from_name") if m["sender"] == wait.get("from_open_id") else None
        name = name or await feishu.user_name(m["sender"]) or "对方"
        lines.append(f"- {m['at'].astimezone(ZoneInfo(user.timezone)):%m-%d %H:%M} {name}：{m['text']}")
    return lines


async def wake_reason(session: AsyncSession, mission: Mission, feishu: FeishuClient | None = None) -> str | None:
    """返回这次醒来的原因（会作为新消息交给 Relay）；不该醒时返回 None。"""
    now = datetime.now(UTC)
    since = mission.updated_at

    # 任务里准备的操作有了结果（用户确认/取消，或执行失败）
    decided = (await session.execute(
        select(PendingAction).where(
            PendingAction.mission_id == mission.id, PendingAction.status != "pending",
            PendingAction.decided_at > since,
        )
    )).scalars().all()
    if decided:
        status = {"done": "已执行", "cancelled": "被用户取消", "failed": "执行失败"}
        return "[操作有了结果]\n" + "\n".join(
            f"- #{a.id} {a.summary}：{status.get(a.status, a.status)}{('（' + a.result + '）') if a.result else ''}"
            for a in decided
        )

    if mission.status == "asking":
        return None  # 等用户回答，由 answer() 唤醒

    wait = mission.wait_for or {}
    if wait.get("type") == "answer":
        return f"[用户回答了你的问题] {wait.get('text')}"
    if mission.status == "waiting" and wait:
        kind = wait.get("type")
        if kind == "mail_reply":
            mail = (await session.execute(
                select(Signal).where(
                    Signal.user_id == mission.user_id, Signal.kind == "mail", Signal.created_at > since,
                    Signal.payload["thread_id"].astext == wait.get("thread_id"),
                ).order_by(Signal.id.desc())
            )).scalars().first()
            if mail:
                return f"{REPLY_MARK}（邮件）{mail.payload.get('from')}《{mail.title}》（邮件 #{mail.id}）：\n{(mail.body or '')[:2000]}"
        elif kind == "chat_message":
            waiting_since = datetime.fromisoformat(wait["since"]) if wait.get("since") else since
            from app.feishu.client import has_feishu

            lines = await _poll_chat(session, feishu, mission, wait, waiting_since) if feishu is not None and has_feishu(feishu) else []
            if not lines:
                # 机器人在群里时收到的消息（拉取失败时的兜底）
                statement = select(ChatMessage).where(
                    ChatMessage.tenant_id == select(User.tenant_id).where(User.id == mission.user_id).scalar_subquery(),
                    ChatMessage.chat_id == wait.get("chat_id"), ChatMessage.created_at > waiting_since)
                if wait.get("from_open_id"):
                    statement = statement.where(ChatMessage.sender_open_id == wait["from_open_id"])
                messages = (await session.execute(statement.order_by(ChatMessage.created_at).limit(10))).scalars().all()
                lines = [f"- {m.sender_name or '某人'}：{m.text}" for m in messages]
            if lines:
                return f"{REPLY_MARK}（{wait.get('chat_name') or '会话'}）\n" + "\n".join(lines)
        if mission.next_run_at and mission.next_run_at <= now:
            return f"[等待超时] 等的事件（{describe_wait(wait)}）到现在还没发生"
        return None
    if mission.status == "waiting" and mission.next_run_at and mission.next_run_at <= now:
        return "[到点了] 按计划回来看看进展"  # 兜底：没有等待条件的 waiting 不能永远睡下去

    if mission.status == "active" and mission.next_run_at and mission.next_run_at <= now:
        return "[到点了] 按计划回来看看进展"
    return None


def describe_wait(wait: dict) -> str:
    kind = wait.get("type")
    if kind == "mail_reply":
        return "对方回复邮件"
    if kind == "chat_message":
        who = wait.get("from_name") or "对方"
        return f"{who}在「{wait.get('chat_name')}」回复" if wait.get("chat_name") else f"{who}回复"
    if kind == "action":
        return "用户确认操作"
    return kind or "事件"


async def auto_send_blocked(session: AsyncSession, mission: Mission, user: User, action: PendingAction) -> str | None:
    """已授权“发消息”时，这些情况仍要用户确认：返回原因；可以自动发时返回 None。

    - 换了会话或对象：授权只覆盖已经发过的那个会话（私聊里催过，不能自己转到有其他人的群里公开催）
    - 同一个会话里已经催过 MAX_NUDGES 次
    - 不在工作时间
    """
    sent = (await session.execute(
        select(PendingAction).where(PendingAction.mission_id == mission.id, PendingAction.kind == "send_chat",
                                    PendingAction.status == "done")
    )).scalars().all()
    same = [a for a in sent if a.payload.get("receive_id") == action.payload.get("receive_id")]
    if not same:
        return "要发到一个新的会话或对象（不是之前发过的那个），需要用户确认"
    if len(same) > MAX_NUDGES:
        return f"这个会话里已经发过 {len(same)} 次，再催需要用户确认"
    if not in_work_hours(user.timezone):
        return "现在不是工作时间，发消息需要用户确认（或等到工作时间再发）"
    return None


# ---------- 醒来推进一步 ----------


REPLY_GUIDE = """对方回复了。先对照“用户原话”判断这条回复属于哪一种，再决定下一步：
- 已经办成 → complete_mission，把对方的答复转告用户；
- 承诺了时间（“月底前”“明天给”“下午发”）→ report_progress 告诉用户对方的答复，然后 wait_until 到那个时间再核实，不要追问细节；
- 部分完成 → report_progress 说明还差什么，问用户要不要继续追；
- 拒绝、说做不了 → ask_user 问用户怎么办；
- 看不懂（只回了“1”“收到”“好”“ok”）→ 结合上下文理解（中文聊天里“1”通常是收到/已办）；仍拿不准就 ask_user，不要去追问同事。
不要向对方提出用户原话里没有的要求（例如用户只要“给个结果”，就不要再追问清单、细节）。"""


TIMELINE = 12


async def briefing(session: AsyncSession, mission: Mission, reason: str, user: User) -> str:
    """每次醒来交给 Relay 的全部上下文：为什么醒、用户原话、验收清单、计划、笔记、最近的时间线和操作。

    每次醒来都从这里开始（不带之前几轮的对话历史）：长任务靠清单和笔记接续，而不是靠越来越长的对话，
    这样不会被早先的大段工具结果冲淡注意力，也不会沿着旧的思路越走越偏。
    """
    from app.missions import criteria

    tz = ZoneInfo(user.timezone)
    plan = "\n".join(f"- [{'x' if s.get('status') == 'done' else ' '}] {s.get('step')}" for s in mission.plan) or "（还没有计划）"
    logs = list((await session.execute(
        select(MissionLog).where(MissionLog.mission_id == mission.id).order_by(MissionLog.id.desc()).limit(TIMELINE)
    )).scalars())[::-1]
    timeline = "\n".join(f"log:{x.id} {x.created_at.astimezone(tz):%m-%d %H:%M} [{x.kind}] {x.text[:300]}" for x in logs) or "（无）"
    actions = list((await session.execute(
        select(PendingAction).where(PendingAction.mission_id == mission.id).order_by(PendingAction.id.desc()).limit(10)
    )).scalars())[::-1]
    action_lines = "\n".join(
        f"action:{a.id} {a.summary}：{a.status}" + (f"，{a.result[:120]}" if a.result else "")
        + (f"（写入后核对：{ {True: '一致', False: '不一致', None: '未核对'}.get(a.payload['verified'].get('ok'))}，{a.payload['verified'].get('detail')}）"
           if (a.payload or {}).get("verified") else "")
        for a in actions
    ) or "（无）"
    grants = "、".join(GRANTABLE.get(g, g) for g in mission.grants) or "无（所有对外操作都要等用户确认）"
    guide = f"\n\n{REPLY_GUIDE}" if reason.startswith(REPLY_MARK) else ""
    return (
        f"{reason}{guide}\n\n"
        f"<mission id=\"{mission.id}\">\n任务：{mission.title}\n"
        + (f"用户原话（判断办成没有以这句为准）：{mission.instruction}\n" if mission.instruction else "")
        + f"目标：{mission.goal}\n"
        + (f"截止/复查时间：{mission.due_at.astimezone(ZoneInfo(user.timezone)):%Y-%m-%d %H:%M}\n" if mission.due_at
           else "截止/复查时间：用户没提（催人按默认节奏：下一个工作日上午，最多再催 2 次，之后问用户）\n")
        + f"现在：{datetime.now(UTC).astimezone(ZoneInfo(user.timezone)):%Y-%m-%d %H:%M}\n"
        f"验收清单（做到这几条才算办成；你只能用 check_criterion 标记状态和证据，条目只有用户能改）：\n{criteria.describe(mission)}\n"
        f"计划：\n{plan}\n笔记：{mission.notes or '（无）'}\n"
        f"最近的时间线（log:编号 可以作为证据）：\n{timeline}\n"
        f"这个任务的操作（action:编号）：\n{action_lines}\n"
        f"用户已授权自动执行：{grants}\n已醒来 {mission.runs} 次\n</mission>"
    )


async def run(session: AsyncSession, feishu: FeishuClient, mission: Mission, reason: str) -> None:
    from app.agent.loop import conversation_lock, run_turn_text  # 避免循环导入

    user = await session.get(User, mission.user_id)
    conversation = await session.get(Conversation, mission.conversation_id)
    started = datetime.now(UTC)
    from app import assurance
    assurance.record(session, mission.user_id, "mission_run", mission_id=mission.id)
    mission.runs += 1
    before = (mission.status, mission.next_run_at, mission.wait_for)
    # 先清掉“醒来”的条件；Relay 这一轮必须重新决定接下来等什么
    mission.status, mission.wait_for, mission.next_run_at = "active", None, None
    mission.updated_at = datetime.now(UTC)
    await log(session, mission, "wake", reason.splitlines()[0])
    if reason.startswith(REPLY_MARK):
        # 对方的回复原文记进时间线：之后可以作为验收证据（log:编号）
        session.add(entry := MissionLog(mission_id=mission.id, kind="reply", text=reason[:4000]))
        await session.flush()
        reason = f"{reason}\n（这条回复已记入时间线 log:{entry.id}，可以作为验收证据）"
    await session.commit()

    async with conversation_lock(conversation.id):
        try:
            text = await run_turn_text(
                session, user=user, conversation=conversation, text=await briefing(session, mission, reason, user),
                feishu=feishu, mission=mission,
            )
        except LLMError as exc:
            logger.warning("任务 #%s 调用模型失败: %s", mission.id, exc)
            # 恢复原来的等待；原来没在等具体事件（或等待条件已被清掉）就按“到点再来”重试。
            # 不能只恢复 status：waiting 而 wait_for 为空时 wake_reason 永远不会叫醒它（任务会卡死）
            status, _, wait_for = before
            if status == "waiting" and wait_for:
                mission.status, mission.wait_for = "waiting", wait_for
            else:
                mission.status = "active"
            mission.next_run_at = datetime.now(UTC) + timedelta(minutes=30)
            await log(session, mission, "step", f"模型调用失败，30 分钟后重试：{exc}")
            await session.commit()
            return

    await session.refresh(mission)
    # 这一轮准备了需要用户确认的操作、但 Relay 自己没汇报：替它告诉用户（带确认按钮）
    prepared = (await session.execute(
        select(PendingAction).where(PendingAction.mission_id == mission.id, PendingAction.status == "pending",
                                    PendingAction.created_at >= started).order_by(PendingAction.id)
    )).scalars().all()
    reported = await session.scalar(
        select(MissionLog.id).where(MissionLog.mission_id == mission.id, MissionLog.kind.in_(["report", "ask"]),
                                    MissionLog.created_at >= started).limit(1)
    )
    if reason.startswith(REPLY_MARK) and not reported and not await session.scalar(
        select(MissionLog.id).where(MissionLog.mission_id == mission.id, MissionLog.kind == "done",
                                    MissionLog.created_at >= started).limit(1)
    ):
        # 对方回复了一定要让用户知道：Relay 没汇报时替它转告
        await notify(session, feishu, mission, f"《{mission.title}》对方回复了：\n" + "\n".join(reason.splitlines()[1:6]), important=True)
    if prepared and not reported:
        await notify(
            session, feishu, mission,
            f"《{mission.title}》下一步需要你确认：" + "；".join(a.summary for a in prepared),
            important=True, cards=[{"kind": "action", "action_id": a.id} for a in prepared],
        )
    if mission.status == "active" and mission.next_run_at is None:
        # 这一轮没说接下来做什么：过一段时间再回来看
        mission.next_run_at = datetime.now(UTC) + DEFAULT_RECHECK
        await log(session, mission, "step", "没有指定下一步，6 小时后再看")
    if mission.runs >= MAX_RUNS and mission.status in OPEN:
        mission.status, mission.result = "failed", f"已经推进了 {MAX_RUNS} 次仍未完成，先停下，请你看一下"
        await notify(session, feishu, mission, mission.result, important=True)
    if text:
        await log(session, mission, "step", text[:1000])
    mission.updated_at = datetime.now(UTC)
    await session.commit()


async def notify(session: AsyncSession, feishu: FeishuClient, mission: Mission, text: str, important: bool, cards: list | None = None) -> None:
    """在主线里汇报任务进展（重要的同时推到飞书）。主线正忙时只写进时间线。

    不提交事务（可能在工具调用的保存点里运行），由调用方提交。
    """
    from app.proactive.push import push

    user = await session.get(User, mission.user_id)
    message_cards = [card(mission)] + (cards or [])
    await log(session, mission, "report", text)
    try:
        await post(session, user, event=f"长期任务《{mission.title}》汇报进展", text=text, cards=message_cards)
    except ConversationBusy:
        return  # 用户正在主线里说话：这次只记进时间线（飞书照常推送）
    if important:
        try:
            await push(session, feishu, user, f"Relay 任务｜{mission.title}", text, message_cards)
        except FeishuError:
            logger.exception("任务汇报推送失败")


async def prepared_this_run(session: AsyncSession, mission: Mission) -> list[PendingAction]:
    """这一轮（从醒来那一刻起）准备的、还在等用户确认的操作。"""
    return list((await session.execute(
        select(PendingAction).where(PendingAction.mission_id == mission.id, PendingAction.status == "pending",
                                    PendingAction.created_at >= mission.updated_at).order_by(PendingAction.id)
    )).scalars())


async def due(session: AsyncSession, limit: int = 5, feishu: FeishuClient | None = None) -> list[tuple[Mission, str]]:
    missions = (await session.execute(
        select(Mission).where(Mission.status.in_(OPEN)).order_by(Mission.next_run_at.asc().nulls_last())
    )).scalars().all()
    ready = []
    from app import tenancy

    for mission in missions:
        owner = await session.get(User, mission.user_id)
        client = await tenancy.client_for(session, owner, feishu) if owner is not None else None
        reason = await wake_reason(session, mission, client)
        if reason:
            ready.append((mission, reason))
        if len(ready) >= limit:
            break
    return ready


async def run_due(session: AsyncSession, feishu: FeishuClient) -> None:
    from app import telemetry

    from app import tenancy

    for mission, reason in await due(session, feishu=feishu):
        try:
            client = await tenancy.client_for(session, await session.get(User, mission.user_id), feishu)
            with telemetry.work("mission"):
                await run(session, client, mission, reason)
        except Exception:
            logger.exception("任务 #%s 执行失败", mission.id)
            await session.rollback()


async def answer(session: AsyncSession, mission: Mission, text: str) -> None:
    """用户回答了任务提出的问题：马上唤醒它。"""
    if mission.status == "asking":
        mission.check_rounds = 0  # 用户明确介入后可重新核验，不继承上一轮的重试额度
    mission.status, mission.question = "active", None
    mission.next_run_at = datetime.now(UTC)
    mission.wait_for = {"type": "answer", "text": text}
    await log(session, mission, "step", f"你回答：{text}")


def local(moment: datetime | None, user: User) -> str:
    return moment.astimezone(ZoneInfo(user.timezone)).strftime("%m-%d %H:%M") if moment else "-"
