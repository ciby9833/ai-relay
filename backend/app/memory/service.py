"""长期记忆。

profile：关于用户的稳定事实（岗位、偏好、在跟的项目），每轮对话都会带上。
episodic：某次发生的具体事情，按与当前消息的语义相似度召回。
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import embed, embedding_model
from app.models import Memory

KINDS = ("profile", "episodic")
PROFILE_LIMIT = 50


async def list_memories(
    session: AsyncSession, user_id: uuid.UUID, kind: str | None = None, limit: int = 200
) -> list[Memory]:
    query = select(Memory).where(Memory.user_id == user_id)
    if kind:
        query = query.where(Memory.kind == kind)
    result = await session.execute(query.order_by(Memory.id.desc()).limit(limit))
    return list(result.scalars())


async def add_memory(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: str,
    content: str,
    conversation_id: uuid.UUID | None = None,
) -> Memory:
    content = content.strip()
    existing = await session.execute(
        select(Memory).where(Memory.user_id == user_id, Memory.content == content)
    )
    if memory := existing.scalars().first():
        return memory
    vector = await embed(content)
    memory = Memory(
        user_id=user_id,
        kind=kind,
        content=content,
        embedding=vector,
        embedding_model=embedding_model() if vector else None,
        source_conversation_id=conversation_id,
    )
    session.add(memory)
    await session.flush()
    return memory


async def delete_memory(session: AsyncSession, user_id: uuid.UUID, memory_id: int) -> bool:
    result = await session.execute(
        delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    return result.rowcount > 0


async def search_memories(
    session: AsyncSession, user_id: uuid.UUID, query: str, kind: str | None = None, limit: int = 5
) -> list[Memory]:
    """语义检索；没有可用的 embedding 时退化为返回最近的几条。"""
    vector = await embed(query) if query.strip() else None
    if vector is None:
        return await list_memories(session, user_id, kind, limit)
    statement = select(Memory).where(
        Memory.user_id == user_id,
        Memory.embedding.is_not(None),
        Memory.embedding_model == embedding_model(),
    )
    if kind:
        statement = statement.where(Memory.kind == kind)
    result = await session.execute(
        statement.order_by(Memory.embedding.cosine_distance(vector)).limit(limit)
    )
    return list(result.scalars())
