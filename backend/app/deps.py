from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.feishu.client import FeishuClient
from app.models import User
from app.security import SESSION_COOKIE, parse_session_token


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_feishu(request: Request) -> FeishuClient:
    return request.app.state.feishu


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    user_id = parse_session_token(token) if token else None
    user = await session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]
FeishuDep = Annotated[FeishuClient, Depends(get_feishu)]
