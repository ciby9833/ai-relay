"""主线对话：每个用户一条，网页首页和飞书私聊共用。Relay 的主动发言也写在这里。"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine
from app.models import Conversation, Message, User


class ConversationBusy(Exception):
    """用户正在这条对话里和 Relay 说话，主动发言稍后再发。"""


def _lock_key(conversation_id: uuid.UUID):
    return func.hashtextextended(str(conversation_id), 0)


@asynccontextmanager
async def turn_lock(conversation_id: uuid.UUID):
    """一轮对话期间持有的跨进程锁（Postgres advisory lock，占用一条独立连接）。

    一轮对话会分几个事务写入，期间 worker 的主动发言不能插进来，否则这一轮会被拆散。
    """
    async with engine.connect() as connection:
        await connection.execute(select(func.pg_advisory_lock(_lock_key(conversation_id))))
        try:
            yield
        finally:
            await connection.execute(select(func.pg_advisory_unlock(_lock_key(conversation_id))))
            await connection.commit()


async def home_conversation(session: AsyncSession, user: User) -> Conversation:
    result = await session.execute(
        select(Conversation).where(Conversation.user_id == user.id, Conversation.channel == "home")
    )
    conversation = result.scalars().first()
    if conversation is None:
        conversation = Conversation(user_id=user.id, channel="home", title="Relay")
        session.add(conversation)
        await session.flush()
    return conversation


async def post(
    session: AsyncSession, user: User, *, event: str, text: str, cards: list[dict] | None = None
) -> Message:
    """Relay 主动发言：先写一条隐藏的“事件”消息说明起因，再写助手消息。

    事件消息让对话保持“用户/助手”交替，也让模型在用户接着追问时知道这条发言从何而来。
    两条在同一个事务里写入，历史排序时始终相邻。
    """
    conversation = await home_conversation(session, user)
    # 事务级锁：拿不到说明用户正在对话，这次先不发，留到下一轮
    if not await session.scalar(select(func.pg_try_advisory_xact_lock(_lock_key(conversation.id)))):
        raise ConversationBusy()
    session.add(
        Message(
            conversation_id=conversation.id, role="user",
            content=[{"type": "text", "text": f"<event>{event}</event>", "meta": "event"}],
        )
    )
    message = Message(
        conversation_id=conversation.id, role="assistant",
        content=[{"type": "text", "text": text}] + [{"type": "card", "card": c} for c in cards or []],
    )
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    return message
