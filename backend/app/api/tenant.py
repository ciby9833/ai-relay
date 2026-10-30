"""工作区管理（只有本工作区的所有者 / 管理员能用）：名称、成员与角色、邀请、外部渠道（飞书）接入。

所有查询都限定在操作者自己的工作区：看不到、也改不了别的工作区的任何东西。
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import tenancy
from app.config import get_settings
from app.deps import SessionDep, UserDep
from app.models import DEFAULT_TENANT_ID, Account, Tenant, TenantInvitation, User

router = APIRouter(prefix="/api/tenant", tags=["tenant"])


def require_admin(user: UserDep) -> User:
    if not tenancy.is_admin(user):
        raise HTTPException(status_code=403, detail="需要工作区管理员")
    return user


AdminDep = Depends(require_admin)


@router.get("")
async def workspace(session: SessionDep, user: UserDep):
    tenant = await session.get(Tenant, user.tenant_id)
    members = await session.scalar(select(func.count()).select_from(User).where(User.tenant_id == tenant.id, User.status == "active"))
    return {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug, "role": user.role, "members": members}


class WorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.patch("")
async def rename(body: WorkspaceBody, session: SessionDep, admin: User = AdminDep):
    tenant = await session.get(Tenant, admin.tenant_id)
    tenant.name = body.name.strip()
    await session.commit()
    return {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug}


@router.get("/members")
async def members(session: SessionDep, admin: User = AdminDep):
    rows = (await session.execute(
        select(User, Account).outerjoin(Account, Account.id == User.account_id)
        .where(User.tenant_id == admin.tenant_id).order_by(User.status, User.name)
    )).all()
    return [{"id": str(u.id), "name": u.name, "email": a.email if a else u.email, "role": u.role, "status": u.status,
             "feishu": bool(u.feishu_open_id), "password": bool(a and a.password_hash),
             "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None, "me": u.id == admin.id}
            for u, a in rows]


class MemberBody(BaseModel):
    role: Literal["owner", "admin", "member"] | None = None
    status: Literal["active", "deactivated"] | None = None


@router.patch("/members/{member_id}")
async def change_member(member_id: uuid.UUID, body: MemberBody, session: SessionDep, admin: User = AdminDep):
    member = await session.get(User, member_id)
    if member is None or member.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    try:
        await tenancy.change_member(session, admin, member, body.role, body.status)
    except tenancy.TenancyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"id": str(member.id), "role": member.role, "status": member.status}


class InviteBody(BaseModel):
    email: str = Field(max_length=255)
    role: Literal["owner", "admin", "member"] = "member"


@router.post("/invitations")
async def invite(body: InviteBody, session: SessionDep, admin: User = AdminDep):
    """生成邀请链接（7 天有效，只能用一次）。目前不发邮件：管理员把链接发给对方。"""
    try:
        token = await tenancy.invite(session, admin, body.email, body.role)
    except tenancy.TenancyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"link": f"{get_settings().frontend_url}/invite/{token}"}


@router.get("/invitations")
async def invitations(session: SessionDep, admin: User = AdminDep):
    rows = (await session.execute(select(TenantInvitation).where(
        TenantInvitation.tenant_id == admin.tenant_id, TenantInvitation.accepted_at.is_(None), TenantInvitation.revoked_at.is_(None),
    ).order_by(TenantInvitation.id.desc()))).scalars().all()
    return [{"id": i.id, "email": i.email, "role": i.role, "expires_at": i.expires_at.isoformat()} for i in rows]


@router.delete("/invitations/{invitation_id}")
async def revoke(invitation_id: int, session: SessionDep, admin: User = AdminDep):
    from datetime import UTC, datetime

    row = await session.get(TenantInvitation, invitation_id)
    if row is None or row.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404, detail="邀请不存在")
    row.revoked_at = datetime.now(UTC)
    await session.commit()
    return {"ok": True}


# ---------- 外部渠道：飞书 ----------


@router.get("/connections/feishu")
async def feishu_connection(session: SessionDep, admin: User = AdminDep):
    data = tenancy.connection_json(await tenancy.connection(session, admin.tenant_id))
    data["redirect_uri"] = get_settings().feishu_redirect_uri  # 飞书后台“重定向 URL”要填这个
    data["managed"] = admin.tenant_id == DEFAULT_TENANT_ID  # 默认工作区沿用服务器配置，在这里只读
    return data


class FeishuBody(BaseModel):
    app_id: str | None = Field(default=None, max_length=100)
    tenant_key: str | None = Field(default=None, max_length=100)
    app_secret: str | None = Field(default=None, max_length=200)
    verification_token: str | None = Field(default=None, max_length=200)
    encrypt_key: str | None = Field(default=None, max_length=200)


@router.put("/connections/feishu")
async def save_feishu(body: FeishuBody, session: SessionDep, admin: User = AdminDep):
    """保存飞书应用配置。密钥留空表示不改；接口永远不返回密钥原文。"""
    if admin.tenant_id == DEFAULT_TENANT_ID:
        raise HTTPException(status_code=400, detail="默认工作区的飞书配置由服务器统一管理，不能在这里修改")
    conn = await tenancy.save_feishu(session, admin, body.model_dump())
    await session.commit()
    return tenancy.connection_json(conn)


@router.post("/connections/feishu/test")
async def test_feishu(request: Request, session: SessionDep, admin: User = AdminDep):
    try:
        conn = await tenancy.test_feishu(session, admin, getattr(request.app.state, "http", None))
    except tenancy.TenancyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    tenancy.forget(admin.tenant_id)
    return tenancy.connection_json(conn)
