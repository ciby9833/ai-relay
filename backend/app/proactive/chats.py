"""从群聊里提取要处理的事：谁让谁做什么、什么时候要。

群消息本身不推送。提取出来的事归到对应用户的跟进看板上：
    别人让 Relay 用户做事 → 他的“等你”
    Relay 用户让别人做事 → 他的“等别人”（到期没动静会提醒）
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient
from app.models import ChatMessage, FollowUp, Signal, User
from app.proactive import items
from app.proactive.llm import complete_structured
from app.proactive.prompts import CHAT_TASKS_SYSTEM
from app.sources.base import add_signal

logger = logging.getLogger("relay.chats")

RETENTION = timedelta(days=14)
BATCH = 40
CONTEXT = 10
WAITING_DEFAULT = timedelta(days=2)

TASKS_TOOL = {
    "name": "report_tasks",
    "description": "报告这段聊天新消息里提出的待办，以及未结事项的进展",
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
            },
            "progress": {
                "type": "array",
                "description": "<open> 里的未结事项中，新消息带来了实质进展的（只回了“收到/好的/在看”不算，不用列）",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer"},
                        "verdict": {"type": "string", "enum": ["done", "committed"],
                                    "description": "done=已经办完/给出了这件事要的结果；committed=答应了、给了完成时间但还没办完"},
                        "evidence": {"type": "string", "description": "哪条消息、说了什么，一句话"},
                        "due": {"type": "string", "description": "committed 时：答应的完成时间，ISO 8601（按 <now> 换算）；说不出具体时间就留空"},
                    },
                    "required": ["item_id", "verdict", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["tasks", "progress"],
        "additionalProperties": False,
    },
}


def chat_link(chat_id: str) -> str:
    return f"https://applink.feishu.cn/client/chat/open?openChatId={chat_id}"


async def extract(session: AsyncSession, feishu: FeishuClient, only_chats: list[str] | None = None) -> None:
    """处理群聊和私聊里还没看过的新消息：提出新待办、判断未结事项的进展。worker 每轮调用一次。

    群聊：待办归到相关的每位 Relay 用户。私聊：只归到读取它的那位用户（owner_user_id），不碰别人。
    """
    await session.execute(delete(ChatMessage).where(ChatMessage.created_at < datetime.now(UTC) - RETENTION))
    pending = select(ChatMessage.chat_id, ChatMessage.owner_user_id).where(ChatMessage.processed.is_(False)).distinct()
    if only_chats is not None:
        pending = pending.where(ChatMessage.chat_id.in_(only_chats))
    batches = list((await session.execute(pending)).all())
    users = {u.feishu_open_id: u for u in (await session.execute(select(User))).scalars()}
    by_name = {u.name: u for u in users.values()}
    for chat_id, owner_id in batches:
        owner = next((u for u in users.values() if u.id == owner_id), None) if owner_id else None
        same_chat = (ChatMessage.chat_id == chat_id) & (
            ChatMessage.owner_user_id == owner_id if owner_id else ChatMessage.owner_user_id.is_(None))
        new = list((await session.execute(
            select(ChatMessage).where(same_chat, ChatMessage.processed.is_(False))
            .order_by(ChatMessage.created_at, ChatMessage.id).limit(BATCH)
        )).scalars())
        earlier = list((await session.execute(
            select(ChatMessage).where(same_chat, ChatMessage.processed.is_(True))
            .order_by(ChatMessage.created_at.desc()).limit(CONTEXT)
        )).scalars())[::-1]
        for message in new:
            message.processed = True
        # 这个会话里还没结的事（等别人回复、别人让他做的事）：新消息可能就是进展，要一起判断
        open_query = select(FollowUp).where(FollowUp.status == "open", FollowUp.url == chat_link(chat_id), FollowUp.key.like("chat:%"))
        if owner is not None:
            open_query = open_query.where(FollowUp.user_id == owner.id)
        open_items = list((await session.execute(open_query)).scalars())
        involved = {m.sender_open_id for m in new} | {x.get("open_id") for m in new for x in m.mentions}
        if owner is None and not involved & set(users) and not open_items:
            continue  # 群里这段新消息和任何 Relay 用户都无关，也没有在等这个群里的答复
        await _process(session, chat_id, new, earlier, open_items, users, by_name, owner)
    await session.commit()


async def _process(session, chat_id, new, earlier, open_items, users, by_name, owner) -> None:
    tz = ZoneInfo((owner or next(iter(users.values()), None)).timezone if (owner or users) else "UTC")
    lines = [f"（之前）{m.sender_name or '某人'}：{m.text}" for m in earlier]
    lines += [f"[{i}] {m.created_at.astimezone(tz):%m-%d %H:%M} {m.sender_name or '某人'}：{m.text}" for i, m in enumerate(new)]
    pending = "\n".join(f"[#{i.id}] {i.title}" + (f"（{i.summary}）" if i.summary else "") for i in open_items)
    if owner:
        # 私聊只有两个人：告诉模型是谁和谁，否则“你帮我……”里的“你”对应不到人名
        other = next((m.chat_name for m in new + earlier if m.chat_name), "") .removeprefix("和 ").removesuffix(" 的私聊") or "对方"
        kind = f"{owner.name} 和 {other} 的私聊（只有这两个人）"
    else:
        kind = "群聊"
    try:
        result = await complete_structured(
            CHAT_TASKS_SYSTEM,
            f"<now>{datetime.now(tz):%Y-%m-%d %H:%M %A}</now>\n<chat kind=\"{kind}\">\n" + "\n".join(lines) + "\n</chat>"
            + (f"\n\n<open>\n{pending}\n</open>" if pending else ""),
            TASKS_TOOL,
        )
    except Exception:
        logger.exception("提取聊天待办失败 %s", chat_id)
        return
    by_id = {i.id: i for i in open_items}
    for change in result.get("progress") or []:
        item = by_id.get(change.get("item_id"))
        if item is not None and item.status == "open":
            await apply_progress(session, item, change, next((u for u in users.values() if u.id == item.user_id), None))
    where = "私聊" if owner else "群里"
    for task in result.get("tasks") or []:
        if not 0 <= task["message_ref"] < len(new):
            continue
        source = new[task["message_ref"]]
        mentioned = {x.get("name"): x.get("open_id") for x in source.mentions}
        assignee = users.get(mentioned.get(task["assignee"])) or by_name.get(task["assignee"])
        requester = users.get(source.sender_open_id) or by_name.get(task["requester"])
        if owner is not None:
            # 私聊只有两个人：只给读取它的这位用户建事项，另一方即使是 Relay 用户也不替他建
            assignee = owner if assignee == owner else None
            requester = owner if requester == owner else None
        due = items._due(task["due"], assignee or requester) if (assignee or requester) else None
        chat_name = next((m.chat_name for m in new + earlier if m.chat_name), None) if owner is None else None
        if assignee and assignee != requester:
            await items.upsert(
                session, assignee, f"chat:{source.message_id}:{assignee.id}", None, silent=False,
                kind="request", owner="me", title=f"{task['requester']} 让你：{task['task']}",
                summary=f"「{source.text[:200]}」", next_step=f"完成后在{where}回复对方",
                url=chat_link(chat_id), due_at=due,
                facets={"people": [task["requester"]], "open_ids": [source.sender_open_id], "chat": chat_name},
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
                facets={"people": [task["assignee"]], "chat": chat_name},
            )


async def apply_progress(session: AsyncSession, item: FollowUp, change: dict, user: User | None) -> None:
    """对方有了实质进展：办完了就结束；答应了时间就改成到那个时间再核实。两种都告诉他。"""
    evidence = change.get("evidence") or ""
    if change.get("verdict") == "done":
        items.close(item, "done", f"有了结果：{evidence}".rstrip("："))
        note = f"{item.title.removeprefix('等 ')} —— 已有结果：{evidence}"
    else:
        due = None
        if change.get("due"):
            try:
                due = datetime.fromisoformat(change["due"])
                if due.tzinfo is None and user is not None:
                    due = due.replace(tzinfo=ZoneInfo(user.timezone))
            except ValueError:
                due = None
        item.summary = f"对方答应了：{evidence}"
        if due is not None:
            item.due_at, item.remind_at = due, due
            item.next_step = "Relay 会在答应的时间核实有没有完成"
        item.updated_at = datetime.now(UTC)
        note = f"{item.title.removeprefix('等 ')} —— 对方答应了：{evidence}"
    if user is not None and item.owner == "others":
        await add_signal(session, user, "chat", f"progress:{item.id}:{change.get('verdict')}:{int(datetime.now(UTC).timestamp())}",
                         kind="chat_result", title=note, payload={"item_id": item.id}, occurred_at=datetime.now(UTC), status="result")


async def related(session: AsyncSession, keywords: list[str], limit: int = 5) -> list[ChatMessage]:
    """起草回复时找相关的群聊背景（只用群消息：私聊属于个人，不给任何人当背景）。"""
    words = [w for w in keywords if len(w) >= 2][:4]
    if not words:
        return []
    result = await session.execute(
        select(ChatMessage).where(ChatMessage.owner_user_id.is_(None), or_(*[ChatMessage.text.ilike(f"%{w}%") for w in words]))
        .order_by(ChatMessage.created_at.desc()).limit(limit)
    )
    return list(result.scalars())
