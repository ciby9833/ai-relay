"""从群聊里提取要处理的事：谁让谁做什么、什么时候要。

群消息本身不推送。提取出来的事归到对应用户的跟进看板上：
    别人让 Relay 用户做事 → 他的“等你”
    Relay 用户让别人做事 → 他的“等别人”（到期没动静会提醒）
"""

import logging
import re
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
MAX_ATTEMPTS = 3
_failures: dict[tuple, int] = {}  # 每段会话连续失败的次数（进程内；重启后重新计数）

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
                        "basis": {"type": "string", "enum": ["commitment", "open_request", "blocking_wait", "asked_to_watch", "unclear"],
                                  "description": "为什么值得跟：commitment 明确答应了要做；open_request 明确的请求、要交付物/决定/答复、对方在等、还没解决；"
                                                 "blocking_wait 他在等的东西影响他接下来的工作；asked_to_watch 他明确说要盯着/提醒他；"
                                                 "unclear 像是请求但前后文不够，拿不准"},
                        "why": {"type": "string", "description": "一句话依据：谁说了什么、为什么要跟（给用户看，不写消息编号）"},
                    },
                    "required": ["message_ref", "requester", "assignee", "task", "due", "basis", "why"],
                    "additionalProperties": False,
                },
            },
            "asks": {
                "type": "array",
                "description": "新消息里在问某个人、需要他亲自回答的话（不是让他办事）；答复他自己问题的、抄送、致谢不算",
                "items": {
                    "type": "object",
                    "properties": {
                        "message_ref": {"type": "integer"},
                        "to": {"type": "string", "description": "被问的人名"},
                        "question": {"type": "string", "description": "问的是什么，一句话"},
                    },
                    "required": ["message_ref", "to", "question"],
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
                        "verdict": {"type": "string", "enum": ["done", "committed", "track", "same"],
                                    "description": "done=已经办完/给出了这件事要的结果（或者不需要了）；committed=答应了、给了完成时间但还没办完；"
                                                   "track=只用于标了（候选）的事：新消息表明这确实是要跟进的事；"
                                                   "same=又提了一次这件事（例如邮件里提过、现在在聊天里重复），没有新进展"},
                        "evidence": {"type": "string", "description": "哪条消息、说了什么，一句话"},
                        "due": {"type": "string", "description": "committed 时：答应的完成时间，ISO 8601（按 <now> 换算）；说不出具体时间就留空"},
                    },
                    "required": ["item_id", "verdict", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["tasks", "asks", "progress"],
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
    # 候选 2 天没有新证据：作废，不打扰任何人
    await session.execute(update(FollowUp).where(FollowUp.status == items.CANDIDATE, FollowUp.remind_at < datetime.now(UTC)).values(
        status=items.EXPIRED, resolution="候选：没有新进展，没有进入跟踪", closed_at=datetime.now(UTC)))
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
        open_query = select(FollowUp).where(FollowUp.status.in_((items.OPEN, items.CANDIDATE)), FollowUp.url == chat_link(chat_id),
                                            or_(FollowUp.key.like("chat:%"), FollowUp.key.like("mention:%")))
        if owner is not None:
            open_query = open_query.where(FollowUp.user_id == owner.id)
        open_items = list((await session.execute(open_query)).scalars())
        involved = {m.sender_open_id for m in new} | {x.get("open_id") for m in new for x in m.mentions}
        if owner is None and not involved & set(users) and not open_items:
            continue  # 群里这段新消息和任何 Relay 用户都无关，也没有在等这个群里的答复
        # 同一件事可能是在别的渠道提起的（邮件里要他确认的事，私聊里补充进展）：同一个人、说到同样的事的未结事项也拿来对照
        text = "\n".join(m.text for m in new)
        speakers = {m.sender_name for m in new if m.sender_name} | {m.chat_name.removeprefix("和 ").removesuffix(" 的私聊")
                                                                   for m in new if owner and m.chat_name}
        for person in ([owner] if owner else [u for u in users.values() if u.feishu_open_id in involved]):
            open_items += await items.related_open_items(session, person, text, speakers - {person.name},
                                                         exclude={i.id for i in open_items}, limit=3)
        await _process(session, chat_id, new, earlier, open_items, users, by_name, owner)
    await session.commit()


async def _process(session, chat_id, new, earlier, open_items, users, by_name, owner) -> None:
    tz = ZoneInfo((owner or next(iter(users.values()), None)).timezone if (owner or users) else "UTC")
    replied = await _parents(session, earlier + new)
    lines = [f"（之前）{m.sender_name or '某人'}{replied.get(m.message_id, '')}：{m.text}" for m in earlier]
    lines += [f"[{i}] {m.created_at.astimezone(tz):%m-%d %H:%M} {m.sender_name or '某人'}{replied.get(m.message_id, '')}：{m.text}"
              for i, m in enumerate(new)]
    here = chat_link(chat_id)
    pending = "\n".join(f"[#{i.id}]" + ("（候选）" if i.status == items.CANDIDATE else "")
                        + ("" if i.url == here else f"（来自{items.channel_of(i)}）") + f" {i.title}"
                        + (f"（{i.summary}）" if i.summary else "") for i in open_items)
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
        # 模型出错（限流、超时）不能把这段消息丢掉：标回未处理，下一轮再试；同一段连续失败几次才放弃
        key = (chat_id, owner.id if owner else None)
        _failures[key] = _failures.get(key, 0) + 1
        if _failures[key] < MAX_ATTEMPTS:
            for message in new:
                message.processed = False
            logger.warning("提取聊天待办失败（第 %s 次，下一轮重试）%s", _failures[key], chat_id, exc_info=True)
        else:
            _failures.pop(key, None)
            logger.exception("提取聊天待办连续失败 %s 次，放弃这段消息 %s", MAX_ATTEMPTS, chat_id)
        return
    _failures.pop((chat_id, owner.id if owner else None), None)
    by_id = {i.id: i for i in open_items}
    changes = result.get("progress") or []
    for change in changes:
        item = by_id.get(change.get("item_id"))
        if item is not None and item.status == items.CANDIDATE:
            settle_candidate(item, change)
        elif item is not None and item.status == "open" and change.get("verdict") == "same":
            # 又提了一次同一件事（换个渠道、没有新进展）：只记下依据，不另建
            items.add_evidence(item, "私聊" if owner else "群聊", clean_evidence(change.get("evidence") or ""))
            item.updated_at = datetime.now(UTC)
        elif item is not None and item.status == "open" and change.get("verdict") != "track":
            await apply_progress(session, item, change, next((u for u in users.values() if u.id == item.user_id), None))
    # 有一件办完了：同一个会话里、同一个人的其他未结事项，再单独对照这些新消息判断一次。
    # 一次回复常常同时回应了好几件内容相近的事，模型一起判断时容易只认其中一件，剩下的就一直挂着
    closed = [by_id[c["item_id"]] for c in changes if c.get("verdict") == "done" and c.get("item_id") in by_id
              and by_id[c["item_id"]].status != items.EXPIRED]
    judged = {c.get("item_id") for c in changes}
    siblings = [i for i in open_items if i.status == "open" and i.id not in judged
                and any(_counterpart(i) == _counterpart(x) and i.user_id == x.user_id for x in closed)]
    if siblings:
        try:
            again = await complete_structured(
                CHAT_TASKS_SYSTEM,
                f"<now>{datetime.now(tz):%Y-%m-%d %H:%M %A}</now>\n<chat kind=\"{kind}\">\n" + "\n".join(lines) + "\n</chat>"
                + "\n\n<open>\n" + "\n".join(f"[#{i.id}] {i.title}" + (f"（{i.summary}）" if i.summary else "") for i in siblings)
                + "\n</open>\n\n这次只判断 <open> 里这几件事的进展，不用提取新的待办（tasks 给空列表）。",
                TASKS_TOOL,
            )
        except Exception:
            logger.exception("复核相关事项失败 %s", chat_id)
            again = {}
        sibling_ids = {i.id: i for i in siblings}
        for change in again.get("progress") or []:
            item = sibling_ids.get(change.get("item_id"))
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
        # 拿不准的先作候选：不上看板、不推送；同一段对话有新消息时再判断，2 天没有新证据就作废
        candidate = task.get("basis") == "unclear"
        why = clean_evidence(task.get("why") or "")
        private = owner is not None
        chat_name = next((m.chat_name for m in new + earlier if m.chat_name), None) if owner is None else None
        if assignee and assignee != requester and not await _merge_same_ask(
                session, assignee, chat_id, "me", task["requester"], task["task"], source.text, candidate):
            item = await items.upsert(
                session, assignee, f"chat:{source.message_id}:{assignee.id}", None, silent=candidate,
                kind="request", owner="me", title=f"{task['requester']} 让你：{task['task']}",
                summary=f"「{source.text[:200]}」", next_step=f"完成后在{where}回复对方", recommendation=why or None,
                url=chat_link(chat_id), due_at=due,
                facets={"people": [task["requester"]], "open_ids": [source.sender_open_id], "chat": chat_name,
                        "private": private, "basis": task.get("basis")},
            )
            if candidate:
                _as_candidate(item)
            else:
                # 同一条消息已经建成待办，不再单独提醒“@你没回”
                await session.execute(
                    update(Signal).where(Signal.user_id == assignee.id, Signal.kind == "mention",
                                         Signal.external_id == source.message_id).values(status="done")
                )
        if requester and requester != assignee and not await _merge_same_ask(
                session, requester, chat_id, "others", task["assignee"], task["task"], source.text, candidate):
            item = await items.upsert(
                session, requester, f"chat:{source.message_id}:{requester.id}", None, silent=True,
                kind="waiting", owner="others", title=f"等 {task['assignee']}：{task['task']}",
                summary=f"「{source.text[:200]}」", waiting_on=task["assignee"], recommendation=why or None,
                next_step="Relay 会在到期时提醒你跟进", url=chat_link(chat_id),
                due_at=due, remind_at=due or datetime.now(UTC) + WAITING_DEFAULT,
                facets={"people": [task["assignee"]], "chat": chat_name, "private": private, "basis": task.get("basis")},
            )
            if candidate:
                _as_candidate(item)

    if owner is None:
        await _settle_mentions(session, new, result, users, by_name)


async def _parents(session, messages: list[ChatMessage]) -> dict[str, str]:
    """话题回复 / 引用回复：每条消息前面标上它回复的是谁的哪句话。"""
    ids = {m.parent_message_id for m in messages if m.parent_message_id}
    if not ids:
        return {}
    parents = {p.message_id: p for p in (await session.execute(select(ChatMessage).where(ChatMessage.message_id.in_(ids)))).scalars()}
    return {m.message_id: f"（回复 {parents[m.parent_message_id].sender_name or '某人'}：{parents[m.parent_message_id].text[:60]}）"
            for m in messages if m.parent_message_id in parents}


async def _settle_mentions(session, new: list[ChatMessage], result: dict, users: dict, by_name: dict) -> None:
    """群里@了某位用户：读过上下文之后再决定要不要等他回。

    以前只要@了他、两小时内他没在群里说话，就提醒“@你的消息还没回”——可那条@常常是在回答他自己刚问的问题，
    或者只是抄送。现在：被判为在问他、要他回答的，才继续盯着（并记下问的是什么）；建成了待办的，由待办跟进；
    其余的（答复、抄送、致谢……）直接结束，不再提醒。模型没给出判断时（出错）保持原来的做法。
    """
    asked: dict[tuple[str, str], str] = {}
    for ask in result.get("asks") or []:
        if 0 <= ask.get("message_ref", -1) < len(new):
            source = new[ask["message_ref"]]
            mentioned = {x.get("name"): x.get("open_id") for x in source.mentions}
            target = users.get(mentioned.get(ask["to"])) or by_name.get(ask["to"])
            if target is not None:
                asked[(source.message_id, target.feishu_open_id)] = ask["question"]
    for message in new:
        for mention in message.mentions or []:
            user = users.get(mention.get("open_id"))
            if user is None:
                continue
            signal = (await session.execute(select(Signal).where(
                Signal.user_id == user.id, Signal.kind == "mention", Signal.external_id == message.message_id,
                Signal.status == "watching"))).scalars().first()
            if signal is None:
                continue  # 已经建成待办（见上）或已经结束
            question = asked.get((message.message_id, user.feishu_open_id))
            if question:
                signal.payload = {**(signal.payload or {}), "ask": question}
            else:
                signal.status = "done"
                signal.payload = {**(signal.payload or {}), "settled": "读过上下文：不需要他回复（答复、抄送或已有结论）"}


MERGE_WINDOW = timedelta(minutes=10)


def _counterpart(item: FollowUp) -> str | None:
    """这件事的另一方：等别人的是在等谁，等他的是谁提的。"""
    return item.waiting_on if item.owner == "others" else ((item.facets or {}).get("people") or [None])[0]


CANDIDATE_TTL = timedelta(days=2)


def _as_candidate(item: FollowUp) -> None:
    item.status, item.announced_at = items.CANDIDATE, datetime.now(UTC)
    item.remind_at = datetime.now(UTC) + CANDIDATE_TTL  # 候选的作废时间


def settle_candidate(item: FollowUp, change: dict) -> None:
    """候选有了新证据：确实要跟（或对方答应了）→ 转成正式事项，进入看板和提醒；已经有结论 → 安静作废。"""
    verdict = change.get("verdict")
    now = datetime.now(UTC)
    if verdict in ("track", "committed"):
        item.status, item.announced_at, item.updated_at = items.OPEN, None, now
        item.remind_at = (item.due_at or now + WAITING_DEFAULT) if item.owner == "others" else None
        evidence = clean_evidence(change.get("evidence") or "")
        if evidence:
            item.recommendation = evidence
    elif verdict == "done":
        item.status, item.resolution, item.closed_at, item.updated_at = items.EXPIRED, "候选：已有结论，没有进入跟踪", now, now


async def _merge_same_ask(session, user: User, chat_id: str, owner: str, counterpart: str, task: str, text: str,
                          candidate: bool = False) -> bool:
    """同一个会话里、同一对人之间，10 分钟内连着提的要求，并进刚建的那件事，而不是拆成好几件。

    拆开的后果：对方一次回复把几件都答了，往往只有其中一件被判为办完，剩下的永远挂着（例如“三段码”那两件）。
    """
    recent = (await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == (items.CANDIDATE if candidate else items.OPEN),
                               FollowUp.owner == owner,
                               FollowUp.url == chat_link(chat_id), FollowUp.key.like("chat:%"),
                               FollowUp.created_at > datetime.now(UTC) - MERGE_WINDOW)
        .order_by(FollowUp.id.desc())
    )).scalars().all()
    same = next((i for i in recent
                 if (i.waiting_on if owner == "others" else ((i.facets or {}).get("people") or [None])[0]) == counterpart), None)
    if same is None:
        return False
    if task not in same.title:
        same.title = f"{same.title}；{task}"[:500]
    same.summary = f"{same.summary or ''}\n「{text[:200]}」".strip()[:2000]
    same.updated_at = datetime.now(UTC)
    return True


def clean_evidence(text: str) -> str:
    """模型有时把消息编号写进依据（“[0][1] Veigar 说……”）：给人看的时候去掉。"""
    text = re.sub(r"(消息)?\s*\[\d+\](\s*[-–~、,，]\s*\[\d+\])*\s*(中)?", "", text or "")
    return re.sub(r"\s{2,}", " ", text).strip(" ：:，,")


async def apply_progress(session: AsyncSession, item: FollowUp, change: dict, user: User | None) -> None:
    """对方有了实质进展：办完了就结束；答应了时间就改成到那个时间再核实。两种都告诉他。"""
    evidence = clean_evidence(change.get("evidence") or "")
    items.add_evidence(item, "聊天", evidence)
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
        item.summary = f"{'你答应了' if item.owner == 'me' else '对方答应了'}：{evidence}"
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
