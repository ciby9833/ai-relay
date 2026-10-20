"""卡片按钮走 HTTP 回调：飞书只发到配置的地址，不会被其他长连接分走（200671 的根因）。"""
import asyncio

import httpx

from app.config import get_settings
from app.main import app
from app.proactive import callbacks


def card_event(token: str, relay: str = "approval") -> dict:
    return {
        "schema": "2.0",
        "header": {"event_id": "e1", "token": token, "event_type": "card.action.trigger", "tenant_key": get_settings().feishu_tenant_key},
        "event": {"operator": {"open_id": "ou_me"}, "action": {"value": {"relay": relay, "signal_id": 1, "approve": True}},
                  "context": {"open_message_id": "om_1"}},
    }


async def test_card_click_over_http_returns_new_card_or_processing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "feishu_verification_token", "vt-test")
    app.state.feishu = object()
    calls = []

    async def fast(feishu, operator, value, message_id):
        calls.append((operator, value["relay"], message_id))
        return {"ok": True, "message": "已批准", "card": {"schema": "2.0", "body": {"elements": []}}, "open_id": operator}

    async def slow(feishu, operator, value, message_id):
        await asyncio.sleep(3)
        return {"ok": True, "message": "已起草", "card": None, "open_id": operator}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
        assert (await client.post("/api/feishu/events", json=card_event("wrong"))).status_code == 403
        assert (await client.post("/api/feishu/events", json={"type": "url_verification", "token": "vt-test", "challenge": "c1"})).json() == {"challenge": "c1"}

        monkeypatch.setattr(callbacks, "handle_card_action", fast)
        body = (await client.post("/api/feishu/events", json=card_event("vt-test"))).json()
        assert calls == [("ou_me", "approval", "om_1")]
        assert body["toast"] == {"type": "success", "content": "已批准"} and body["card"]["type"] == "raw"

        # 来不及在 3 秒内做完：先回“正在处理”，不让飞书报错
        monkeypatch.setattr(callbacks, "handle_card_action", slow)
        monkeypatch.setattr(callbacks, "deferred_update", lambda *a, **k: asyncio.sleep(0))
        body = (await client.post("/api/feishu/events", json=card_event("vt-test", "draft_reply"))).json()
        assert body == {"toast": {"type": "info", "content": "收到，正在处理…"}}
