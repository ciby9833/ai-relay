"""卡片按钮走 HTTP 回调：飞书只发到配置的地址，不会被其他长连接分走（200671 的根因）。"""
import asyncio
from types import SimpleNamespace

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
    app.state.feishu = SimpleNamespace(settings=settings)
    calls = []

    async def fast(feishu, operator, value, message_id, **_):
        calls.append((operator, value["relay"], message_id))
        return {"ok": True, "message": "已批准", "card": {"schema": "2.0", "body": {"elements": []}}, "open_id": operator}

    async def slow(feishu, operator, value, message_id, **_):
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


async def test_late_callback_answers_at_once_and_updates_with_event_token(monkeypatch):
    """回调在路上已经用了 2.6 秒：立刻回“正在处理”，处理完用回调里的 event.token 延时更新卡片。"""
    import time

    settings = get_settings()
    monkeypatch.setattr(settings, "feishu_verification_token", "vt-test")
    app.state.feishu = SimpleNamespace(settings=settings)
    updates = []

    async def quick_but_not_instant(feishu, operator, value, message_id, **_):
        await asyncio.sleep(0.3)
        return {"ok": True, "message": "已批准", "card": {"schema": "2.0"}, "open_id": operator}

    async def record(feishu, message_id, result, update_token=None):
        updates.append((message_id, result["message"], update_token))

    monkeypatch.setattr(callbacks, "handle_card_action", quick_but_not_instant)
    monkeypatch.setattr(callbacks, "deferred_update", record)
    event = card_event("vt-test")
    event["header"]["create_time"] = str(int((time.time() - 2.6) * 1_000_000))
    event["event"]["token"] = "c-update-token"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
        started = time.monotonic()
        body = (await client.post("/api/feishu/events", json=event)).json()
        assert time.monotonic() - started < 0.2  # 没有再等
    assert body == {"toast": {"type": "info", "content": "收到，正在处理…"}}
    await asyncio.sleep(0.5)
    assert updates == [("om_1", "已批准", "c-update-token")]


async def test_deferred_update_prefers_official_token_then_falls_back(monkeypatch):
    from app.feishu.client import FeishuError

    calls = []

    class Feishu:
        fail_token = False

        async def tenant_api(self, method, path, **kwargs):
            calls.append((method, path))
            if path == "/interactive/v1/card/update" and self.fail_token:
                raise FeishuError("token expired", 300030)
            return {}

        async def send_text(self, open_id, text):
            calls.append(("text", text))

    feishu = Feishu()
    result = {"ok": True, "message": "已批准", "card": {"schema": "2.0"}, "open_id": "ou_me"}
    await callbacks.deferred_update(feishu, "om_1", result, "c-token")
    assert calls == [("POST", "/interactive/v1/card/update")]
    calls.clear()
    feishu.fail_token = True
    await callbacks.deferred_update(feishu, "om_1", result, "c-token")
    assert calls == [("POST", "/interactive/v1/card/update"), ("PATCH", "/im/v1/messages/om_1")]
