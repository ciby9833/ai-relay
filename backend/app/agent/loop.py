"""Agent 主循环：Web、飞书、定时任务三个入口共用。"""

import asyncio
import logging
import re
import uuid
import weakref
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import i18n, insights
from app.proactive.settings import get_settings_row, language_of
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import ToolContext, execute, tool_specs
from app.feishu.client import FeishuClient
from app.llm import registry
from app.llm.base import Completion, TextDelta
from app.memory import service as memory_service
from app.models import Conversation, FollowUp, Message, Mission, PendingAction, User

logger = logging.getLogger(__name__)

MAX_STEPS = 8
MISSION_MAX_STEPS = 16  # 后台长期任务一轮里往往要查好几样东西
HISTORY_LIMIT = 40
WEEKDAYS = "一二三四五六日"

_locks: weakref.WeakValueDictionary[uuid.UUID, asyncio.Lock] = weakref.WeakValueDictionary()


def conversation_lock(conversation_id: uuid.UUID) -> asyncio.Lock:
    """同一会话同一时间只跑一轮，避免历史交错。"""
    lock = _locks.get(conversation_id)
    if lock is None:
        lock = _locks[conversation_id] = asyncio.Lock()
    return lock


def _has(message: dict, block_type: str) -> bool:
    return any(block["type"] == block_type for block in message["content"])


def sanitize_history(messages: list[dict]) -> list[dict]:
    """截取窗口后保证历史仍然合法：以一条真正的用户消息开头，结尾没有悬空的工具调用。"""
    start = 0
    while start < len(messages) and (
        messages[start]["role"] != "user" or _has(messages[start], "tool_result")
    ):
        start += 1
    messages = messages[start:]
    if messages and messages[-1]["role"] == "assistant" and _has(messages[-1], "tool_use"):
        messages = messages[:-1]
    return messages


async def load_history(session: AsyncSession, conversation_id: uuid.UUID) -> list[dict]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        # 同一事务写入的消息 created_at 相同：按 (created_at, id) 排，
        # 其他进程（worker 发主动消息）插进来的消息不会夹在工具调用和它的结果之间
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(HISTORY_LIMIT)
    )
    rows = list(result.scalars())[::-1]
    actions = await _actions_for(session, rows)
    item_ids = {b["card"].get("item_id") for r in rows for b in r.content if b["type"] == "card"} - {None}
    follow_ups = {}
    if item_ids:
        result = await session.execute(select(FollowUp).where(FollowUp.id.in_(item_ids)))
        follow_ups = {i.id: i for i in result.scalars()}
    return sanitize_history(_with_card_notes(rows, actions, follow_ups))


async def _actions_for(session: AsyncSession, rows: list[Message]) -> dict[int, PendingAction]:
    ids = {b["card"].get("action_id") for r in rows for b in r.content if b["type"] == "card"} - {None}
    if not ids:
        return {}
    result = await session.execute(select(PendingAction).where(PendingAction.id.in_(ids)))
    return {a.id: a for a in result.scalars()}


def card_text(card: dict, actions: dict[int, PendingAction], follow_ups: dict[int, FollowUp]) -> str:
    kind = card.get("kind")
    if kind == "draft" and (action := actions.get(card.get("action_id"))):
        status = {"pending": "待用户确认", "done": "已发送", "cancelled": "已取消", "failed": "发送失败"}[action.status]
        return f"[回复草稿 #{action.id}（{status}），收件人 {action.payload.get('to')}]\n{action.payload.get('body')}"
    if kind == "mail":
        return f"[邮件 #{card.get('signal_id')}] {card.get('from')}《{card.get('subject')}》{card.get('summary') or ''}"
    if kind == "action" and (action := actions.get(card.get("action_id"))):
        if action.kind == "cloud_write":
            return f"[云文档操作 #{action.id}（{action.status}）] {action.summary}\n{action.result or action.payload.get('body', '')}"
        return f"[待确认操作 #{action.id}（{action.status}）] {action.summary}"
    if kind == "mission":
        return f"[长期任务 #{card.get('mission_id')}]"
    if kind == "item":
        item = follow_ups.get(card.get("item_id"))
        if item is None:
            return f"[跟进事项 #{card.get('item_id')}]"
        action = f"，待确认操作 #{item.action_id}" if item.action_id else ""
        return f"[跟进事项 #{item.id}（{item.kind}，{'等他' if item.owner == 'me' else '等别人'}，{item.status}{action}）] {item.title}：{item.summary or ''}"
    if kind == "event":
        extra = f"，待确认操作 #{card['action_id']}" if card.get("action_id") else ""
        return f"[日程 #{card.get('signal_id')}] {card.get('start')} 《{card.get('title')}》回复状态 {card.get('rsvp')}{extra}"
    return f"[{kind}] {card.get('title') or ''} {card.get('detail') or card.get('summary') or ''}".strip()


CARD_NOTE = "〔系统记录，不是用户说的话，也不要在回复里模仿这个格式：上一条助手消息同时以卡片形式向用户展示了〕"


def _with_card_notes(rows: list[Message], actions: dict[int, PendingAction], follow_ups: dict[int, FollowUp]) -> list[dict]:
    """卡片块各家模型都看不到，要换成文字让模型知道展示过什么（比如草稿编号）。

    这段说明放进下一条用户侧消息（工具结果或用户的下一句话）里，不放进助手自己的消息：
    放在助手消息里，模型会以为这是自己说过的话，照着格式写进回复。
    """
    messages, pending = [], []
    for row in rows:
        blocks = [b for b in row.content if b["type"] != "card"]
        cards = [b["card"] for b in row.content if b["type"] == "card"]
        if row.role == "user" and pending:
            note = {"type": "text", "text": CARD_NOTE + "\n" + "\n".join(pending)}
            # 工具结果块保持在最前（部分模型要求）
            results = [b for b in blocks if b["type"] == "tool_result"]
            blocks = results + [note] + [b for b in blocks if b["type"] != "tool_result"]
            pending = []
        if row.role == "assistant":
            pending += [card_text(c, actions, follow_ups) for c in cards]
            if cards and not blocks:
                blocks = [{"type": "text", "text": "（发了卡片）"}]  # 只有卡片的主动提醒：保持用户/助手交替
        if blocks:
            messages.append({"role": row.role, "content": blocks})
    if pending and messages and not _has(messages[-1], "tool_use"):
        # 最后一条是带卡片的助手消息（例如主动提醒）：说明交给本轮的用户消息带上
        messages.append({"role": "user", "content": [{"type": "text", "text": CARD_NOTE + "\n" + "\n".join(pending)}]})
    return messages


async def build_context(
    session: AsyncSession, user: User, conversation: Conversation, text: str
) -> str:
    now = datetime.now(UTC).astimezone(ZoneInfo(user.timezone))
    lines = [
        "<context>",
        f"当前时间：{now:%Y-%m-%d %H:%M} 周{WEEKDAYS[now.weekday()]}（{user.timezone}）",
        f"用户：{user.name}",
        f"渠道：{conversation.channel}",
        f"用户常用语言：{i18n.LANGUAGES[await language_of(session, user)]}",
    ]
    profile = await memory_service.list_memories(
        session, user.id, "profile", memory_service.PROFILE_LIMIT
    )
    if profile:
        lines.append("关于用户的长期记忆：")
        lines += [f"- #{m.id} {m.content}" for m in reversed(profile)]
    open_items = (await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == "open")
        .order_by(FollowUp.updated_at.desc()).limit(12)
    )).scalars().all()
    if open_items:
        from app.proactive import items as follow_ups  # 避免循环导入

        lines.append("正在跟进的事（含最近一次往来）：")
        lines += [f"- {await follow_ups.context_line(session, i, user.timezone)}" for i in open_items]
    closed = (await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status != "open",
                               FollowUp.closed_at > datetime.now(UTC) - timedelta(days=1))
        .order_by(FollowUp.closed_at.desc()).limit(5)
    )).scalars().all()
    if closed:
        # 用户问“那件事怎么样了”时，刚结束的事也要知道怎么结束的
        lines.append("最近一天结束的事：")
        lines += [f"- #{i.id} {i.title} → {i.resolution or i.status}" for i in closed]
    if conversation.channel != "mission":
        missions = (await session.execute(
            select(Mission).where(Mission.user_id == user.id, Mission.status.in_(["active", "waiting", "asking"]))
            .order_by(Mission.id).limit(8)
        )).scalars().all()
        if missions:
            lines.append("正在办的长期任务：")
            lines += [
                f"- #{m.id} {m.title}" + (f"（在等他回答：{m.question}）" if m.status == "asking" else "")
                for m in missions
            ]
    related = await memory_service.search_memories(session, user.id, text, "episodic", 5)
    if related:
        lines.append("可能相关的过往记忆：")
        lines += [f"- #{m.id}（{m.created_at:%Y-%m-%d}）{m.content}" for m in related]
    lines.append("</context>")
    return "\n".join(lines)


async def run_turn(
    session: AsyncSession,
    *,
    user: User,
    conversation: Conversation,
    text: str,
    feishu: FeishuClient,
    model_id: str | None = None,
    mission=None,
    task=None,
) -> AsyncIterator[dict]:
    """处理用户的一条消息，产出事件流：

    {"type": "text", "delta": str}
    {"type": "tool_start" | "tool_end", "name": str, ...}
    {"type": "error", "message": str}
    {"type": "done"}

    调用方负责持有 conversation_lock。
    """
    provider, model, model_id = registry.resolve(model_id)
    # 定时任务和长期任务是无人值守的，不提供“确认执行”一类的工具
    user_initiated = conversation.channel not in ("task", "mission")
    insights.via.set("chat" if user_initiated else "system")
    tools = tool_specs(user_initiated, conversation.channel)
    ctx = ToolContext(session=session, user=user, conversation=conversation, feishu=feishu, mission=mission, task=task)

    messages = await load_history(session, conversation.id)
    if user_initiated:
        # 记住他习惯用什么语言（主动提醒、简报、卡片按钮都用这个语言）
        row = await get_settings_row(session, user)
        if (learned := i18n.learn(row.data or {}, text)) is not None:
            row.data = learned
    user_content = [
        # meta 只是存储标记：前端据此隐藏这一块，发给模型前不需要处理（适配器只读 type/text）
        {
            "type": "text",
            "text": await build_context(session, user, conversation, text),
            "meta": "context",
        },
        {"type": "text", "text": text},
    ]
    session.add(Message(conversation_id=conversation.id, role="user", content=user_content))
    if not conversation.title:
        conversation.title = text.strip().splitlines()[0][:60] if text.strip() else None
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    if messages and messages[-1]["role"] == "user":
        messages[-1] = {"role": "user", "content": messages[-1]["content"] + user_content}
    else:
        messages.append({"role": "user", "content": user_content})

    max_steps = MISSION_MAX_STEPS if conversation.channel == "mission" else MAX_STEPS
    for _ in range(max_steps):
        completion: Completion | None = None
        async for event in provider.stream(
            model=model, system=SYSTEM_PROMPT, messages=messages, tools=tools
        ):
            if isinstance(event, TextDelta):
                yield {"type": "text", "delta": event.text}
            else:
                completion = event
        if completion is None:
            raise RuntimeError("模型没有返回结果")

        blocks = completion.blocks
        tool_uses = [block for block in blocks if block["type"] == "tool_use"]
        if completion.stop_reason in ("max_tokens", "refusal"):
            # 被截断的工具参数不可信，拒答时的工具调用也不执行：只保留文字
            blocks = [block for block in blocks if block["type"] == "text"]
            tool_uses = []
        assistant_message = None
        if blocks:
            assistant_message = Message(
                conversation_id=conversation.id, role="assistant", content=blocks, model=model_id
            )
            session.add(assistant_message)

        if not tool_uses:
            await session.commit()
            if completion.stop_reason == "refusal":
                yield {"type": "error", "message": "模型拒绝了这个请求"}
            elif completion.stop_reason == "max_tokens":
                yield {"type": "error", "message": "回答过长，被截断了"}
            break

        results = []
        for call in tool_uses:
            yield {"type": "tool_start", "name": call["name"]}
            content, is_error = await execute(ctx, call["name"], call["input"], user_initiated)
            yield {"type": "tool_end", "name": call["name"], "ok": not is_error}
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "name": call["name"],
                    "content": content,
                    "is_error": is_error,
                }
            )
        if ctx.cards:
            # 工具产出的卡片挂在发起调用的那条助手消息上；各家模型适配器会忽略 card 块
            assistant_message.content = blocks + [{"type": "card", "card": c} for c in ctx.cards]
            yield {"type": "cards", "cards": ctx.cards}
            ctx.cards = []
        session.add(Message(conversation_id=conversation.id, role="user", content=results))
        # 工具调用和它的结果在同一个事务里落库，历史里不会出现没有结果的调用
        await session.commit()

        messages.append(
            {
                "role": "assistant",
                "content": blocks,
                "raw": completion.raw,
                "raw_provider": provider.name if completion.raw is not None else None,
            }
        )
        messages.append({"role": "user", "content": results})
        if ctx.stop_turn:
            break  # 长期任务已经决定接下来等什么，这一轮结束
    else:
        yield {"type": "error", "message": f"连续调用工具超过 {max_steps} 步，已停止"}

    yield {"type": "done"}


async def run_turn_text(session: AsyncSession, **kwargs) -> str:
    """不需要流式的入口（飞书、定时任务）：跑完一轮，返回最后的回答。

    工具调用之间的过程性文字（“我先查一下…”）不发出去，只发最后一段；最后一段为空时用最近一段非空文字。
    """
    segments: list[str] = [""]
    errors: list[str] = []
    async for event in run_turn(session, **kwargs):
        if event["type"] == "text":
            segments[-1] += event["delta"]
        elif event["type"] == "tool_start" and segments[-1].strip():
            segments.append("")
        elif event["type"] == "error":
            errors.append(event["message"])
    text = next((s for s in reversed(segments) if s.strip()), "").strip()
    text = strip_leaked_notes(text)
    if errors:
        text = f"{text}\n\n（{'；'.join(errors)}）".strip()
    return text


LEAKED = re.compile(r"^[（〔](以下内容以卡片形式展示给了用户|系统记录[^）〕]*)[）〕][^\n]*\n(\[[^\]\n]+\][^\n]*\n?)*", re.M)


def strip_leaked_notes(text: str) -> str:
    """兜底：模型偶尔会照抄历史里的卡片说明，发给用户前去掉。"""
    return LEAKED.sub("", text).strip()
