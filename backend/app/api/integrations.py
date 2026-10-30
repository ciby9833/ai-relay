"""业务系统接入。

管理（仅管理员）：登记业务系统，拿到推送地址和签名密钥。
推送（业务系统调用）：POST /api/inbound/{key}

    请求头
        X-Relay-Timestamp: Unix 秒
        X-Relay-Signature: hex(HMAC-SHA256(密钥, "{timestamp}.{请求体原文}"))
    请求体（JSON）
        event_id     必填，唯一 ID；重复推送只处理一次
        title        必填，一句话说明发生了什么
        content      可选，详细说明
        recipients   必填，要通知谁：[{"email": ...} | {"open_id": ...} | {"name": ...}]
        priority     urgent | normal（默认）| low（只进简报）
        url          可选，业务系统里的详情页
        group_key    可选，归并键（如订单号）：同一个键的后续事件更新同一件事
        status       open（默认）| resolved（这件事已解决，Relay 关闭对应事项）
        action_hint  可选，告诉用户要做什么（如“确认是否改派”）
        due_at       可选，ISO 8601 截止时间
        data         可选，任意结构化字段，Relay 会结合它理解这件事
"""

import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import SessionLocal
from app.deps import SessionDep, UserDep
from app.feishu.client import FeishuError
from app.models import FollowUp, Integration, IntegrationEvent, User
from app.proactive import items
from app.security import decrypt, encrypt
from app.sources import people
from app.sources.base import add_signal

router = APIRouter(tags=["integrations"])

MAX_BODY = 256 * 1024
MAX_SKEW = 300  # 秒


def require_admin(user: UserDep) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以管理业务系统接入")
    return user


def _endpoint(integration: Integration) -> str:
    base = get_settings().feishu_redirect_uri.split("/api/")[0]
    return f"{base}/api/inbound/{integration.key}"


def _json(integration: Integration, reveal: bool = False) -> dict:
    return {
        "id": integration.id, "key": integration.key, "name": integration.name, "description": integration.description,
        "enabled": integration.enabled, "endpoint": _endpoint(integration),
        "secret": decrypt(integration.secret_enc) if reveal else None,
        "created_at": integration.created_at.isoformat() if integration.created_at else None,
    }


# ---------- 管理 ----------


class IntegrationBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


@router.get("/api/integrations")
async def list_integrations(session: SessionDep, admin: User = Depends(require_admin)):
    rows = (await session.execute(select(Integration).where(Integration.tenant_id == admin.tenant_id).order_by(Integration.id))).scalars().all()
    return [_json(i, reveal=True) for i in rows]


@router.post("/api/integrations")
async def create_integration(body: IntegrationBody, session: SessionDep, admin: User = Depends(require_admin)):
    integration = Integration(
        key=secrets.token_urlsafe(12), name=body.name, description=body.description,
        secret_enc=encrypt(secrets.token_hex(32)), created_by=admin.id, tenant_id=admin.tenant_id,
    )
    session.add(integration)
    await session.commit()
    return _json(integration, reveal=True)


@router.post("/api/integrations/{integration_id}/rotate")
async def rotate_secret(integration_id: int, session: SessionDep, admin: User = Depends(require_admin)):
    integration = await session.get(Integration, integration_id)
    if integration is None or integration.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404)
    integration.secret_enc = encrypt(secrets.token_hex(32))
    await session.commit()
    return _json(integration, reveal=True)


@router.delete("/api/integrations/{integration_id}")
async def delete_integration(integration_id: int, session: SessionDep, admin: User = Depends(require_admin)):
    integration = await session.get(Integration, integration_id)
    if integration and integration.tenant_id == admin.tenant_id:
        await session.delete(integration)
        await session.commit()
    return {"ok": True}


@router.get("/api/integrations/{integration_id}/events")
async def recent_events(integration_id: int, session: SessionDep, admin: User = Depends(require_admin)):
    integration = await session.get(Integration, integration_id)
    if integration is None or integration.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404)
    rows = (await session.execute(
        select(IntegrationEvent).where(IntegrationEvent.integration_id == integration_id)
        .order_by(IntegrationEvent.id.desc()).limit(30)
    )).scalars().all()
    return [{"event_id": e.event_id, "title": e.title, "status": e.status, "detail": e.detail,
             "received_at": e.received_at.isoformat()} for e in rows]


# ---------- 推送 ----------


class Recipient(BaseModel):
    email: str | None = None
    open_id: str | None = None
    name: str | None = None


class InboundEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    content: str | None = Field(default=None, max_length=20000)
    recipients: list[Recipient] = Field(min_length=1, max_length=50)
    priority: str = Field(default="normal", pattern="^(urgent|normal|low)$")
    url: str | None = Field(default=None, max_length=2000)
    group_key: str | None = Field(default=None, max_length=255)
    status: str = Field(default="open", pattern="^(open|resolved)$")
    action_hint: str | None = Field(default=None, max_length=500)
    due_at: datetime | None = None
    data: dict | None = None


def verify(secret: str, timestamp: str | None, signature: str | None, body: bytes) -> None:
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="缺少 X-Relay-Timestamp / X-Relay-Signature")
    try:
        if abs(time.time() - int(timestamp)) > MAX_SKEW:
            raise HTTPException(status_code=401, detail="时间戳过期（与服务器相差超过 5 分钟）")
    except ValueError:
        raise HTTPException(status_code=401, detail="时间戳格式错误") from None
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="签名不正确")


async def _resolve(session, feishu, recipient: Recipient, tenant_id) -> tuple[str | None, str]:
    """收件人 → (open_id, 展示名)。只在这个接入所属的工作区里找人。"""
    label = recipient.name or recipient.email or recipient.open_id or "?"
    if recipient.open_id:
        return recipient.open_id, label
    if recipient.email:
        user = (await session.execute(select(User).where(User.email == recipient.email, User.tenant_id == tenant_id))).scalars().first()
        if user:
            return user.feishu_open_id, user.name
        found = await people.find(session, feishu, recipient.email, tenant_id=tenant_id)
        return (found[0]["open_id"], label) if found else (None, label)
    if recipient.name:
        try:
            found = await people.find(session, feishu, recipient.name, tenant_id=tenant_id)
        except people.Ambiguous:
            return None, f"{label}（同名多人）"
        return (found[0]["open_id"], found[0]["name"]) if found else (None, label)
    return None, label


@router.post("/api/inbound/{key}")
async def inbound(key: str, request: Request):
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(status_code=413, detail="请求体超过 256KB")
    async with SessionLocal() as session:
        integration = (await session.execute(select(Integration).where(Integration.key == key))).scalars().first()
        if integration is None or not integration.enabled:
            raise HTTPException(status_code=404, detail="接入源不存在或已停用")
        verify(decrypt(integration.secret_enc), request.headers.get("X-Relay-Timestamp"),
               request.headers.get("X-Relay-Signature"), body)
        try:
            event = InboundEvent.model_validate(json.loads(body))
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=f"请求体格式不对：{exc}") from None

        # 同一事件只处理一次
        logged = await session.execute(
            insert(IntegrationEvent).values(integration_id=integration.id, event_id=event.event_id,
                                            title=event.title, status="delivered")
            .on_conflict_do_nothing(constraint="uq_integration_event").returning(IntegrationEvent.id)
        )
        log_id = logged.scalar()
        if log_id is None:
            return {"duplicate": True}

        from app import tenancy

        feishu = await tenancy.feishu_for(session, integration.tenant_id, getattr(request.app.state, "http", None),
                                          fallback=request.app.state.feishu)
        delivered, unmatched = [], []
        group = event.group_key or event.event_id
        for recipient in event.recipients:
            try:
                open_id, label = await _resolve(session, feishu, recipient, integration.tenant_id) if feishu else (None, recipient.name or "?")
            except FeishuError:
                open_id, label = None, recipient.name or recipient.email or "?"
            if not open_id:
                unmatched.append(label)
                continue
            user = (await session.execute(select(User).where(User.tenant_id == integration.tenant_id,
                                                             User.feishu_open_id == open_id))).scalars().first()
            if user is None:
                # 还没用过 Relay 的同事也能收到（通过 Relay 机器人推送）
                user = User(feishu_open_id=open_id, name=label, timezone=get_settings().default_timezone, tenant_id=integration.tenant_id)
                session.add(user)
                await session.flush()
            if event.status == "resolved":
                item = await items.get_item(session, user, f"biz:{integration.key}:{group}")
                if item and item.status == "open":
                    items.close(item, "done", f"{integration.name}：{event.title}")
                delivered.append(user.name)
                continue
            await add_signal(
                session, user, "biz", f"{integration.key}:{event.event_id}",
                kind="biz_event", title=event.title, body=event.content, url=event.url,
                payload={
                    "integration": integration.name, "integration_key": integration.key, "group_key": group,
                    "action_hint": event.action_hint, "data": event.data,
                    "due_at": event.due_at.isoformat() if event.due_at else None,
                },
                occurred_at=datetime.now(UTC),
                # 低优先级只进简报；其余实时建成跟进事项并告诉他
                status="ignored" if event.priority == "low" else "notify",
                importance="urgent" if event.priority == "urgent" else event.priority,
            )
            delivered.append(user.name)
        status = "resolved" if event.status == "resolved" else ("unmatched" if not delivered else "partial" if unmatched else "delivered")
        await session.execute(
            IntegrationEvent.__table__.update().where(IntegrationEvent.id == log_id).values(
                status=status, detail=(f"未找到：{'、'.join(unmatched)}" if unmatched else None),
            )
        )
        await session.commit()
    return {"delivered": delivered, "unmatched": unmatched}
