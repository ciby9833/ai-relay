"""Gemini 客户端：配置了服务账号就走 Vertex AI，否则用 Gemini API key。

访问令牌用服务账号私钥在本地签发（self-signed JWT），不去 oauth2.googleapis.com 换：
生产服务器到那个地址时好时坏、有时完全连不上，在用户请求里换令牌会一直等到超时（“Gemini 响应超时”）。
本地签发不需要网络；令牌约一小时过期，后台仍按“剩不到 15 分钟就换”提前续签，请求里只在快过期时补签。
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from google import genai
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from app.config import get_settings

logger = logging.getLogger("relay.llm")

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
REFRESH_TIMEOUT = 10  # 秒：换令牌单次最多等这么久
REFRESH_AHEAD = timedelta(minutes=15)  # 剩不到这么久就提前换
URGENT_AHEAD = timedelta(minutes=2)  # 请求前发现剩不到这么久才当场换
_lock = threading.Lock()


class _QuickRequest(Request):
    """google-auth 换令牌时不传超时（默认 120 秒），这里统一改成短超时。"""

    def __call__(self, *args, timeout=None, **kwargs):
        return super().__call__(*args, timeout=REFRESH_TIMEOUT, **kwargs)


def _credentials_file() -> str | None:
    path = get_settings().google_application_credentials
    return path if path and os.path.isfile(path) and os.path.getsize(path) > 0 else None


def gemini_configured() -> bool:
    return bool(_credentials_file() or get_settings().gemini_api_key)


@lru_cache
def credentials() -> service_account.Credentials | None:
    path = _credentials_file()
    if not path:
        return None
    # always_use_jwt_access：令牌在本地签发，不依赖 oauth2.googleapis.com
    return service_account.Credentials.from_service_account_file(path, scopes=SCOPES).with_always_use_jwt_access(True)


def _remaining(creds) -> timedelta:
    if not creds.token or not creds.expiry:
        return timedelta(0)
    return creds.expiry.replace(tzinfo=UTC) - datetime.now(UTC)


def refresh(ahead: timedelta = REFRESH_AHEAD, attempts: int = 3) -> bool:
    """令牌剩余时间不足 ahead 时换新的；返回令牌现在是否可用。同步函数，放在线程里跑。"""
    creds = credentials()
    if creds is None:
        return True
    with _lock:
        if _remaining(creds) > ahead:
            return True
        for attempt in range(1, attempts + 1):
            try:
                creds.refresh(_QuickRequest())
                logger.info("Google 访问令牌已刷新，有效到 %s", creds.expiry)
                return True
            except (TransportError, GoogleAuthError) as exc:
                logger.warning("刷新 Google 访问令牌失败（第 %s 次）：%s", attempt, str(exc)[:200])
                time.sleep(attempt)
        return _remaining(creds) > timedelta(0)


async def ensure_fresh() -> None:
    """模型请求前：令牌快过期了才当场换（正常情况下后台已经换好了，这里直接返回）。"""
    creds = credentials()
    if creds is not None and _remaining(creds) <= URGENT_AHEAD:
        await asyncio.to_thread(refresh, URGENT_AHEAD)


async def keep_fresh(interval: float = 60) -> None:
    """后台常驻：每分钟看一眼，剩不到 15 分钟就提前换。各个服务进程（api、worker、长连接）各跑一个。"""
    if credentials() is None:
        return
    while True:
        try:
            await asyncio.to_thread(refresh)
        except Exception:  # noqa: BLE001 - 后台任务不能退出
            logger.exception("后台刷新 Google 令牌出错")
        await asyncio.sleep(interval)


@lru_cache
def genai_client() -> genai.Client:
    settings = get_settings()
    path = _credentials_file()
    if path:
        with open(path) as f:
            project = settings.google_cloud_project or json.load(f)["project_id"]
        return genai.Client(vertexai=True, project=project, location=settings.google_cloud_location, credentials=credentials())
    return genai.Client(api_key=settings.gemini_api_key)
