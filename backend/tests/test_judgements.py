"""后台判断：清单和代码一一对应；每次调用都记下；从真实反馈推出对错；统计只有数字、只看本工作区；固定样本能按线上格式拼出输入。

用虚构数据和假的模型，不调用真实模型。
"""
import json
import os
import pathlib
import re
import uuid
from datetime import UTC, datetime

import pytest

from app.judgements import catalog, replay

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
DB = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


def test_every_model_call_is_a_named_judgement_and_every_judgement_is_used():
    source = "\n".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py") if "judgements" not in p.parts)
    # 不允许绕过 judged 直接调用模型（否则这次判断不会被记下、也没法评估）
    bare = [line.strip() for line in source.splitlines()
            if re.search(r"await complete_(structured|text)\(", line) and "judged(" not in line]
    assert bare == []
    used = set(re.findall(r'judged\(\s*"([a-z_]+)"', source))
    assert used == set(catalog.JUDGEMENTS)
    assert all(j.kind in catalog.KINDS for j in catalog.JUDGEMENTS.values())


def test_golden_cases_build_inputs_the_same_way_as_production():
    for name in ("mail_triage", "reply_state"):
        cases = replay.golden_cases(name)
        assert len(cases) >= 4 and len({c["id"] for c in cases}) == len(cases)
        for case in cases:
            assert "<mail>" in replay.build_input(name, case["fields"])
    triage = replay.build_input("mail_triage", replay.golden_cases("mail_triage")[0]["fields"])
    assert triage.startswith("用户：Budi") and "这封信里他是：收件人" in triage and "<mail>" in triage
    assert {c["expect"] for c in replay.golden_cases("reply_state")} <= {"done", "waiting", "mine"}


@DB
async def test_calls_are_recorded_and_labelled_from_real_feedback(monkeypatch):
    import httpx
    from sqlalchemy import delete, select

    from app import tenancy
    from app.db import SessionLocal, engine
    from app.judgements import labels, record
    from app.llm.base import Completion
    from app.main import app
    from app.models import (Account, AttentionRule, FollowUp, ItemFeedback, JudgementRun, PendingAction, Signal, Tenant, User)
    from app.proactive import engine as proactive_engine
    from app.proactive import llm

    class FakeProvider:
        def __init__(self, output):
            self.output = output

        async def stream(self, **kwargs):
            yield Completion(blocks=[{"type": "tool_use", "name": kwargs["tools"][0]["name"], "input": self.output, "id": "t"}], stop_reason="tool_use")

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        account = Account(email=f"judge-{tag}@x.test", name="Judge", password_hash=tenancy.hash_password("judge-pass-1"))
        session.add(account)
        await session.flush()
        owner = await tenancy.create_workspace(session, account, f"Judge {tag}")
        user_id, tenant_id = owner.id, owner.tenant_id
        signals = [Signal(user_id=user_id, source="mail", kind="mail", external_id=f"m{n}-{tag}", title=f"信 {n}", payload={})
                   for n in range(3)]
        session.add_all(signals)
        await session.commit()
        sig = [s.id for s in signals]

    decision = {"importance": "normal", "notify_now": False, "needs_reply": True, "action_type": "reply", "due": "none",
                "summary": "s", "reason": "r", "ask": "确认报价"}
    monkeypatch.setattr(llm, "_model", lambda: (FakeProvider(decision), "fake-model", "fake:model"))
    try:
        # 三次分级都被记下（在 judged 范围里）；不在范围里的调用不记
        for signal_id in sig:
            await record.judged("mail_triage", user_id, f"signal:{signal_id}", llm.complete_structured,
                                proactive_engine.TRIAGE_SYSTEM, "prompt", proactive_engine.TRIAGE_TOOL)
        await llm.complete_structured(proactive_engine.TRIAGE_SYSTEM, "outside", proactive_engine.TRIAGE_TOOL)
        async with SessionLocal() as session:
            runs = list((await session.execute(select(JudgementRun).where(JudgementRun.user_id == user_id).order_by(JudgementRun.id))).scalars())
            assert [r.subject for r in runs] == [f"signal:{s}" for s in sig]
            assert runs[0].model == "fake-model" and runs[0].output["action_type"] == "reply" and len(runs[0].prompt_version) == 8
            # 真实反馈：第一封他处理了（判断对），第二封“不归我”（判断错），第三封没有反馈（不计）
            items = [FollowUp(user_id=user_id, key=f"mail-thread:{s}-{tag}", kind="reply", owner="me", title="x", signal_ids=[s]) for s in sig]
            session.add_all(items)
            await session.flush()
            session.add_all([
                ItemFeedback(user_id=user_id, item_id=items[0].id, kind="reply", source="mail", outcome="handled_after", via="web"),
                ItemFeedback(user_id=user_id, item_id=items[1].id, kind="reply", source="mail", outcome="not_mine", via="web")])
            # 草稿：原样发出（对）；规则：一条启用（对）一条不用（错）
            draft = JudgementRun(name="reply_draft", user_id=user_id, subject=f"signal:{sig[0]}", prompt_version="v", input="p",
                                 output={"body": "您好，已确认。"}, created_at=datetime.now(UTC))
            proposal = JudgementRun(name="rule_proposal", user_id=user_id, subject=f"user:{user_id}", prompt_version="v", input="p",
                                    output={"rules": []}, created_at=datetime.now(UTC))
            session.add_all([draft, proposal])
            session.add(PendingAction(user_id=user_id, kind="send_mail", summary="回复", signal_id=sig[0], payload={"body": "您好，已确认。"}, status="done"))
            session.add_all([AttentionRule(user_id=user_id, match={}, level="mute", label="a", source="memory", status="active"),
                             AttentionRule(user_id=user_id, match={}, level="mute", label="b", source="memory", status="rejected")])
            await session.commit()
            runs = list((await session.execute(select(JudgementRun).where(JudgementRun.user_id == user_id))).scalars())
            verdicts = sorted((s.verdict, s.why) for s in await labels.samples(session, runs))
            assert verdicts == sorted([("right", "feedback:handled_after"), ("wrong", "feedback:not_mine"), ("right", "draft:sent"),
                                       ("right", "rule:accepted"), ("wrong", "rule:rejected")])

        # 长期任务完成核对：全自动——结束 8 天没重做 = 对；结束后又开了几乎一样的任务 = 错；才结束 1 天的不计
        from datetime import timedelta

        from app.models import Conversation, Mission, MissionLog

        async with SessionLocal() as session:
            now = datetime.now(UTC)
            talk = Conversation(user_id=user_id, channel="mission")
            session.add(talk)
            await session.flush()
            held = Mission(user_id=user_id, conversation_id=talk.id, title="催 Nikki 交运单", goal="让 Nikki 交 9 月运单明细", instruction="让 Nikki 交 9 月运单明细", status="done")
            redone = Mission(user_id=user_id, conversation_id=talk.id, title="约 Budi 开会", goal="约 Budi 下周开会", instruction="约 Budi 下周二开会讨论报价", status="done")
            fresh = Mission(user_id=user_id, conversation_id=talk.id, title="催 Kevin", goal="催 Kevin 回复", instruction="催 Kevin 回复报价", status="done")
            session.add_all([held, redone, fresh])
            await session.flush()
            session.add_all([MissionLog(mission_id=held.id, kind="done", text="完成", created_at=now - timedelta(days=8)),
                             MissionLog(mission_id=redone.id, kind="done", text="完成", created_at=now - timedelta(days=3)),
                             MissionLog(mission_id=fresh.id, kind="done", text="完成", created_at=now - timedelta(days=1))])
            session.add(Mission(user_id=user_id, conversation_id=talk.id, title="再约 Budi", goal="约 Budi 开会", instruction="约 Budi 下周二开会讨论报价单", status="active",
                                created_at=now - timedelta(days=2)))
            checks = [JudgementRun(name="mission_completion_check", user_id=user_id, subject=f"mission:{m.id}", prompt_version="v",
                                   input="p", output={"goal_supported": True}) for m in (held, redone, fresh)]
            session.add_all(checks)
            await session.commit()
            found = {s.why for s in await labels.samples(session, checks)}
            assert found == {"mission:held", "mission:redone"}
            await session.execute(delete(JudgementRun).where(JudgementRun.id.in_([c.id for c in checks])))
            await session.execute(delete(Mission).where(Mission.user_id == user_id))
            await session.execute(delete(Conversation).where(Conversation.user_id == user_id))
            await session.commit()

        # 管理员看到的只有数字，按判断和提示词版本分组
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as c:
            await c.post("/api/auth/login", json={"email": f"judge-{tag}@x.test", "password": "judge-pass-1"})
            data = (await c.get("/api/insights/judgements")).json()
        triage = next(g for g in data["judgements"] if g["name"] == "mail_triage")
        assert triage["runs"] == 3 and triage["right"] == 1 and triage["wrong"] == 1 and triage["accuracy"]["rate"] == 0.5
        assert "信 " not in json.dumps(data, ensure_ascii=False)  # 不含内容
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(JudgementRun).where(JudgementRun.user_id == user_id))
            await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        await engine.dispose()


def test_string_booleans_and_numbers_from_the_model_are_coerced_by_schema():
    from app.proactive.engine import TRIAGE_TOOL
    from app.proactive.llm import coerce

    raw = {"importance": "normal", "notify_now": "true", "needs_reply": "False", "action_type": "reply", "due": "none",
           "summary": "s", "reason": "r"}
    fixed = coerce(raw, TRIAGE_TOOL["input_schema"])
    assert fixed["notify_now"] is True and fixed["needs_reply"] is False and fixed["summary"] == "s"
    assert coerce({"n": "3", "flag": "maybe"}, {"type": "object", "properties": {"n": {"type": "integer"}, "flag": {"type": "boolean"}}}) == {"n": 3, "flag": "maybe"}
