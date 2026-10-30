import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated

import uuid

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import get_settings
from app.deps import FeishuDep, SessionDep, UserDep
from app.feishu.client import FeishuError
from app import tenancy
from app.models import DEFAULT_TENANT_ID, Account, Tenant, User
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


def _user_json(user: User, tenant: Tenant | None = None, account: Account | None = None, workspaces: int = 1) -> dict:
    return {
        "is_admin": user.is_admin,
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "timezone": user.timezone,
        "role": user.role,
        "tenant": {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug} if tenant else None,
        "has_password": bool(account and account.password_hash),
        "login_email": account.email if account else None,
        "feishu_linked": bool(user.feishu_open_id),
        "workspaces": workspaces,
    }


async def _describe(session, user: User) -> dict:
    tenant = await session.get(Tenant, user.tenant_id)
    account = await session.get(Account, user.account_id) if user.account_id else None
    count = len(await tenancy.memberships(session, account.id)) if account else 1
    return _user_json(user, tenant, account, count)


def _login_failed(reason: str) -> RedirectResponse:
    response = RedirectResponse(f"{get_settings().frontend_url}/?login_error={reason}")
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


@router.get("/config")
async def auth_config():
    settings = get_settings()
    return {"dev_login": settings.dev_login_enabled, "signup": settings.allow_signup, "feishu": bool(settings.feishu_app_id)}


async def _workspace_feishu(session, request: Request, slug: str | None):
    """飞书登录走哪个工作区的飞书应用：不指定就是默认工作区（旧的登录入口不变）。"""
    tenant_id = DEFAULT_TENANT_ID
    if slug:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == slug, Tenant.status == "active"))).scalars().first()
        if tenant is None:
            return None, None
        tenant_id = tenant.id
    client = await tenancy.feishu_for(session, tenant_id, getattr(request.app.state, "http", None), fallback=request.app.state.feishu)
    return tenant_id, client


@router.get("/feishu/login")
async def feishu_login(request: Request, session: SessionDep, workspace: str | None = None):
    tenant_id, feishu = await _workspace_feishu(session, request, workspace)
    if feishu is None:
        return _login_failed("no_feishu")
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(feishu.authorize_url(state, await feishu.granted_user_scopes()))
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        f"{state}.{tenant_id}",  # 回调时据此知道是哪个工作区的飞书应用
        max_age=600,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/feishu/callback")
async def feishu_callback(
    request: Request,
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    saved_state: Annotated[str | None, Cookie(alias=OAUTH_STATE_COOKIE)] = None,
):
    settings = get_settings()
    if not code:
        return _login_failed("denied")
    saved, _, tenant_part = (saved_state or "").partition(".")
    if not state or not saved or not secrets.compare_digest(state, saved):
        return _login_failed("state")
    try:
        tenant_id = uuid.UUID(tenant_part) if tenant_part else DEFAULT_TENANT_ID
    except ValueError:
        return _login_failed("state")
    feishu = await tenancy.feishu_for(session, tenant_id, getattr(request.app.state, "http", None), fallback=request.app.state.feishu)
    if feishu is None:
        return _login_failed("no_feishu")
    try:
        token_data = await feishu.exchange_code(code)
        info = await feishu.user_info(token_data["access_token"])
    except FeishuError as exc:
        logger.warning("飞书登录失败: %s", exc)
        return _login_failed("feishu")

    if not info.get("open_id"):
        return _login_failed("feishu")
    # 只接受这个工作区绑定的那家飞书企业的账号
    expected = feishu.settings.feishu_tenant_key
    if not expected or info.get("tenant_key") != expected:
        logger.warning("拒绝了其他租户的登录: %s", info.get("tenant_key"))
        return _login_failed("tenant")

    result = await session.execute(select(User).where(User.feishu_open_id == info["open_id"]))
    user = result.scalars().first()
    if user is not None and user.tenant_id != tenant_id:
        return _login_failed("tenant")
    if user is not None and user.status != "active":
        return _login_failed("deactivated")
    if user is None:
        user = User(tenant_id=tenant_id, feishu_open_id=info["open_id"], timezone=settings.default_timezone, name="")
        session.add(user)
    user.name = info.get("name") or info.get("en_name") or "飞书用户"
    user.email = info.get("enterprise_email") or info.get("email") or None
    user.avatar_url = info.get("avatar_url")
    user.feishu_union_id = info.get("union_id")
    user.feishu_user_id = info.get("user_id")
    user.tenant_key = info.get("tenant_key")
    user.last_login_at = datetime.now(UTC)
    feishu.store_user_token(user, token_data)
    # 工作区的第一位成员成为所有者（可以管理成员、接入和业务系统）
    if not await session.scalar(select(User.id).where(User.tenant_id == tenant_id, User.role == "owner", User.id != user.id).limit(1)) \
            and not user.is_admin:
        tenancy.set_role(user, "owner")
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
    return await _describe(session, user)


@router.get("/me")
async def me(session: SessionDep, user: UserDep, feishu: FeishuDep):
    data = await _describe(session, user)
    # 应用在飞书后台新开通了权限，但他的登录还没包含：提示重新登录一次（新权限只在登录时申请）
    try:
        granted = set(await feishu.granted_user_scopes()) if user.feishu_open_id else set()
    except FeishuError:
        granted = set()
    have = set((user.feishu_scopes or "").split())
    data["missing_scopes"] = sorted(granted - have) if have else []
    return data


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


# ---------- 邮箱 + 密码登录、工作区 ----------


class LoginBody(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)
    tenant_id: uuid.UUID | None = None


@router.post("/login")
async def password_login(body: LoginBody, session: SessionDep, response: Response):
    """邮箱 + 密码登录。账号加入了多个工作区时，没指定就返回工作区列表让他选。"""
    try:
        email = tenancy.normalize_email(body.email)
    except tenancy.TenancyError:
        raise HTTPException(status_code=400, detail="邮箱或密码不对") from None
    if tenancy.throttled(email):
        raise HTTPException(status_code=429, detail="尝试次数太多，请 15 分钟后再试")
    account = (await session.execute(select(Account).where(Account.email == email))).scalars().first()
    if account is None or account.status != "active" or not tenancy.verify_password(body.password, account.password_hash):
        tenancy.note_failure(email)
        raise HTTPException(status_code=400, detail="邮箱或密码不对")
    joined = await tenancy.memberships(session, account.id)
    if not joined:
        raise HTTPException(status_code=403, detail="这个账号还没有加入任何工作区")
    chosen = [m for m in joined if m[1].id == body.tenant_id] if body.tenant_id else (joined if len(joined) == 1 else [])
    if not chosen:
        return {"choose": [{"tenant_id": str(t.id), "name": t.name, "slug": t.slug} for _, t in joined]}
    user = chosen[0][0]
    account.last_login_at = user.last_login_at = datetime.now(UTC)
    await session.commit()
    _set_session_cookie(response, user)
    return await _describe(session, user)


class SignupBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)
    workspace: str = Field(min_length=1, max_length=100)


@router.post("/signup")
async def signup(body: SignupBody, session: SessionDep, response: Response):
    """新建账号和一个新工作区（自己是所有者）。默认关闭，由 ALLOW_SIGNUP 打开。"""
    if not get_settings().allow_signup:
        raise HTTPException(status_code=404)
    try:
        email = tenancy.normalize_email(body.email)
        if await session.scalar(select(Account.id).where(Account.email == email)):
            raise tenancy.TenancyError("这个邮箱已经注册过，请直接登录")
        account = Account(email=email, name=body.name.strip(), password_hash=tenancy.hash_password(body.password))
        session.add(account)
        await session.flush()
        user = await tenancy.create_workspace(session, account, body.workspace)
    except tenancy.TenancyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    _set_session_cookie(response, user)
    return await _describe(session, user)


@router.get("/workspaces")
async def workspaces(session: SessionDep, user: UserDep):
    """他能切换到的工作区（同一个登录账号加入的）。"""
    if not user.account_id:
        tenant = await session.get(Tenant, user.tenant_id)
        return [{"tenant_id": str(tenant.id), "name": tenant.name, "slug": tenant.slug, "current": True}]
    return [{"tenant_id": str(t.id), "name": t.name, "slug": t.slug, "current": t.id == user.tenant_id}
            for _, t in await tenancy.memberships(session, user.account_id)]


class SwitchBody(BaseModel):
    tenant_id: uuid.UUID


@router.post("/switch")
async def switch(body: SwitchBody, session: SessionDep, user: UserDep, response: Response):
    if not user.account_id:
        raise HTTPException(status_code=400, detail="先给账号设置邮箱和密码，才能加入和切换多个工作区")
    target = next((u for u, t in await tenancy.memberships(session, user.account_id) if t.id == body.tenant_id), None)
    if target is None:
        raise HTTPException(status_code=403, detail="你不是这个工作区的成员")
    _set_session_cookie(response, target)
    return await _describe(session, target)


class PasswordBody(BaseModel):
    password: str = Field(max_length=200)
    current_password: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)


@router.post("/password")
async def set_password(body: PasswordBody, session: SessionDep, user: UserDep):
    """设置或修改登录密码。原来只用飞书登录的成员，在这里建一个登录账号（邮箱 + 密码），之后两种方式都能登录。"""
    try:
        if user.account_id:
            account = await session.get(Account, user.account_id)
            if account.password_hash and not tenancy.verify_password(body.current_password or "", account.password_hash):
                raise tenancy.TenancyError("当前密码不对")
            account.password_hash = tenancy.hash_password(body.password)
        else:
            email = tenancy.normalize_email(body.email or user.email)
            if await session.scalar(select(Account.id).where(Account.email == email)):
                raise tenancy.TenancyError("这个邮箱已经有登录账号：请用那个账号登录后，再由管理员邀请加入")
            account = Account(email=email, name=user.name, password_hash=tenancy.hash_password(body.password))
            session.add(account)
            await session.flush()
            user.account_id = account.id
    except tenancy.TenancyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return await _describe(session, user)


@router.get("/invitations/{token}")
async def invitation_info(token: str, session: SessionDep):
    try:
        invitation = await tenancy.find_invitation(session, token)
    except tenancy.TenancyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tenant = await session.get(Tenant, invitation.tenant_id)
    has_account = bool(await session.scalar(select(Account.id).where(Account.email == invitation.email)))
    return {"workspace": tenant.name, "email": invitation.email, "role": invitation.role, "has_account": has_account}


class AcceptBody(BaseModel):
    password: str = Field(max_length=200)
    name: str | None = Field(default=None, max_length=100)


@router.post("/invitations/{token}/accept")
async def accept_invitation(token: str, body: AcceptBody, session: SessionDep, response: Response):
    """接受邀请：新邮箱就建账号并设密码；已有账号的要输入密码证明是本人。"""
    try:
        invitation = await tenancy.find_invitation(session, token)
        account = (await session.execute(select(Account).where(Account.email == invitation.email))).scalars().first()
        if account is None:
            if not (body.name or "").strip():
                raise tenancy.TenancyError("请填写你的名字")
            account = Account(email=invitation.email, name=body.name.strip(), password_hash=tenancy.hash_password(body.password))
            session.add(account)
            await session.flush()
        elif not tenancy.verify_password(body.password, account.password_hash):
            tenancy.note_failure(account.email)
            raise tenancy.TenancyError("密码不对")
        user = await tenancy.accept_invitation(session, invitation, account)
    except tenancy.TenancyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    _set_session_cookie(response, user)
    return await _describe(session, user)
