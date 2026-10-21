"""飞书开放平台客户端：登录、发消息、读文档。"""

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import update
from sqlalchemy.orm.attributes import set_committed_value

from app.config import Settings
from app.db import SessionLocal
from app.models import User
from app.security import decrypt, encrypt

logger = logging.getLogger(__name__)

BASE = "https://open.feishu.cn/open-apis"
AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"

_DOC_URL = re.compile(r"/(docx|wiki)/([A-Za-z0-9]+)")

# 登录时向用户申请哪些“用户身份”权限，由应用在飞书后台实际开通的权限决定（见 granted_user_scopes），
# 不需要手工配置。查询失败时退回到这份最小清单。
FALLBACK_USER_SCOPES = [
    "offline_access",  # 换取 refresh_token，后台才能持续同步
    "calendar:calendar:readonly",
    "mail:user_mailbox.message:readonly",
    "docx:document:readonly",
]
SCOPE_CACHE_SECONDS = 600


def rich_text(text: str) -> dict:
    """以普通消息发 Markdown（富文本 post + md 标签）：加粗、列表、链接、代码会正常显示，不会出现 ** 符号。
    给同事发消息用这个，不用卡片（对方可以正常引用、转发、复制）。"""
    return {"msg_type": "post", "content": json.dumps({"zh_cn": {"content": [[{"tag": "md", "text": text}]]}}, ensure_ascii=False)}


class FeishuError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class FeishuAuthError(FeishuError):
    """用户的飞书授权缺失或已过期，需要重新登录。"""


def needs_reauth(exc: Exception) -> bool:
    """授权过期，或 token 里缺少这项用户身份权限（报错写着 "under the user identity"）。"""
    return isinstance(exc, FeishuAuthError) or "user identity" in str(exc)


class FeishuClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http
        self._tenant_token: str | None = None
        self._tenant_token_expires = 0.0
        self._tenant_lock = asyncio.Lock()

    # ---- 基础 ----

    async def _request(self, method: str, path: str, *, token: str, **kwargs) -> dict:
        response = await self.http.request(
            method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        try:
            body = response.json()
        except ValueError:
            raise FeishuError(f"飞书返回了非 JSON 响应 (HTTP {response.status_code})") from None
        if body.get("code") != 0:
            raise FeishuError(body.get("msg") or f"HTTP {response.status_code}", body.get("code"))
        return body.get("data") or {}

    async def tenant_api(self, method: str, path: str, **kwargs) -> dict:
        """以应用身份调用。"""
        return await self._request(method, path, token=await self.tenant_token(), **kwargs)

    async def user_api(self, user: User, method: str, path: str, **kwargs) -> dict:
        """以用户本人身份调用：只能看到/操作用户自己有权限的数据。"""
        token = await self.user_token(user)
        if not token:
            raise FeishuAuthError("飞书授权已过期，需要在 Relay 网页端重新登录")
        return await self._request(method, path, token=token, **kwargs)

    async def download(self, url: str, *, user: User | None = None, max_bytes: int = 60 * 1024 * 1024) -> tuple[bytes, str | None]:
        """下载文件原件（流式，超过上限即停）。user 给定时带用户 token（云空间文件）；邮件附件的临时链接不需要。"""
        headers = {}
        if user is not None:
            token = await self.user_token(user)
            if not token:
                raise FeishuAuthError("飞书授权已过期，需要在 Relay 网页端重新登录")
            headers["Authorization"] = f"Bearer {token}"
        target = url if url.startswith("https://") else f"{BASE}{url}"
        async with self.http.stream("GET", target, headers=headers, timeout=120) as response:
            if response.status_code != 200:
                body = (await response.aread())[:500]
                try:
                    import json as _json
                    data = _json.loads(body)
                    raise FeishuError(data.get("msg") or f"HTTP {response.status_code}", data.get("code"))
                except ValueError:
                    raise FeishuError(f"下载失败 (HTTP {response.status_code})", response.status_code) from None
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise FeishuError(f"文件超过 {max_bytes // 1024 // 1024}MB，暂不读取")
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("content-type")

    async def bot_open_id(self) -> str:
        if not getattr(self, "_bot_open_id", None):
            response = await self.http.get(
                f"{BASE}/bot/v3/info", headers={"Authorization": f"Bearer {await self.tenant_token()}"}
            )
            self._bot_open_id = (response.json().get("bot") or {}).get("open_id", "")
        return self._bot_open_id

    async def user_name(self, open_id: str) -> str | None:
        """通讯录里的姓名（需要通讯录读取权限；拿不到时返回 None）。"""
        cache = self.__dict__.setdefault("_names", {})
        if open_id not in cache:
            try:
                data = await self.tenant_api("GET", f"/contact/v3/users/{open_id}", params={"user_id_type": "open_id"})
                cache[open_id] = (data.get("user") or {}).get("name")
            except FeishuError:
                cache[open_id] = None
        return cache[open_id]

    async def tenant_token(self) -> str:
        async with self._tenant_lock:
            if self._tenant_token and time.monotonic() < self._tenant_token_expires:
                return self._tenant_token
            response = await self.http.post(
                f"{BASE}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.settings.feishu_app_id,
                    "app_secret": self.settings.feishu_app_secret,
                },
            )
            body = response.json()
            if body.get("code") != 0:
                raise FeishuError(body.get("msg", "获取 tenant_access_token 失败"), body.get("code"))
            self._tenant_token = body["tenant_access_token"]
            self._tenant_token_expires = time.monotonic() + body.get("expire", 7200) - 300
            return self._tenant_token

    # ---- 登录 ----

    async def granted_user_scopes(self) -> list[str]:
        """应用在飞书后台已开通（审核通过）的全部用户身份权限。后台新开通权限后自动生效，无需改配置。"""
        cached = getattr(self, "_scopes", None)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        try:
            data = await self.tenant_api("GET", "/application/v6/scopes")
            scopes = sorted(
                s["scope_name"] for s in data.get("scopes") or []
                if s.get("scope_type") == "user" and s.get("grant_status") == 1
            )
        except FeishuError as exc:
            logger.warning("查询应用权限失败，使用最小权限清单: %s", exc)
            return FALLBACK_USER_SCOPES
        if "offline_access" not in scopes:
            logger.warning("应用没有开通 offline_access：用户授权两小时后就会过期")
        self._scopes = (time.monotonic() + SCOPE_CACHE_SECONDS, scopes or FALLBACK_USER_SCOPES)
        return self._scopes[1]

    def authorize_url(self, state: str, scopes: list[str]) -> str:
        params = {
            "client_id": self.settings.feishu_app_id,
            "redirect_uri": self.settings.feishu_redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": " ".join(scopes),
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def _oauth_token(self, payload: dict) -> dict:
        response = await self.http.post(
            f"{BASE}/authen/v2/oauth/token",
            json={
                "client_id": self.settings.feishu_app_id,
                "client_secret": self.settings.feishu_app_secret,
                **payload,
            },
        )
        body = response.json()
        if body.get("code") != 0 or "access_token" not in body:
            detail = body.get("error_description") or body.get("msg") or "换取用户 token 失败"
            raise FeishuError(detail, body.get("code"))
        return body

    async def exchange_code(self, code: str) -> dict:
        return await self._oauth_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.feishu_redirect_uri,
            }
        )

    async def user_info(self, user_token: str) -> dict:
        return await self._request("GET", "/authen/v1/user_info", token=user_token)

    @staticmethod
    def store_user_token(user: User, token_data: dict) -> None:
        user.feishu_access_token_enc = encrypt(token_data["access_token"])
        user.feishu_token_expires_at = datetime.now(UTC) + timedelta(
            seconds=int(token_data.get("expires_in", 7200))
        )
        if token_data.get("scope"):
            user.feishu_scopes = token_data["scope"]
        # 只有申请了 offline_access 才会返回 refresh_token
        refresh = token_data.get("refresh_token")
        user.feishu_refresh_token_enc = encrypt(refresh) if refresh else None

    async def user_token(self, user: User) -> str | None:
        """返回仍然有效的用户 token，必要时用 refresh_token 续期；拿不到则返回 None。"""
        expires = user.feishu_token_expires_at
        if user.feishu_access_token_enc and expires and expires > datetime.now(UTC) + timedelta(
            seconds=60
        ):
            return decrypt(user.feishu_access_token_enc)
        refresh = decrypt(user.feishu_refresh_token_enc) if user.feishu_refresh_token_enc else None
        if not refresh:
            return None
        try:
            data = await self._oauth_token({"grant_type": "refresh_token", "refresh_token": refresh})
        except FeishuError as exc:
            logger.warning("刷新飞书用户 token 失败: %s", exc)
            return None
        # refresh_token 只能用一次，新 token 必须立刻落库：用独立的会话提交，
        # 不受调用方事务（例如工具执行失败时的回滚）影响
        fresh = User()
        self.store_user_token(fresh, data)
        values = {
            "feishu_access_token_enc": fresh.feishu_access_token_enc,
            "feishu_refresh_token_enc": fresh.feishu_refresh_token_enc,
            "feishu_token_expires_at": fresh.feishu_token_expires_at,
        }
        async with SessionLocal() as own_session:
            await own_session.execute(update(User).where(User.id == user.id).values(**values))
            await own_session.commit()
        for key, value in values.items():
            set_committed_value(user, key, value)
        return data["access_token"]

    # ---- 消息 ----

    @staticmethod
    def _message_payloads(text: str) -> list[dict]:
        """Relay 自己的回复：优先用 JSON 2.0 卡片渲染 Markdown（支持行内代码、代码块、表格），
        卡片被拒时退回富文本，最后才是纯文本。"""
        from urllib.parse import urlparse

        from app.config import get_settings
        from app.feishu.cards import safe_md

        # 回复里常引用邮件、群消息原文：只有飞书和 Relay 自己的链接能点，杂散的 < > 原样显示
        content = safe_md(text, (urlparse(get_settings().frontend_url).hostname or "",))
        card = {"schema": "2.0", "config": {"width_mode": "fill"}, "body": {"elements": [{"tag": "markdown", "content": content}]}}
        return [
            {"msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
            rich_text(text),
            {"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        ]

    async def _send(self, path: str, extra: dict, text: str, **kwargs) -> None:
        token = await self.tenant_token()
        payloads = self._message_payloads(text)
        for index, payload in enumerate(payloads):
            try:
                await self._request("POST", path, token=token, json={**extra, **payload}, **kwargs)
                return
            except FeishuError as exc:
                if index == len(payloads) - 1:
                    raise
                logger.warning("飞书卡片消息发送失败，改用纯文本: %s", exc)

    async def send_text(self, open_id: str, text: str) -> None:
        await self._send(
            "/im/v1/messages", {"receive_id": open_id}, text, params={"receive_id_type": "open_id"}
        )

    async def send_card(self, open_id: str, card: dict, fallback_text: str) -> str | None:
        """发送交互卡片（JSON 2.0）；卡片被拒时退回纯文本。返回消息 id。"""
        token = await self.tenant_token()
        try:
            data = await self._request(
                "POST",
                "/im/v1/messages",
                token=token,
                params={"receive_id_type": "open_id"},
                json={
                    "receive_id": open_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                },
            )
            return data.get("message_id")
        except FeishuError as exc:
            logger.warning("卡片发送失败，改用文本: %s", exc)
            await self.send_text(open_id, fallback_text)
            return None

    async def reply_text(self, message_id: str, text: str) -> None:
        await self._send(f"/im/v1/messages/{message_id}/reply", {}, text)

    # ---- 文档 ----

    async def read_doc(self, url: str, user_token: str) -> str:
        """以用户身份读取新版文档（docx）或知识库页面的纯文本。"""
        match = _DOC_URL.search(url)
        if not match:
            raise FeishuError("只支持飞书新版文档（/docx/）和知识库（/wiki/）链接")
        kind, token = match.groups()
        if kind == "wiki":
            node = await self._request(
                "GET", "/wiki/v2/spaces/get_node", token=user_token, params={"token": token}
            )
            node = node.get("node") or {}
            if node.get("obj_type") != "docx":
                raise FeishuError(f"这个知识库页面的类型是 {node.get('obj_type')}，目前只支持文档")
            token = node["obj_token"]
        data = await self._request(
            "GET", f"/docx/v1/documents/{token}/raw_content", token=user_token
        )
        return data.get("content", "")
