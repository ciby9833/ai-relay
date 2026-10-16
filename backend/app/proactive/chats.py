"""从群聊里提取要处理的事：谁让谁做什么、什么时候要。

群消息本身不推送。提取出来的事归到对应用户的跟进看板上：
    别人让 Relay 用户做事 → 他的“等你”
    Relay 用户让别人做事 → 他的“等别人”（到期没动静会提醒）
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient
from app.models import ChatMessage, Signal, User
from app.proactive import items
from app.proactive.llm import complete_structured
from app.proactive.prompts import CHAT_TASKS_SYSTEM

logger = logging.getLogger("relay.chats")

RETENTION = timedelta(days=14)
BATCH = 40
CONTEXT = 10
WAITING_DEFAULT = timedelta(days=2)

TASKS_TOOL = {
    "name": "report_tasks",
    "description": "报告从这段群聊新消息里提取出的待办",
    "input_schema": {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "message_ref": {"type": "integer", "description": "提出这件事的那条消息的编号"},
                        "requester": {"type": "string", "description": "提出要求的人名"},
                        "assignee": {"type": "string", "description": "要去做这件事的人名"},
                        "task": {"type": "string", "description": "要做什么，一句话，可独立读懂"},
                        "due": {"type": "string", "enum": ["today", "this_week", "none"]},
                    },
                    "required": ["message_ref", "requester", "assignee", "task", "due"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["tasks"],
        "additionalProperties": False,
    },
}


def chat_link(chat_id: str) -> str:
    return f"https://applink.feishu.cn/client/chat/open?openChatId={chat_id}"


async def extract(session: AsyncSession, feishu: FeishuClient, only_chats: list[str] | None = None) -> None:
    """处理群里还没看过的新消息。worker 每轮调用一次（不分用户）；only_chats 用于只处理指定的群。"""
    await session.execute(delete(ChatMessage).where(ChatMessage.created_at < datetime.now(UTC) - RETENTION))
    pending = select(ChatMessage.chat_id).where(ChatMessage.processed.is_(False)).distinct()
    if only_chats is not None:
        pending = pending.where(ChatMessage.chat_id.in_(only_chats))
    chat_ids = list((await session.execute(pending)).scalars())
    users = {u.feishu_open_id: u for u in (await session.execute(select(User))).scalars()}
    by_name = {u.name: u for u in users.values()}
    for chat_id in chat_ids:
        new = list((await session.execute(
            select(ChatMessage).where(ChatMessage.chat_id == chat_id, ChatMessage.processed.is_(False))
            .order_by(ChatMessage.created_at, ChatMessage.id).limit(BATCH)
        )).scalars())
        earlier = list((await session.execute(
            select(ChatMessage).where(ChatMessage.chat_id == chat_id, ChatMessage.processed.is_(True))
            .order_by(ChatMessage.created_at.desc()).limit(CONTEXT)
        )).scalars())[::-1]
        involved = {m.sender_open_id for m in new} | {x.get("open_id") for m in new for x in m.mentions}
        for message in new:
            message.processed = True
        if not involved & set(users):
            continue  # 这段新消息和任何 Relay 用户都无关
        lines = [f"（之前）{m.sender_name or '某人'}：{m.text}" for m in earlier]
        lines += [f"[{i}] {m.sender_name or '某人'}：{m.text}" for i, m in enumerate(new)]
        try:
            result = await complete_structured(
                CHAT_TASKS_SYSTEM, "<chat>\n" + "\n".join(lines) + "\n</chat>", TASKS_TOOL
            )
        except Exception:
            logger.exception("提取群聊待办失败 %s", chat_id)
            continue
        for task in result["tasks"]:
            if not 0 <= task["message_ref"] < len(new):
                continue
            source = new[task["message_ref"]]
            mentioned = {x.get("name"): x.get("open_id") for x in source.mentions}
            assignee = users.get(mentioned.get(task["assignee"])) or by_name.get(task["assignee"])
            requester = users.get(source.sender_open_id) or by_name.get(task["requester"])
            due = items._due(task["due"], assignee or requester) if (assignee or requester) else None
            if assignee and assignee != requester:
                await items.upsert(
                    session, assignee, f"chat:{source.message_id}:{assignee.id}", None, silent=False,
                    kind="request", owner="me", title=f"{task['requester']} 让你：{task['task']}",
                    summary=f"「{source.text[:200]}」", next_step="完成后在群里回复对方",
                    url=chat_link(chat_id), due_at=due,
                )
                # 同一条消息已经建成待办，不再单独提醒“@你没回”
                await session.execute(
                    update(Signal).where(Signal.user_id == assignee.id, Signal.kind == "mention",
                                         Signal.external_id == source.message_id).values(status="done")
                )
            if requester and requester != assignee:
                await items.upsert(
                    session, requester, f"chat:{source.message_id}:{requester.id}", None, silent=True,
                    kind="waiting", owner="others", title=f"等 {task['assignee']}：{task['task']}",
                    summary=f"「{source.text[:200]}」", waiting_on=task["assignee"],
                    next_step="Relay 会在到期时提醒你跟进", url=chat_link(chat_id),
                    due_at=due, remind_at=due or datetime.now(UTC) + WAITING_DEFAULT,
                )
    await session.commit()


async def related(session: AsyncSession, keywords: list[str], limit: int = 5) -> list[ChatMessage]:
    """起草回复时找相关的群聊背景。"""
    words = [w for w in keywords if len(w) >= 2][:4]
    if not words:
        return []
    result = await session.execute(
        select(ChatMessage).where(or_(*[ChatMessage.text.ilike(f"%{w}%") for w in words]))
        .order_by(ChatMessage.created_at.desc()).limit(limit)
    )
    return list(result.scalars())
