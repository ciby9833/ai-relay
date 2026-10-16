"""业务系统推送的集成测试。

    docker compose run --rm -e RUN_DB_TESTS=1 api pytest
"""

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid

import httpx
import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class NoFeishu:
    """通讯录里查不到任何人。"""

    async def tenant_api(self, *args, **kwargs):
        from app.feishu.client import FeishuError

        raise FeishuError("not found")

    async def user_name(self, open_id):
        return None


def signed(secret: str, event: dict, ts: int | None = None) -> tuple[bytes, dict]:
    body = json.dumps(event, ensure_ascii=False).encode()
    ts = str(ts or int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, {"Content-Type": "application/json", "X-Relay-Timestamp": ts, "X-Relay-Signature": sig}


async def test_business_events_become_follow_ups():
    from app.db import SessionLocal, engine
    from app.feishu.client import FeishuClient
    from app.main import app
    from app.models import FollowUp, Integration, Signal, User
    from app.proactive import items
    from app.security import encrypt

    app.state.feishu = NoFeishu()
    secret = secrets.token_hex(16)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="阿明", timezone="Asia/Jakarta", email=f"{uuid.uuid4().hex[:8]}@co.com")
        integration = Integration(key=secrets.token_urlsafe(8), name="TMS", secret_enc=encrypt(secret))
        session.add_all([user, integration])
        await session.commit()
        user_id, email, key, integration_id = user.id, user.email, integration.key, integration.id

    event = {"event_id": "e1", "title": "订单 JT123 清关异常", "content": "海关要求补充发票", "priority": "urgent",
             "recipients": [{"email": email}, {"email": "nobody@nowhere.test"}], "group_key": "JT123",
             "action_hint": "确认是否改派", "url": "https://tms/JT123"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://relay") as client:
            body, headers = signed(secret, event)
            assert (await client.post(f"/api/inbound/{key}", content=body, headers={"Content-Type": "application/json"})).status_code == 401
            assert (await client.post(f"/api/inbound/{key}", content=body, headers={**headers, "X-Relay-Signature": "0" * 64})).status_code == 401
            stale_body, stale = signed(secret, event, ts=int(time.time()) - 3600)
            assert (await client.post(f"/api/inbound/{key}", content=stale_body, headers=stale)).status_code == 401

            response = await client.post(f"/api/inbound/{key}", content=body, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json() == {"delivered": ["阿明"], "unmatched": ["nobody@nowhere.test"]}
            # 重复推送只处理一次
            body2, headers2 = signed(secret, event)
            assert (await client.post(f"/api/inbound/{key}", content=body2, headers=headers2)).json() == {"duplicate": True}

            # 低优先级：只留作简报素材，不建事项
            low = {**event, "event_id": "e2", "priority": "low", "group_key": "OTHER", "recipients": [{"email": email}]}
            await client.post(f"/api/inbound/{key}", content=signed(secret, low)[0], headers=signed(secret, low)[1])

        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            await items.track(session, NoFeishu(), user)
            found = {i.key: i for i in (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars()}
            item = found[f"biz:{key}:JT123"]
            assert (item.kind, item.owner, item.importance, item.next_step) == ("biz", "me", "urgent", "确认是否改派")
            assert item.title == "TMS：订单 JT123 清关异常" and item.url == "https://tms/JT123"
            assert f"biz:{key}:OTHER" not in found
            low_signal = (await session.execute(select(Signal).where(Signal.external_id == f"{key}:e2"))).scalars().one()
            assert low_signal.status == "ignored"

        # 业务系统推送“已解决”：关闭对应的事
        resolved = {**event, "event_id": "e3", "status": "resolved", "title": "已改派", "recipients": [{"email": email}]}
        async with httpx.AsyncClient(transport=transport, base_url="http://relay") as client:
            body3, headers3 = signed(secret, resolved)
            assert (await client.post(f"/api/inbound/{key}", content=body3, headers=headers3)).status_code == 200
        async with SessionLocal() as session:
            item = (await session.execute(select(FollowUp).where(FollowUp.key == f"biz:{key}:JT123"))).scalars().one()
            assert item.status == "done" and "已改派" in item.resolution
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, user_id))
            await session.delete(await session.get(Integration, integration_id))
            await session.commit()
        await engine.dispose()
