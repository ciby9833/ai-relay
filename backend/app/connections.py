"""成员自己接入的数据源：标准邮箱（IMAP 收 / SMTP 发）和日历订阅链接（ICS）。

有了这些，没有飞书的成员也能得到同一套助理行为；有飞书的成员接了自己的邮箱，邮件就走这个邮箱。
密码和订阅链接加密保存；接口只告诉“填了没有”，永远不返回原文。
"""

import json
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserConnection
from app.security import decrypt, encrypt

PROVIDERS = {
    # 公开配置 / 密钥
    "imap": (("email", "username", "imap_host", "imap_port", "smtp_host", "smtp_port", "smtp_security", "sent_folder"),
             ("password",)),
    "ics": (("label",), ("url",)),
}
# 常见邮箱的默认服务器（填邮箱地址时自动带出，也可以改）
PRESETS = {
    "gmail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465, "ssl"),
    "googlemail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465, "ssl"),
    "outlook.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, "starttls"),
    "hotmail.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, "starttls"),
    "yahoo.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, "ssl"),
    "qq.com": ("imap.qq.com", 993, "smtp.qq.com", 465, "ssl"),
    "163.com": ("imap.163.com", 993, "smtp.163.com", 465, "ssl"),
    "zoho.com": ("imap.zoho.com", 993, "smtp.zoho.com", 465, "ssl"),
}


class ConnectionProblem(Exception):
    """给用户看的接入错误。"""


def preset(email: str) -> dict:
    domain = (email or "").rsplit("@", 1)[-1].lower()
    if domain not in PRESETS:
        return {}
    imap_host, imap_port, smtp_host, smtp_port, security = PRESETS[domain]
    return {"imap_host": imap_host, "imap_port": imap_port, "smtp_host": smtp_host, "smtp_port": smtp_port, "smtp_security": security}


async def get(session: AsyncSession, user_id: uuid.UUID, provider: str) -> UserConnection | None:
    return (await session.execute(select(UserConnection).where(UserConnection.user_id == user_id,
                                                               UserConnection.provider == provider))).scalars().first()


def secrets_of(conn: UserConnection | None) -> dict:
    if conn is None or not conn.secrets_enc:
        return {}
    raw = decrypt(conn.secrets_enc)
    return json.loads(raw) if raw else {}


def to_json(provider: str, conn: UserConnection | None) -> dict:
    public, secret = PROVIDERS[provider]
    if conn is None:
        return {"provider": provider, "connected": False, "status": "none", "config": {}, "secrets": {k: False for k in secret}}
    stored = secrets_of(conn)
    return {"provider": provider, "connected": all(stored.get(k) for k in secret), "status": conn.status,
            "last_error": conn.last_error, "config": {k: conn.config.get(k) for k in public},
            "secrets": {k: bool(stored.get(k)) for k in secret},
            "verified_at": conn.verified_at.isoformat() if conn.verified_at else None}


def _validate(provider: str, config: dict, stored: dict) -> None:
    if provider == "imap":
        if "@" not in (config.get("email") or ""):
            raise ConnectionProblem("要填邮箱地址")
        for key in ("imap_host", "smtp_host"):
            host = (config.get(key) or "").strip()
            if not host or "/" in host or " " in host:
                raise ConnectionProblem("收信 / 发信服务器要填域名，例如 imap.gmail.com")
        for key in ("imap_port", "smtp_port"):
            try:
                config[key] = int(config.get(key))
            except (TypeError, ValueError):
                raise ConnectionProblem("端口要填数字") from None
        if config.get("smtp_security") not in ("ssl", "starttls"):
            config["smtp_security"] = "ssl" if config["smtp_port"] == 465 else "starttls"
    if provider == "ics" and stored.get("url"):
        url = stored["url"]
        if url.startswith("webcal://"):
            stored["url"] = url = "https://" + url.removeprefix("webcal://")
        if not url.startswith("https://"):
            raise ConnectionProblem("日历订阅链接要是 https 开头（Google / Outlook 日历里的“私密地址 / ICS 链接”）")


async def save(session: AsyncSession, user: User, provider: str, values: dict) -> UserConnection:
    """保存。密钥留空表示不改；改了之后要重新测试。"""
    if provider not in PROVIDERS:
        raise ConnectionProblem("不支持的接入")
    public, secret = PROVIDERS[provider]
    conn = await get(session, user.id, provider)
    if conn is None:
        conn = UserConnection(user_id=user.id, provider=provider, config={})
        session.add(conn)
    config = dict(conn.config or {})
    if provider == "imap" and values.get("email") and not values.get("username") and config.get("username") == config.get("email"):
        config["username"] = values["email"]  # 登录名一直跟着邮箱地址：换了邮箱就跟着换
    if provider == "imap" and values.get("email") and not config.get("imap_host"):
        config.update(preset(values["email"]))  # 常见邮箱先带出默认服务器
    for key in public:
        if values.get(key) not in (None, ""):
            config[key] = str(values[key]).strip() if not isinstance(values[key], int) else values[key]
    if provider == "imap" and not config.get("username"):
        config["username"] = config.get("email")
    stored = secrets_of(conn)
    for key in secret:
        if values.get(key):
            stored[key] = str(values[key]).strip()
    _validate(provider, config, stored)
    conn.config, conn.secrets_enc = config, encrypt(json.dumps(stored))
    conn.status, conn.last_error, conn.updated_at = "unverified", None, datetime.now(UTC)
    await session.flush()
    forget(user.id)
    return conn


async def mark(session: AsyncSession, conn: UserConnection, error: str | None) -> None:
    conn.status, conn.last_error = ("failed", error[:500]) if error else ("ok", None)
    if not error:
        conn.verified_at = datetime.now(UTC)
    await session.flush()


# ---------- 同步和发送时读取（带短时缓存，避免每封信都查库解密） ----------

_cache: dict[tuple, tuple[float, dict | None]] = {}
TTL = 60


def forget(user_id) -> None:
    for key in [k for k in _cache if k[0] == user_id]:
        _cache.pop(key, None)


async def account(user: User, provider: str) -> dict | None:
    """这个成员可用的接入（配置 + 密钥）；没接或停用返回 None。测试失败的也返回（下一次同步会再试并记下错误）。"""
    key = (user.id, provider)
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from app.db import SessionLocal

    async with SessionLocal() as session:
        conn = await get(session, user.id, provider)
        stored = secrets_of(conn)
        _, secret = PROVIDERS[provider]
        value = {**(conn.config or {}), **stored, "id": conn.id, "status": conn.status} if conn is not None and all(stored.get(k) for k in secret) else None
    _cache[key] = (time.monotonic() + TTL, value)
    return value


async def record_error(user: User, provider: str, error: str | None) -> None:
    """同步时发现账号不能用了（密码改了、授权被撤销）：记下来，设置页里能看到。"""
    from app.db import SessionLocal

    async with SessionLocal() as session:
        conn = await get(session, user.id, provider)
        if conn is not None:
            await mark(session, conn, error)
            await session.commit()
    forget(user.id)


async def record_ok(user: User, provider: str) -> None:
    """同步成功：之前标成失败的恢复成正常（只在状态变化时写库）。"""
    value = await account(user, provider)
    if value is not None and value.get("status") != "ok":
        await record_error(user, provider, None)
        forget(user.id)
