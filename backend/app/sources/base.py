"""数据源公共部分：把采集到的事统一写成 Signal。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Signal, User


def ts(seconds: str | int | None) -> datetime | None:
    if seconds in (None, "", "0", 0):
        return None
    return datetime.fromtimestamp(int(seconds), UTC)


async def add_signal(
    session: AsyncSession, user: User, source: str, external_id: str, **fields
) -> bool:
    """写入一条信号；已存在（同一用户、来源、external_id）时不动，返回是否新建。"""
    result = await session.execute(
        insert(Signal)
        .values(user_id=user.id, source=source, external_id=external_id, **fields)
        .on_conflict_do_nothing(constraint="uq_signals_user_source_ext")
    )
    return bool(result.rowcount)


async def existing_ids(session: AsyncSession, user: User, source: str, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    result = await session.execute(
        select(Signal.external_id).where(
            Signal.user_id == user.id, Signal.source == source, Signal.external_id.in_(ids)
        )
    )
    return set(result.scalars())
