"""私聊感知（用户在设置里开启后才运行）：读他和常联系的同事之间的私聊，用来识别待办、判断事情有没有结果。

飞书没有“列出我所有私聊”的接口，只能按人查到“我和他的私聊”（/im/v1/chat_p2p/batch_query）。
所以先找出他常联系的人：群里和他有往来的、给他发审批的、Relay 替他发过消息的、@过他的、同部门的，
每天刷新一次名单；每一轮只取这些私聊里上次之后的新消息。

读到的私聊消息只属于他本人（ChatMessage.owner_user_id），只用于他自己的事项，不会给任何别人当背景。
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
from app.models import ChatMessage, PendingAction, Signal, SourceState, User
from app.sources import im

MAX_CONTACTS = 40
CONTACTS_TTL = timedelta(hours=24)
FIRST_LOOKBACK_HOURS = 24  # 刚开启时只看最近一天，不把历史私聊翻出来


async def contacts(session: AsyncSession, feishu: FeishuClient, user: User) -> list[str]:
    """他常联系的同事（open_id），按往来次数排序。"""
    since = datetime.now(UTC) - timedelta(days=30)
    score: Counter = Counter()
    # 群里和他有往来的人：他发言的群里的其他发言人，以及 @ 过他的人
    mine = select(ChatMessage.chat_id).where(ChatMessage.sender_open_id == user.feishu_open_id, ChatMessage.owner_user_id.is_(None))
    rows = (await session.execute(
        select(ChatMessage.sender_open_id, ChatMessage.mentions, ChatMessage.chat_id).where(
            ChatMessage.owner_user_id.is_(None), ChatMessage.created_at > since,
            or_(ChatMessage.chat_id.in_(mine), ChatMessage.mentions.contains([{"open_id": user.feishu_open_id}])),
        )
    )).all()
    for sender, mentions, _ in rows:
        score[sender] += 1
        if any(m.get("open_id") == user.feishu_open_id for m in mentions or []):
            score[sender] += 3
    # 发给他审批的人、Relay 替他发过消息的人
    signals = (await session.execute(
        select(Signal.payload).where(Signal.user_id == user.id, Signal.kind.in_(["approval_pending", "mention"]), Signal.created_at > since)
    )).scalars().all()
    for payload in signals:
        for open_id in (payload or {}).get("initiators") or []:
            score[open_id] += 3
        if (payload or {}).get("sender_open_id"):
            score[payload["sender_open_id"]] += 3
    sent = (await session.execute(
        select(PendingAction.payload).where(PendingAction.user_id == user.id, PendingAction.kind == "send_chat",
                                            PendingAction.status == "done")
    )).scalars().all()
    for payload in sent:
        if payload.get("receive_id_type") == "open_id":
            score[payload["receive_id"]] += 5
    # 同部门的人（读不到组织架构时跳过）
    try:
        me = (await feishu.user_api(user, "GET", f"/contact/v3/users/{user.feishu_open_id}", params={"user_id_type": "open_id"})).get("user") or {}
        for dept in (me.get("department_ids") or [])[:2]:
            members = (await feishu.user_api(user, "GET", "/contact/v3/users/find_by_department",
                                             params={"department_id": dept, "user_id_type": "open_id", "page_size": 50})).get("items") or []
            for member in members:
                score[member.get("open_id")] += 1
        if me.get("leader_user_id"):
            score[me["leader_user_id"]] += 5
    except FeishuError:
        pass
    score.pop(user.feishu_open_id, None)
    score.pop(None, None)
    return [open_id for open_id, _ in score.most_common(MAX_CONTACTS) if open_id and open_id.startswith("ou_")]


async def chat_ids(feishu: FeishuClient, user: User, open_ids: list[str]) -> dict[str, str]:
    """他和这些人之间的私聊 chat_id（没聊过的人没有）。"""
    found = {}
    for start in range(0, len(open_ids), 20):
        data = await feishu.user_api(user, "POST", "/im/v1/chat_p2p/batch_query", params={"user_id_type": "open_id"},
                                     json={"chatter_ids": open_ids[start:start + 20]})
        for chat in data.get("p2p_chats") or []:
            other = chat["chatter_id2"] if chat.get("chatter_id1") == user.feishu_open_id else chat.get("chatter_id1")
            if other and chat.get("chat_id"):
                found[other] = chat["chat_id"]
    return found


async def sync(session: AsyncSession, feishu: FeishuClient, user: User, state: SourceState) -> int:
    cursor = dict(state.cursor or {})
    now = datetime.now(UTC)
    refreshed = cursor.get("contacts_at")
    if not refreshed or datetime.fromisoformat(refreshed) < now - CONTACTS_TTL or not cursor.get("chats"):
        people = await contacts(session, feishu, user)
        cursor["chats"] = await chat_ids(feishu, user, people)
        cursor["contacts_at"] = now.isoformat()
    seen = dict(cursor.get("seen") or {})  # chat_id → 已读到的最后一条消息时间（ISO）
    created = 0
    for other, chat_id in (cursor.get("chats") or {}).items():
        since = datetime.fromisoformat(seen[chat_id]) if chat_id in seen else now - timedelta(hours=FIRST_LOOKBACK_HOURS)
        hours = max(1, min(336, int((now - since).total_seconds() // 3600) + 1))
        try:
            messages = await im.recent_messages(feishu, user, chat_id, hours=hours, limit=50)
        except FeishuError:
            continue
        newest = since
        for m in messages:
            if m["at"] <= since or m["sender_type"] != "user" or not m.get("message_id"):
                continue
            newest = max(newest, m["at"])
            exists = await session.scalar(select(ChatMessage.id).where(ChatMessage.message_id == m["message_id"]))
            if exists:
                continue
            name = user.name if m["sender"] == user.feishu_open_id else (await feishu.user_name(m["sender"]) or "对方")
            session.add(ChatMessage(
                message_id=m["message_id"], chat_id=chat_id, chat_name=f"和 {await feishu.user_name(other) or '同事'} 的私聊",
                sender_open_id=m["sender"], sender_name=name, text=m["text"][:4000], mentions=m.get("mentions") or [],
                owner_user_id=user.id, created_at=m["at"],
            ))
            created += 1
        seen[chat_id] = newest.isoformat()
    cursor["seen"] = seen
    state.cursor = cursor
    return created
