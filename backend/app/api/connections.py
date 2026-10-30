"""成员自己接入的邮箱（IMAP/SMTP）和日历订阅链接（ICS）：保存、测试、断开。密钥永远不回显。"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete

from app import connections
from app.deps import SessionDep, UserDep
from app.feishu.client import FeishuError
from app.models import UserConnection
from app.sources import ics, imap

router = APIRouter(prefix="/api/connections", tags=["connections"])


class MailBody(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_security: str | None = Field(default=None, max_length=16)
    sent_folder: str | None = Field(default=None, max_length=255)


class CalendarBody(BaseModel):
    url: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(default=None, max_length=100)


def _check(provider: str) -> str:
    if provider not in connections.PROVIDERS:
        raise HTTPException(status_code=404, detail="不支持的接入")
    return provider


@router.get("")
async def overview(session: SessionDep, user: UserDep):
    data = {p: connections.to_json(p, await connections.get(session, user.id, p)) for p in connections.PROVIDERS}
    data["feishu"] = {"linked": bool(user.feishu_open_id)}
    return data


@router.get("/imap/preset")
async def mail_preset(email: str):
    """常见邮箱的默认服务器（填好邮箱地址时自动带出）。"""
    return connections.preset(email)


async def _save(session, user, provider: str, values: dict):
    try:
        conn = await connections.save(session, user, provider, values)
    except connections.ConnectionProblem as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return connections.to_json(provider, conn)


@router.put("/imap")
async def save_mail(body: MailBody, session: SessionDep, user: UserDep):
    return await _save(session, user, "imap", body.model_dump())


@router.put("/ics")
async def save_calendar(body: CalendarBody, session: SessionDep, user: UserDep):
    return await _save(session, user, "ics", body.model_dump())


@router.post("/{provider}/test")
async def test(provider: str, session: SessionDep, user: UserDep):
    """真的连一次：邮箱能登录收信和发信服务器（不发信）；日历能读到日程。"""
    conn = await connections.get(session, user.id, _check(provider))
    account = {**(conn.config or {}), **connections.secrets_of(conn)} if conn else None
    if not account or not all(account.get(k) for k in connections.PROVIDERS[provider][1]):
        raise HTTPException(status_code=400, detail="还没有填完整")
    note = None
    try:
        if provider == "imap":
            await imap.test(account)
            note = "收信、发信服务器都能登录"
        else:
            now = datetime.now(UTC)
            events = await ics.list_events(account, user.timezone, now, now + timedelta(days=7))
            note = f"读到未来 7 天的 {len(events)} 个日程"
        await connections.mark(session, conn, None)
    except FeishuError as exc:  # MailboxError / CalendarError
        await connections.mark(session, conn, str(exc))
    await session.commit()
    connections.forget(user.id)
    return {**connections.to_json(provider, conn), "note": note if conn.status == "ok" else None}


@router.delete("/{provider}")
async def disconnect(provider: str, session: SessionDep, user: UserDep):
    """断开：删掉保存的账号和密码。已经读进来的邮件、日程和事项保留。"""
    await session.execute(delete(UserConnection).where(UserConnection.user_id == user.id, UserConnection.provider == _check(provider)))
    await session.commit()
    connections.forget(user.id)
    return connections.to_json(provider, None)
