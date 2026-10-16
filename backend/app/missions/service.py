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


async def log(session: AsyncSession, mission: Mission, kind: str, text: str) -> None:
    session.add(MissionLog(mission_id=mission.id, kind=kind, text=text[:4000]))


async def create(session: AsyncSession, user: User, title: str, goal: str) -> Mission:
    conversation = Conversation(user_id=user.id, channel="mission", title=title)
    session.add(conversation)
    await session.flush()
    mission = Mission(
        user_id=user.id, conversation_id=conversation.id, title=title, goal=goal,
        status="active", next_run_at=datetime.now(UTC), plan=[], grants=[],
    )
    session.add(mission)
    await session.flush()
    await log(session, mission, "step", f"接下任务：{goal}")
    return mission


def card(mission: Mission) -> dict:
    return {"kind": "mission", "mission_id": mission.id}


# ---------- 什么时候醒 ----------


async def wake_reason(session: AsyncSession, mission: Mission) -> str | None:
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
                return f"[收到回信] {mail.payload.get('from')}《{mail.title}》（邮件 #{mail.id}）：\n{(mail.body or '')[:2000]}"
        elif kind == "chat_message":
            statement = select(ChatMessage).where(ChatMessage.chat_id == wait.get("chat_id"), ChatMessage.created_at > since)
            if wait.get("from_open_id"):
                statement = statement.where(ChatMessage.sender_open_id == wait["from_open_id"])
            messages = (await session.execute(statement.order_by(ChatMessage.created_at).limit(10))).scalars().all()
            if messages:
                return "[群里有新消息]\n" + "\n".join(f"- {m.sender_name or '某人'}：{m.text}" for m in messages)
        if mission.next_run_at and mission.next_run_at <= now:
            return f"[等待超时] 等的事件（{describe_wait(wait)}）到现在还没发生"
        return None

    if mission.status == "active" and mission.next_run_at and mission.next_run_at <= now:
        return "[到点了] 按计划回来看看进展"
    return None


def describe_wait(wait: dict) -> str:
    kind = wait.get("type")
    if kind == "mail_reply":
        return "对方回复邮件"
    if kind == "chat_message":
        return "群里有人回复" + (f"（{wait.get('from_name')}）" if wait.get("from_name") else "")
    if kind == "action":
        return "用户确认操作"
    return kind or "事件"


# ---------- 醒来推进一步 ----------


def briefing(mission: Mission, reason: str, user: User) -> str:
    """每次醒来交给 Relay 的消息：为什么醒、任务现状。"""
    plan = "\n".join(f"- [{'x' if s.get('status') == 'done' else ' '}] {s.get('step')}" for s in mission.plan) or "（还没有计划）"
    grants = "、".join(GRANTABLE.get(g, g) for g in mission.grants) or "无（所有对外操作都要等用户确认）"
    return (
        f"{reason}\n\n"
        f"<mission id=\"{mission.id}\">\n任务：{mission.title}\n目标：{mission.goal}\n"
        f"计划：\n{plan}\n笔记：{mission.notes or '（无）'}\n"
        f"用户已授权自动执行：{grants}\n已醒来 {mission.runs} 次\n</mission>"
    )


async def run(session: AsyncSession, feishu: FeishuClient, mission: Mission, reason: str) -> None:
    from app.agent.loop import conversation_lock, run_turn_text  # 避免循环导入

    user = await session.get(User, mission.user_id)
    conversation = await session.get(Conversation, mission.conversation_id)
    started = datetime.now(UTC)
    mission.runs += 1
    before = (mission.status, mission.next_run_at, mission.wait_for)
    # 先清掉“醒来”的条件；Relay 这一轮必须重新决定接下来等什么
    mission.status, mission.wait_for, mission.next_run_at = "active", None, None
    mission.updated_at = datetime.now(UTC)
    await log(session, mission, "wake", reason.splitlines()[0])
    await session.commit()

    async with conversation_lock(conversation.id):
        try:
            text = await run_turn_text(
                session, user=user, conversation=conversation, text=briefing(mission, reason, user),
                feishu=feishu, mission=mission,
            )
        except LLMError as exc:
            logger.warning("任务 #%s 调用模型失败: %s", mission.id, exc)
            mission.status, mission.next_run_at = before[0] if before[0] in OPEN else "active", datetime.now(UTC) + timedelta(minutes=30)
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


async def due(session: AsyncSession, limit: int = 5) -> list[tuple[Mission, str]]:
    missions = (await session.execute(
        select(Mission).where(Mission.status.in_(OPEN)).order_by(Mission.next_run_at.asc().nulls_last())
    )).scalars().all()
    ready = []
    for mission in missions:
        reason = await wake_reason(session, mission)
        if reason:
            ready.append((mission, reason))
        if len(ready) >= limit:
            break
    return ready


async def run_due(session: AsyncSession, feishu: FeishuClient) -> None:
    for mission, reason in await due(session):
        try:
            await run(session, feishu, mission, reason)
        except Exception:
            logger.exception("任务 #%s 执行失败", mission.id)
            await session.rollback()


async def answer(session: AsyncSession, mission: Mission, text: str) -> None:
    """用户回答了任务提出的问题：马上唤醒它。"""
    mission.status, mission.question = "active", None
    mission.next_run_at = datetime.now(UTC)
    mission.wait_for = {"type": "answer", "text": text}
    await log(session, mission, "step", f"你回答：{text}")


def local(moment: datetime | None, user: User) -> str:
    return moment.astimezone(ZoneInfo(user.timezone)).strftime("%m-%d %H:%M") if moment else "-"
