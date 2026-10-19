import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import get_settings
from app.deps import FeishuDep, SessionDep, UserDep
from app.feishu.client import FeishuError
from app.models import User
from app.sources import people
from app.security import OAUTH_STATE_COOKIE, SESSION_COOKIE, create_session_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id),
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _user_json(user: User) -> dict:
    return {
        "is_admin": user.is_admin,
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "timezone": user.timezone,
    }


def _login_failed(reason: str) -> RedirectResponse:
    response = RedirectResponse(f"{get_settings().frontend_url}/?login_error={reason}")
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


@router.get("/config")
async def auth_config():
    return {"dev_login": get_settings().dev_login_enabled}


@router.get("/feishu/login")
async def feishu_login(feishu: FeishuDep):
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(feishu.authorize_url(state, await feishu.granted_user_scopes()))
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/feishu/callback")
async def feishu_callback(
    session: SessionDep,
    feishu: FeishuDep,
    code: str | None = None,
    state: str | None = None,
    saved_state: Annotated[str | None, Cookie(alias=OAUTH_STATE_COOKIE)] = None,
):
    settings = get_settings()
    if not code:
        return _login_failed("denied")
    if not state or not saved_state or not secrets.compare_digest(state, saved_state):
        return _login_failed("state")
    try:
        token_data = await feishu.exchange_code(code)
        info = await feishu.user_info(token_data["access_token"])
    except FeishuError as exc:
        logger.warning("飞书登录失败: %s", exc)
        return _login_failed("feishu")

    if not info.get("open_id"):
        return _login_failed("feishu")
    if not settings.feishu_tenant_key or info.get("tenant_key") != settings.feishu_tenant_key:
        logger.warning("拒绝了其他租户的登录: %s", info.get("tenant_key"))
        return _login_failed("tenant")

    result = await session.execute(select(User).where(User.feishu_open_id == info["open_id"]))
    user = result.scalars().first()
    if user is None:
        user = User(feishu_open_id=info["open_id"], timezone=settings.default_timezone, name="")
        session.add(user)
    user.name = info.get("name") or info.get("en_name") or "飞书用户"
    user.email = info.get("enterprise_email") or info.get("email") or None
    user.avatar_url = info.get("avatar_url")
    user.feishu_union_id = info.get("union_id")
    user.feishu_user_id = info.get("user_id")
    user.tenant_key = info.get("tenant_key")
    user.last_login_at = datetime.now(UTC)
    feishu.store_user_token(user, token_data)
    # 第一位用飞书登录的用户成为管理员（可以管理业务系统接入）
    if not await session.scalar(select(User.id).where(User.is_admin).limit(1)):
        user.is_admin = True
    await session.flush()
    await people.remember(session, [(user.feishu_open_id, user.name, "user")])
    await session.commit()

    response = RedirectResponse(settings.frontend_url)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    _set_session_cookie(response, user)
    return response


@router.post("/dev-login")
async def dev_login(session: SessionDep, response: Response):
    """仅本地调试：免飞书登录。生产环境或未显式开启时不存在。"""
    settings = get_settings()
    if not settings.dev_login_enabled:
        raise HTTPException(status_code=404)
    result = await session.execute(select(User).where(User.feishu_open_id == "dev-user"))
    user = result.scalars().first()
    if user is None:
        user = User(feishu_open_id="dev-user", name="本地调试", timezone=settings.default_timezone)
        session.add(user)
        await session.commit()
    _set_session_cookie(response, user)
    return _user_json(user)


@router.get("/me")
async def me(user: UserDep, feishu: FeishuDep):
    data = _user_json(user)
    # 应用在飞书后台新开通了权限，但他的登录还没包含：提示重新登录一次（新权限只在登录时申请）
    try:
        granted = set(await feishu.granted_user_scopes())
    except FeishuError:
        granted = set()
    have = set((user.feishu_scopes or "").split())
    data["missing_scopes"] = sorted(granted - have) if have else []
    return data


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}
