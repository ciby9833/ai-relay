"""按用户加锁：worker 里“每个用户的主流程”和“聊天内容提取”现在并行跑，同一个用户的事项不能被两边同时改。

- 主流程：用一条专门的连接持有会话级锁（主流程中间会多次提交，普通会话的连接每次提交后会还回连接池）。
- 聊天提取：在本批次的事务里试着拿事务级锁；拿不到说明这个人的主流程正在跑，这批先跳过（消息保持未处理，下一轮再来）。
两种锁在 Postgres 里是同一个锁空间，会互相排斥。
"""

import hashlib
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine

NAMESPACE = 0x52454C  # "REL"：避免和别的 advisory lock 撞号


def user_key(user_id: uuid.UUID) -> int:
    digest = hashlib.sha1(f"{NAMESPACE}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@asynccontextmanager
async def hold_user(user_id: uuid.UUID):
    """拿到就 yield True（结束时释放）；别人正拿着就 yield False，不等待。"""
    async with engine.connect() as conn:
        got = bool(await conn.scalar(select(func.pg_try_advisory_lock(user_key(user_id)))))
        try:
            yield got
        finally:
            if got:
                await conn.execute(select(func.pg_advisory_unlock(user_key(user_id))))
                await conn.commit()


async def try_users_in_transaction(session: AsyncSession, user_ids) -> bool:
    """在当前事务里给这些用户加锁（按固定顺序，避免互相等待）；有一个拿不到就返回 False。"""
    for user_id in sorted({u for u in user_ids if u}, key=str):
        if not await session.scalar(select(func.pg_try_advisory_xact_lock(user_key(user_id)))):
            return False
    return True
