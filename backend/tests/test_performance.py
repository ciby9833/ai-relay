"""Monitoring must remain read-only, private, bounded and harmless to business execution."""
import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID

from app import deps, telemetry
from app.api import performance as perf
from app.llm.base import Completion, LLMError, TextDelta
from app.main import app


@pytest.fixture
def settings(monkeypatch):
    config = SimpleNamespace(monitoring_enabled=True, prometheus_url="http://monitor.invalid", monitoring_port=9101)
    monkeypatch.setattr(perf, "get_settings", lambda: config)
    monkeypatch.setattr(telemetry, "get_settings", lambda: config)
    perf._cache.clear()
    monkeypatch.setattr(perf, "_lock", asyncio.Lock())
    yield config
    perf._cache.clear()


@pytest.fixture
async def client():
    app.dependency_overrides[deps.get_session] = lambda: SimpleNamespace(close=AsyncMock())
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(is_admin=True, tenant_id=DEFAULT_TENANT_ID)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_auth_and_disabled_do_not_touch_collectors(client, settings, monkeypatch):
    read = AsyncMock(side_effect=AssertionError("must not collect"))
    monkeypatch.setattr(perf, "read_prometheus", read)
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(is_admin=False, tenant_id=DEFAULT_TENANT_ID)
    assert (await client.get("/api/admin/performance")).status_code == 403
    del app.dependency_overrides[deps.get_current_user]
    assert (await client.get("/api/admin/performance")).status_code == 401
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(is_admin=True, tenant_id=DEFAULT_TENANT_ID)
    settings.monitoring_enabled = False
    body = (await client.get("/api/admin/performance")).json()
    assert body["status"] == "disabled" and body["queue"] is None
    assert (await client.get("/api/admin/performance?window=100y")).status_code == 422
    assert (await client.post("/api/admin/performance")).status_code == 405
    read.assert_not_called()


async def test_failure_is_explicit_not_zero_and_health_is_independent(client, settings, monkeypatch):
    monkeypatch.setattr(perf, "read_prometheus", AsyncMock(side_effect=httpx.ConnectError("secret host detail")))
    monkeypatch.setattr(perf, "queue_snapshot", AsyncMock(side_effect=RuntimeError("db unavailable")))
    response = await client.get("/api/admin/performance")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unavailable" and data["current"] == {} and data["queue"] is None
    assert data["end"] - data["start"] == 3600 and data["start"] > 0
    assert set(data["targets"].values()) == {"unknown"}
    assert "secret" not in response.text and "db unavailable" not in response.text
    assert (await client.get("/api/health")).json() == {"ok": True}


async def test_cache_and_stale_targets(client, settings, monkeypatch):
    def series(job, value):
        return {"labels": {"job": job}, "points": [[1, value]]}
    read = AsyncMock(return_value={"current": {"targets": [series(j, 1) for j in perf.JOBS],
        "target_age": [series(j, 120 if j == "worker" else 5) for j in perf.JOBS]}, "history": {}, "errors": []})
    monkeypatch.setattr(perf, "read_prometheus", read)
    queue = AsyncMock(return_value={"scheduled": {"due": 0, "oldest_seconds": 0}})
    monkeypatch.setattr(perf, "queue_snapshot", queue)
    responses = await asyncio.gather(*[client.get("/api/admin/performance?window=24h") for _ in range(3)])
    assert read.await_count == queue.await_count == 1
    assert responses[0].json()["status"] == "partial"
    assert responses[0].json()["targets"]["worker"] == "down"
    assert responses[0].headers["cache-control"] == "no-store"
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(is_admin=False, tenant_id=DEFAULT_TENANT_ID)
    assert (await client.get("/api/admin/performance?window=24h")).status_code == 403
    assert read.await_count == 1  # cached admin data cannot bypass role checks


async def test_auth_connection_released_before_monitoring_wait(client, settings, monkeypatch):
    session = SimpleNamespace(close=AsyncMock())
    app.dependency_overrides[deps.get_session] = lambda: session
    async def read(window):
        session.close.assert_awaited_once()
        return {"current": {}, "history": {}, "errors": []}
    monkeypatch.setattr(perf, "read_prometheus", read)
    monkeypatch.setattr(perf, "queue_snapshot", AsyncMock(return_value={}))
    assert (await client.get("/api/admin/performance")).status_code == 200


async def test_collector_failure_is_partial_even_when_scrape_is_up(client, settings, monkeypatch):
    rows = lambda value: [{"labels": {"job": job}, "points": [[1, value]]} for job in perf.JOBS]
    monkeypatch.setattr(perf, "read_prometheus", AsyncMock(return_value={"current": {
        "targets": rows(1), "target_age": rows(1),
        "node_collectors": [{"labels": {"collector": "filesystem"}, "points": [[1, 0]]}],
    }, "history": {}, "errors": []}))
    monkeypatch.setattr(perf, "queue_snapshot", AsyncMock(return_value={}))
    data = (await client.get("/api/admin/performance")).json()
    assert data["status"] == "partial" and "collector.filesystem" in data["errors"]


@pytest.mark.parametrize("flag", ["false", "true"])
def test_old_image_without_monitoring_dependency_still_imports_and_serves(flag):
    # Reproduce the real dev failure in a fresh interpreter even when the test
    # image itself already has prometheus-client installed.
    script = '''
import sys, importlib.abc, asyncio
class MissingMetrics(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("prometheus_client"):
            raise ModuleNotFoundError("No module named prometheus_client")
sys.meta_path.insert(0, MissingMetrics())
from app.main import app
from app import telemetry
from app.scheduler import worker
from app.feishu import longconn
import httpx
async def check():
    assert telemetry.REGISTRY is None and telemetry.start() is None
    with telemetry.work("turn"):
        assert 1 + 1 == 2
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
        assert (await client.get("/api/health")).json() == {"ok": True}
asyncio.run(check())
'''
    environment = {**os.environ, "MONITORING_ENABLED": flag}
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


async def test_disabled_and_endpoint_start_stop_do_not_change_business(client, settings, monkeypatch):
    settings.monitoring_enabled = False
    server = telemetry.start_http_server
    blocked = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not start"))
    monkeypatch.setattr(telemetry, "start_http_server", blocked)
    assert telemetry.start() is None
    with telemetry.work("turn"):
        assert (await client.get("/api/health")).status_code == 200
    monkeypatch.setattr(telemetry, "start_http_server", server)
    settings.monitoring_enabled = True
    settings.monitoring_port = 0
    for _ in range(2):
        handle = telemetry.start()
        assert handle is not None
        port = handle[0].server_port
        try:
            async with httpx.AsyncClient(trust_env=False) as http:
                assert (await http.get(f"http://127.0.0.1:{port}/metrics")).status_code == 200
            assert (await client.get("/api/health")).status_code == 200
        finally:
            await telemetry.stop(handle)
        settings.monitoring_port = port  # same port can be rebound without leaking a server
        assert (await client.get("/api/health")).status_code == 200


async def test_instrumentation_handles_bad_usage_and_sync_stream_failure(settings):
    class BadUsage:
        name = "test_bad_usage"
        async def stream(self, **kwargs):
            yield Completion([], "end", usage=None)
            yield Completion([], "end", usage={"input_tokens": float("inf"), "output_tokens": float("nan")})
    assert len([event async for event in telemetry.ObservedProvider(BadUsage()).stream()]) == 2
    class Broken:
        name = "test_sync_failure"
        def stream(self, **kwargs):
            raise ValueError("original failure")
    with pytest.raises(ValueError, match="original failure"):
        _ = [event async for event in telemetry.ObservedProvider(Broken()).stream()]
    assert telemetry.INFLIGHT.labels("llm")._value.get() == 0


async def test_stream_without_completion_is_not_reported_as_cancellation(settings):
    class Empty:
        name = "test_empty"
        async def stream(self, **kwargs):
            if False:
                yield
    assert [event async for event in telemetry.ObservedProvider(Empty()).stream()] == []
    assert telemetry.REGISTRY.get_sample_value("relay_llm_seconds_count", {"provider": "test_empty", "outcome": "error"}) == 1
    assert telemetry.INFLIGHT.labels("llm")._value.get() == 0


def test_first_error_series_has_zero_baseline(settings):
    settings.gemini_api_key = "test-only-enabled-flag"
    telemetry._initialize()
    assert telemetry.REGISTRY.get_sample_value("relay_llm_seconds_count", {"provider": "gemini", "outcome": "limited"}) == 0


async def test_prometheus_partial_response_and_bounded_history(settings, monkeypatch):
    requests = []
    original_client = httpx.AsyncClient
    def handle(request):
        requests.append(request)
        if request.url.path.endswith("query_range"):
            assert float(request.url.params["end"]) - float(request.url.params["start"]) == 604800
            assert request.url.params["step"] == "1800"
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "success", "data": {"result": [
            {"metric": {"metric": "cpu", "secret_label": "private"}, "value": [1, "NaN"]},
            {"metric": {"metric": "memory"}, "value": [1, "0"]},
        ]}})
    monkeypatch.setattr(perf.httpx, "AsyncClient", lambda **kw: original_client(transport=httpx.MockTransport(handle), **kw))
    data = await perf.read_prometheus("7d")
    assert len(requests) == 2 and data["errors"] == ["history"]
    assert data["current"]["cpu"] == [{"labels": {}, "points": [[1, None]]}]
    assert data["current"]["memory"][0]["points"] == [[1, 0]]


async def test_stream_is_preserved_and_tokens_are_counted(settings):
    text, completion = TextDelta("hello"), Completion([], "end", usage={"input_tokens": 9, "output_tokens": 2})
    class Provider:
        name = "test_success"
        async def stream(self, **kwargs):
            yield text
            yield completion
    provider = telemetry.ObservedProvider(Provider())
    before = telemetry.REGISTRY.get_sample_value("relay_llm_tokens_total", {"provider": provider.name, "direction": "input"}) or 0
    assert [e async for e in provider.stream(model="private-model")] == [text, completion]
    assert telemetry.REGISTRY.get_sample_value("relay_llm_tokens_total", {"provider": provider.name, "direction": "input"}) == before + 9
    assert telemetry.INFLIGHT.labels("llm")._value.get() == 0


async def test_failures_and_cancellation_keep_original_semantics(settings, monkeypatch):
    class Provider:
        name = "test_failure"
        async def stream(self, **kwargs):
            yield TextDelta("partial")
            cause = RuntimeError("private upstream detail")
            cause.status_code = 429
            raise LLMError("limited") from cause
    wrapped = telemetry.ObservedProvider(Provider())
    with pytest.raises(LLMError, match="limited"):
        _ = [e async for e in wrapped.stream()]
    assert telemetry.REGISTRY.get_sample_value("relay_llm_seconds_count", {"provider": "test_failure", "outcome": "limited"}) >= 1
    assert telemetry.INFLIGHT.labels("llm")._value.get() == 0
    stream = wrapped.stream()
    assert isinstance(await anext(stream), TextDelta)
    await stream.aclose()
    assert telemetry.INFLIGHT.labels("llm")._value.get() == 0
    monkeypatch.setattr(telemetry, "start_http_server", lambda *a, **k: (_ for _ in ()).throw(OSError("port busy")))
    assert telemetry.start() is None


async def test_measurement_error_does_not_break_business(settings, monkeypatch):
    monkeypatch.setattr(telemetry.INFLIGHT, "labels", lambda *a: (_ for _ in ()).throw(RuntimeError("metrics failed")))
    with telemetry.work("turn"):
        result = "business succeeded"
    assert result == "business succeeded"
    with pytest.raises(ValueError, match="business failure"):
        with telemetry.work("turn"):
            raise ValueError("business failure")


@pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="Requires isolated database")
async def test_due_counts_exclude_ordinary_waits_and_do_not_mutate_tasks():
    from app.db import SessionLocal, engine
    from app.models import User, Conversation, Mission, ScheduledTask
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"perf_{uuid.uuid4().hex}", name="Performance test", timezone="UTC")
        session.add(user)
        await session.flush()
        conversation = Conversation(user_id=user.id, channel="mission")
        session.add(conversation)
        await session.flush()
        for status, due in [("active", now - timedelta(seconds=60)), ("waiting", now - timedelta(seconds=30)),
                            ("asking", now - timedelta(seconds=60)), ("waiting", None), ("active", now + timedelta(hours=1)), ("done", now)]:
            session.add(Mission(user_id=user.id, conversation_id=conversation.id, title="test", goal="test", status=status, next_run_at=due))
        for enabled, due in [(True, now - timedelta(seconds=90)), (False, now), (True, now + timedelta(hours=1))]:
            session.add(ScheduledTask(user_id=user.id, title="test", prompt="test", timezone="UTC", enabled=enabled, next_run_at=due))
        await session.flush()
        first = await perf.queue_snapshot(session)
        second = await perf.queue_snapshot(session)
        assert first["missions"]["due"] == second["missions"]["due"] == 2
        assert first["scheduled"]["due"] == second["scheduled"]["due"] == 1
        assert 60 <= first["missions"]["oldest_seconds"] < 70
        await session.rollback()
    await engine.dispose()


@pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="Requires isolated database")
async def test_real_session_rechecks_admin_role_even_with_cached_metrics(settings, monkeypatch):
    from app.db import SessionLocal, engine
    from app.models import User
    from app.security import SESSION_COOKIE, create_session_token
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"perf_auth_{uuid.uuid4().hex}", name="Admin check", timezone="UTC", is_admin=True)
        session.add(user)
        await session.commit()
        user_id = user.id
        token = create_session_token(user_id)
    monkeypatch.setattr(perf, "read_prometheus", AsyncMock(return_value={"current": {}, "history": {}, "errors": []}))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as http:
            http.cookies.set(SESSION_COOKIE, token)
            assert (await http.get("/api/admin/performance")).status_code == 200
            async with SessionLocal() as session:
                user = await session.get(User, user_id)
                user.is_admin = False
                await session.commit()
            assert (await http.get("/api/admin/performance")).status_code == 403
            http.cookies.clear()
            assert (await http.get("/api/admin/performance")).status_code == 401
    finally:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            await session.delete(user)
            await session.commit()
        await engine.dispose()
