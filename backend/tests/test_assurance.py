"""Regression cases for correlated approval, stale business outcomes and honest denominators."""
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.missions import criteria, outcomes


def mission(items):
    return SimpleNamespace(id=1, user_id=uuid.uuid4(), instruction="让 A 网点异常件数量下降", goal="异常件下降", criteria=items)


def business():
    return criteria.new_list([{"text": "A 网点异常件数量下降", "requirement": "business", "rule": {
        "spreadsheet_token": "token", "sheet_id": "sheet", "cell": "B2", "scope": "A 网点当前异常件数",
        "operator": "decrease", "target": None}}])


async def test_business_readback_cannot_be_overridden_by_reviewer(monkeypatch):
    from app.proactive import llm
    from app.sources import sheets

    read = AsyncMock(return_value={"B2": "20"})
    monkeypatch.setattr(sheets, "read_cells", read)
    judge = AsyncMock(return_value={"criteria": [{"id": 1, "supported": True, "why": "同意"}],
                                  "goal_supported": True, "result_faithful": True, "issues": []})
    monkeypatch.setattr(llm, "complete_structured", judge)
    m = mission(business())
    events = []
    session = SimpleNamespace(add=events.append)
    await outcomes.capture_baselines(None, None, m.criteria)
    assert m.criteria[0]["baseline"]["value"] == "20"
    # Even a successful reminder or colleague claim cannot change the actual number.
    marked = await criteria.mark(session, m, 1, True, "已发送催办，对方说已处理", "action:123")
    assert marked["status"] == "open" and marked["outcome"]["ok"] is False
    read.return_value = {"B2": "12"}
    marked = await criteria.mark(session, m, 1, True, "已经下降", None)
    assert marked["status"] == "met"
    # The value rises again between marking and closing: re-read, reject without consulting model.
    read.return_value = {"B2": "21"}
    checked = await criteria.check(session, m, "目标已达成")
    assert not checked["passed"] and judge.await_count == 0
    assert events[-1].kind == "business_verification" and events[-1].detail["ok"] is False
    read.return_value = {"B2": "12"}
    assert (await criteria.check(session, m, "A 网点异常件由 20 降至 12"))["passed"]
    assert "业务结果回读" in judge.call_args.args[1]
    read.side_effect = RuntimeError("unavailable")
    assert (await outcomes.evaluate(None, None, m.criteria[0]))["ok"] is None


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", True, "已处理"])
async def test_non_numeric_business_state_never_passes(monkeypatch, value):
    from app.sources import sheets
    monkeypatch.setattr(sheets, "read_cells", AsyncMock(return_value={"B2": value}))
    item = business()[0]
    assert (await outcomes.evaluate(None, None, item))["ok"] is None


async def test_missing_baseline_or_rule_is_unknown(monkeypatch):
    from app.sources import sheets
    monkeypatch.setattr(sheets, "read_cells", AsyncMock(return_value={"B2": "2"}))
    item = business()[0]
    assert (await outcomes.evaluate(None, None, item))["ok"] is None
    item["rule"] = None
    assert (await outcomes.evaluate(None, None, item))["ok"] is None


async def test_contract_edits_preserve_or_invalidate_proof(monkeypatch):
    from app.sources import sheets
    monkeypatch.setattr(sheets, "read_cells", AsyncMock(return_value={"B2": "20"}))
    m = mission(business())
    await outcomes.capture_baselines(None, None, m.criteria)
    m.criteria[0].update(status="met", evidence="20 → 12")
    criteria.replace_texts(m, [m.criteria[0]["text"]])
    assert m.criteria[0]["baseline"]["value"] == "20" and m.criteria[0]["status"] == "met"
    spec = {k: m.criteria[0][k] for k in ("text", "requirement", "rule")}
    spec["rule"] = {**spec["rule"], "cell": "C2"}
    criteria.replace_texts(m, [spec])
    assert m.criteria[0]["status"] == "open" and "baseline" not in m.criteria[0]
    with pytest.raises(criteria.CriteriaError):
        criteria.new_list([{**spec, "baseline": {"value": "999"}}])  # model cannot provide observations


async def test_evidence_gates_and_original_goal(monkeypatch):
    from app.proactive import llm
    m = mission(criteria.new_list(["催办已发送"]))
    action = SimpleNamespace(mission_id=1, status="done", summary="催办", result="发送成功", payload={})
    session = SimpleNamespace(get=AsyncMock(return_value=action))
    for verified in [None, {"ok": None}, {"ok": False}]:
        action.payload = {"verified": verified}
        with pytest.raises(criteria.CriteriaError):
            await criteria.resolve(session, m, "action:1")
    action.payload = {"verified": {"ok": True, "detail": "消息存在"}}
    await criteria.mark(session, m, 1, True, "发出催办", "action:1")
    judge = AsyncMock(return_value={"criteria": [{"id": 1, "supported": True, "why": "发送有证据"}],
                                  "goal_supported": False, "result_faithful": True, "issues": ["未证明异常件数量下降"]})
    monkeypatch.setattr(llm, "complete_structured", judge)
    checked = await criteria.check(session, m, "催办已发送")
    assert not checked["passed"] and "原始目标" in checked["problems"][0]
    session.get.return_value = SimpleNamespace(mission_id=1, kind="step", text="我觉得完成了")
    with pytest.raises(criteria.CriteriaError):
        await criteria.resolve(session, m, "log:1")
    session.get.return_value = None
    # Invalid evidence is a deterministic failure even if the reviewer would agree.
    assert not (await criteria.check(session, m, "完成"))["passed"]


async def test_admin_routes_are_forbidden_before_any_database_access():
    from app import deps
    from app.main import app
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(is_admin=False)
    app.dependency_overrides[deps.get_session] = lambda: None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
            for path in ("/api/insights/notifications", "/api/insights/quality"):
                assert (await client.get(path)).status_code == 403
            assert (await client.post("/api/insights/missions/1/review", json={"verdict": "correct", "reason": "x"})).status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要隔离数据库")
async def test_admin_baselines_and_review_history():
    from sqlalchemy import select, func
    from app.api.proactive import notification_stats
    from app.api.quality import quality, review_closure, ReviewBody
    from app.db import SessionLocal, engine
    from app.missions import service
    from app.models import AssuranceEvent, FeishuCard, MissionLog, User, UserDecision

    now = datetime.now(UTC)
    yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=12)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"qa_{uuid.uuid4().hex}", name="Baseline", timezone="UTC", is_admin=True,
                    created_at=now - timedelta(days=40))
        session.add(user)
        await session.flush()
        uid = user.id
        try:
            for i in range(2):
                session.add(FeishuCard(user_id=uid, message_id=f"om_{uuid.uuid4().hex}", title="Relay 简报", text="x", sections=[], created_at=yesterday))
            for via in ["auto", "web"]:
                session.add(UserDecision(user_id=uid, subject="mail", decision="confirm", via=via, detail={}, created_at=yesterday))
            m1 = await service.create(session, user, "A 网点", "降低异常件")
            m2 = await service.create(session, user, "B 网点", "降低异常件")
            for m in (m1, m2):
                m.status = "done"
                session.add(AssuranceEvent(user_id=uid, mission_id=m.id, kind="mission_run", detail={}, created_at=yesterday))
                session.add(MissionLog(mission_id=m.id, kind="done", text="完成", created_at=yesterday))
                session.add(MissionLog(mission_id=m.id, kind="wake", text="执行", created_at=yesterday))
            for kind, detail in [("completion_check", {"passed": True}), ("completion_check", {"passed": False}),
                                 ("write_verification", {"ok": True}), ("write_verification", {"ok": False}),
                                 ("write_verification", {"ok": None}), ("human_takeover", {}), ("human_takeover", {})]:
                session.add(AssuranceEvent(user_id=uid, mission_id=m1.id, kind=kind, detail=detail, created_at=yesterday))
            await session.flush()
            rows = await notification_stats(session, user, 7)
            row = next(r for r in rows if r["user_id"] == str(uid))
            assert len(row["days"]) == 7 and row["pushes_per_day"] == 0.29
            assert sum(d["handled"] for d in row["days"].values()) == 1
            assert sum(d["pushes"] for d in row["days"].values()) == 2
            previous = next(r for r in await notification_stats(session, user, 7, 7) if r["user_id"] == str(uid))
            assert previous["pushes_per_day"] == 0
            stats = await quality(session, user, 7)
            assert stats["false_closure"]["rate"] is None and stats["review_coverage"]["denominator"] == 2
            assert stats["verification_failure"]["rate"] == 0.5 and stats["verification_unknown"] == 1
            assert stats["human_takeover"]["rate"] == 0.5 and stats["completion_failure"]["rate"] == 0.5
            await review_closure(m1.id, ReviewBody(verdict="false_close", reason="实际异常件仍是 20"), session, user)
            stats = await quality(session, user, 7)
            assert stats["false_closure"]["rate"] == 1 and stats["review_coverage"]["rate"] == 0.5
            await review_closure(m1.id, ReviewBody(verdict="correct", reason="补查当时的系统快照：20 → 12"), session, user)
            stats = await quality(session, user, 7)
            assert stats["false_closure"]["rate"] == 0 and stats["false_closure"]["denominator"] == 1
            assert await session.scalar(select(func.count()).select_from(AssuranceEvent).where(AssuranceEvent.kind == "closure_review", AssuranceEvent.user_id == uid)) == 2
            assert m1.status == "done"
        finally:
            await session.rollback()
            existing = await session.get(User, uid)
            if existing:
                await session.delete(existing)
                await session.commit()
            await engine.dispose()
