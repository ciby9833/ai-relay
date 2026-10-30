"""工作区（租户）、登录账号、成员角色、邀请，以及每个工作区自己接入的飞书。

模型（类似 Slack）：
- Tenant 是一家公司 / 一个工作区；数据、成员、连接都归属于工作区，工作区之间互相隔离。
- Account 是一个人的登录账号（邮箱 + 密码）；一个账号可以加入多个工作区。
- User 是这个人在某个工作区里的成员资料，原有的对话、事项、任务等数据都挂在 User 上（所以迁移不需要搬数据）。
- 飞书是工作区接入的外部渠道之一：管理员填写应用配置（密钥加密存储）；没接入飞书的工作区照样能用 Relay 本身的能力。
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import DEFAULT_TENANT_ID, Account, Tenant, TenantConnection, TenantInvitation, User
from app.security import decrypt, encrypt

ROLES = ("owner", "admin", "member")
ADMIN_ROLES = ("owner", "admin")
INVITE_TTL = timedelta(days=7)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


class TenancyError(ValueError):
    """可以原样告诉用户的错误。"""


# ---------- 密码（标准库 scrypt，不引入新依赖） ----------

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD:
        raise TenancyError(f"密码至少 {MIN_PASSWORD} 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not password:
        return False
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# 登录失败限流（进程内）：同一邮箱 15 分钟内最多失败 10 次
_failures: dict[str, list[float]] = {}
FAIL_WINDOW, FAIL_LIMIT = 15 * 60, 10


def throttled(email: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(email, []) if now - t < FAIL_WINDOW]
    _failures[email] = recent
    return len(recent) >= FAIL_LIMIT


def note_failure(email: str) -> None:
    _failures.setdefault(email, []).append(time.time())


def normalize_email(email: str | None) -> str:
    value = (email or "").strip().lower()
    if not EMAIL.match(value):
        raise TenancyError("邮箱格式不对")
    return value


# ---------- 角色 ----------


def set_role(user: User, role: str) -> None:
    if role not in ROLES:
        raise TenancyError("不认识的角色")
    user.role = role
    user.is_admin = role in ADMIN_ROLES  # 旧代码按 is_admin 判断管理员，保持一致


def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES


# ---------- 工作区与成员 ----------


async def unique_slug(session: AsyncSession, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"
    slug, n = base, 1
    while await session.scalar(select(Tenant.id).where(Tenant.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


async def create_workspace(session: AsyncSession, account: Account, name: str, timezone: str | None = None) -> User:
    """建一个新工作区，账号本人成为 owner。返回他在这个工作区里的成员资料。"""
    name = (name or "").strip()
    if not name:
        raise TenancyError("请填写工作区名称")
    tenant = Tenant(name=name[:255], slug=await unique_slug(session, name))
    session.add(tenant)
    await session.flush()
    member = User(tenant_id=tenant.id, account_id=account.id, name=account.name, email=account.email,
                  timezone=timezone or get_settings().default_timezone)
    set_role(member, "owner")
    session.add(member)
    await session.flush()
    return member


async def memberships(session: AsyncSession, account_id: uuid.UUID) -> list[tuple[User, Tenant]]:
    """这个账号加入的、仍有效的工作区（停用的成员、停用的工作区不算）。"""
    rows = (await session.execute(
        select(User, Tenant).join(Tenant, Tenant.id == User.tenant_id).where(
            User.account_id == account_id, User.status == "active", Tenant.status == "active").order_by(Tenant.name)
    )).all()
    return [(u, t) for u, t in rows]


async def owners_left(session: AsyncSession, tenant_id: uuid.UUID, excluding: uuid.UUID) -> int:
    return await session.scalar(select(func.count()).select_from(User).where(
        User.tenant_id == tenant_id, User.role == "owner", User.status == "active", User.id != excluding)) or 0


async def change_member(session: AsyncSession, actor: User, member: User, role: str | None = None, status: str | None = None) -> None:
    """改成员的角色或停用/恢复。规则：只有 owner 能设 owner 或改 owner；不能动自己；工作区至少留一位 owner。"""
    if member.tenant_id != actor.tenant_id:
        raise TenancyError("这位成员不在你的工作区")
    if member.id == actor.id:
        raise TenancyError("不能修改自己的角色或状态")
    if (role == "owner" or member.role == "owner") and actor.role != "owner":
        raise TenancyError("只有所有者可以调整所有者")
    leaving_owner = member.role == "owner" and ((role and role != "owner") or status == "deactivated")
    if leaving_owner and await owners_left(session, member.tenant_id, member.id) == 0:
        raise TenancyError("工作区至少要保留一位所有者")
    if role:
        set_role(member, role)
    if status:
        if status not in ("active", "deactivated"):
            raise TenancyError("不认识的状态")
        member.status = status


# ---------- 邀请 ----------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def invite(session: AsyncSession, actor: User, email: str, role: str = "member") -> str:
    """生成邀请链接里的令牌（只在这一次返回原文）。已经是成员的不重复邀请。"""
    email = normalize_email(email)
    if role not in ROLES or (role == "owner" and actor.role != "owner"):
        raise TenancyError("不能用这个角色邀请")
    existing = await session.scalar(select(User.id).join(Account, Account.id == User.account_id).where(
        User.tenant_id == actor.tenant_id, Account.email == email, User.status == "active"))
    if existing:
        raise TenancyError("这个邮箱已经是工作区成员")
    token = secrets.token_urlsafe(32)
    session.add(TenantInvitation(tenant_id=actor.tenant_id, email=email, role=role, token_hash=_token_hash(token),
                                 invited_by=actor.id, expires_at=datetime.now(UTC) + INVITE_TTL))
    await session.flush()
    return token


async def find_invitation(session: AsyncSession, token: str) -> TenantInvitation:
    found = (await session.execute(select(TenantInvitation).where(TenantInvitation.token_hash == _token_hash(token or "")))).scalars().first()
    if found is None or found.revoked_at or found.accepted_at:
        raise TenancyError("邀请链接无效或已经用过")
    if found.expires_at < datetime.now(UTC):
        raise TenancyError("邀请链接已过期，请让管理员重新邀请")
    return found


async def accept_invitation(session: AsyncSession, invitation: TenantInvitation, account: Account) -> User:
    """账号接受邀请，成为这个工作区的成员（已经是成员但被停用的，恢复）。"""
    if account.email != invitation.email:
        raise TenancyError("这个邀请是发给另一个邮箱的")
    member = (await session.execute(select(User).where(
        User.tenant_id == invitation.tenant_id, User.account_id == account.id))).scalars().first()
    if member is None:
        member = User(tenant_id=invitation.tenant_id, account_id=account.id, name=account.name, email=account.email,
                      timezone=get_settings().default_timezone)
        session.add(member)
    member.status = "active"
    set_role(member, invitation.role)
    invitation.accepted_at = datetime.now(UTC)
    await session.flush()
    return member


# ---------- 渠道连接：飞书 ----------

FEISHU_PUBLIC = ("app_id", "tenant_key")
FEISHU_SECRET = ("app_secret", "verification_token", "encrypt_key")


async def connection(session: AsyncSession, tenant_id: uuid.UUID, provider: str = "feishu") -> TenantConnection | None:
    return (await session.execute(select(TenantConnection).where(
        TenantConnection.tenant_id == tenant_id, TenantConnection.provider == provider))).scalars().first()


def secrets_of(conn: TenantConnection | None) -> dict:
    if conn is None or not conn.secrets_enc:
        return {}
    return json.loads(decrypt(conn.secrets_enc) or "{}")


def connection_json(conn: TenantConnection | None) -> dict:
    """给管理员看：公开配置原样返回，密钥只告诉“填了没有”，永远不返回原文。"""
    if conn is None:
        return {"provider": "feishu", "configured": False, "status": "none", "config": {}, "secrets": {k: False for k in FEISHU_SECRET}}
    stored = secrets_of(conn)
    return {"provider": conn.provider, "configured": bool(conn.config.get("app_id") and stored.get("app_secret")),
            "status": conn.status, "last_error": conn.last_error, "config": {k: conn.config.get(k) for k in FEISHU_PUBLIC},
            "secrets": {k: bool(stored.get(k)) for k in FEISHU_SECRET},
            "verified_at": conn.verified_at.isoformat() if conn.verified_at else None}


async def save_feishu(session: AsyncSession, actor: User, values: dict) -> TenantConnection:
    """保存飞书配置。密钥留空表示不改。改了之后状态回到“未验证”，旧的客户端缓存作废。"""
    conn = await connection(session, actor.tenant_id)
    if conn is None:
        conn = TenantConnection(tenant_id=actor.tenant_id, provider="feishu", config={})
        session.add(conn)
    config = dict(conn.config or {})
    for key in FEISHU_PUBLIC:
        if key in values and values[key] is not None:
            config[key] = str(values[key]).strip()
    stored = secrets_of(conn)
    for key in FEISHU_SECRET:
        if values.get(key):
            stored[key] = str(values[key]).strip()
    conn.config, conn.secrets_enc = config, encrypt(json.dumps(stored))
    conn.status, conn.last_error, conn.updated_by, conn.updated_at = "unverified", None, actor.id, datetime.now(UTC)
    await session.flush()
    forget(actor.tenant_id)
    return conn


def feishu_settings(conn: TenantConnection | None) -> Settings | None:
    """按工作区的飞书配置生成一份设置（其余设置沿用全局）。没配好返回 None。"""
    stored = secrets_of(conn)
    if conn is None or conn.status == "disabled" or not conn.config.get("app_id") or not stored.get("app_secret"):
        return None
    return get_settings().model_copy(update={
        "feishu_app_id": conn.config["app_id"], "feishu_app_secret": stored["app_secret"],
        "feishu_tenant_key": conn.config.get("tenant_key") or "",
        "feishu_verification_token": stored.get("verification_token") or "", "feishu_encrypt_key": stored.get("encrypt_key") or "",
    })


async def ensure_default_connection(session: AsyncSession) -> None:
    """启动时：默认工作区还没有飞书连接、而服务器配置里有飞书应用的，把它登记为默认工作区的连接——现有登录和同步不受影响。"""
    settings = get_settings()
    if not settings.feishu_app_id or await connection(session, DEFAULT_TENANT_ID) is not None:
        return
    stored = {"app_secret": settings.feishu_app_secret, "verification_token": settings.feishu_verification_token,
              "encrypt_key": settings.feishu_encrypt_key}
    session.add(TenantConnection(tenant_id=DEFAULT_TENANT_ID, provider="feishu", status="ok", verified_at=datetime.now(UTC),
                                 config={"app_id": settings.feishu_app_id, "tenant_key": settings.feishu_tenant_key},
                                 secrets_enc=encrypt(json.dumps({k: v for k, v in stored.items() if v}))))
    await session.commit()


# 每个工作区一个飞书客户端（各自缓存应用 token）；配置改了就重建
_clients: dict[uuid.UUID, tuple[datetime | None, object]] = {}


def forget(tenant_id: uuid.UUID) -> None:
    _clients.pop(tenant_id, None)


async def feishu_for(session: AsyncSession, tenant_id: uuid.UUID, http, fallback=None):
    """这个工作区的飞书客户端。工作区没接飞书时返回 fallback（默认工作区沿用服务器配置的客户端，保证旧行为不变）。"""
    from app.feishu.client import FeishuClient

    if tenant_id == DEFAULT_TENANT_ID and fallback is not None:
        return fallback  # 默认工作区始终用服务器配置的飞书客户端（长连接、事件回调都绑在它上面），旧行为不变
    conn = await connection(session, tenant_id)
    version = conn.updated_at if conn else None
    cached = _clients.get(tenant_id)
    if cached and cached[0] == version:
        return cached[1]
    settings = feishu_settings(conn)
    if settings is None:
        return fallback if tenant_id == DEFAULT_TENANT_ID else None
    client = FeishuClient(settings, http)
    _clients[tenant_id] = (version, client)
    return client


async def test_feishu(session: AsyncSession, actor: User, http) -> TenantConnection:
    """用填写的 App ID / Secret 向飞书换一次应用 token，验证配置可用。"""
    from app.feishu.client import FeishuClient, FeishuError

    conn = await connection(session, actor.tenant_id)
    settings = feishu_settings(conn)
    if settings is None:
        raise TenancyError("请先填写 App ID 和 App Secret")
    try:
        await FeishuClient(settings, http).tenant_token()
        conn.status, conn.last_error, conn.verified_at = "ok", None, datetime.now(UTC)
    except (FeishuError, Exception) as exc:  # noqa: BLE001 - 网络错误也如实告诉管理员
        conn.status, conn.last_error = "failed", str(exc)[:300]
    await session.flush()
    return conn
