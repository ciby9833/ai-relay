from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.feishu.client import FeishuClient
from app.models import DEFAULT_TENANT_ID, Tenant, User
from app.security import SESSION_COOKIE, parse_session_token


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    user_id = parse_session_token(token) if token else None
    user = await session.get(User, user_id) if user_id else None
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="未登录")
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=401, detail="工作区已停用")
    return user


async def get_feishu(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> FeishuClient:
    """当前用户所在工作区的飞书客户端；没登录或默认工作区时用服务器配置的那个（旧行为不变）。"""
    default = request.app.state.feishu
    user_id = parse_session_token(token) if token else None
    user = await session.get(User, user_id) if user_id else None
    if user is None or user.tenant_id == DEFAULT_TENANT_ID:
        return default
    from app import tenancy

    client = await tenancy.feishu_for(session, user.tenant_id, getattr(request.app.state, "http", None), fallback=default)
    return client or NoFeishu()


class NoFeishu:
    """工作区没接入飞书：用到飞书的功能时明确报错，而不是用别的公司的飞书应用去做。"""

    def __getattr__(self, name):
        async def unavailable(*args, **kwargs):
            from app.feishu.client import FeishuError

            raise FeishuError("这个工作区还没有接入飞书，请管理员在“工作区设置”里配置")

        return unavailable


SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]
FeishuDep = Annotated[FeishuClient, Depends(get_feishu)]
