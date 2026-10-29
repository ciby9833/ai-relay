"""worker 并行：用户主流程并行跑（有上限、单个超时不拖住别人）；聊天提取独立循环，
同一个用户的主流程在跑时不去改他的事项（跳过这批，之后再处理，消息不丢）；模型限流时退避重试。"""
import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


@db
async def test_users_run_in_parallel_with_a_cap_and_timeouts(monkeypatch):
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.models import User
    from app.scheduler import worker

    tag = uuid.uuid4().hex[:8]
    running, peak, seen = [0], [0], []
    slow_name = f"slow-{tag}"

    async def fake_run(session, feishu, user):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        try:
            seen.append(user.name)
            await asyncio.sleep(5 if user.name == slow_name else 0.2)
        finally:
            running[0] -= 1

    monkeypatch.setattr(worker, "run_for_user", fake_run)
    monkeypatch.setattr(worker, "USER_TIMEOUT", 1)
    async with SessionLocal() as session:
        users = [User(feishu_open_id=f"ou_{tag}_{n}", name=f"u{n}-{tag}", timezone="Asia/Jakarta") for n in range(5)]
        users.append(User(feishu_open_id=f"ou_{tag}_slow", name=slow_name, timezone="Asia/Jakarta"))
        session.add_all(users)
        await session.commit()
        ids = [u.id for u in users]
    try:
        started = asyncio.get_running_loop().time()
        counts = await worker.run_users(None, concurrency=3)
        elapsed = asyncio.get_running_loop().time() - started
        assert peak[0] == 3  # 并行，但不超过上限
        assert counts.get("timeout") == 1 and counts.get("ok", 0) >= 5  # 卡住的那个超时放下，别人照常
        assert elapsed < 2.5  # 串行要 5 秒以上
        assert slow_name in seen
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(User).where(User.id.in_(ids)))
            await session.commit()
        await engine.dispose()


@db
async def test_chat_batches_wait_while_the_users_main_run_holds_the_lock(monkeypatch):
    from sqlalchemy import delete, select

    from app import locks
    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, User
    from app.proactive import chats
    from app.scheduler import worker

    tag = uuid.uuid4().hex[:8]
    chat = f"oc_{tag}"
    calls = []

    async def model(system, prompt, tool):
        calls.append(prompt)
        return {"tasks": [{"message_ref": 0, "requester": "Sari", "assignee": "Xavier", "task": "确认 Medan 报价", "due": "none",
                           "basis": "open_request", "why": "Sari 请他确认报价"}], "asks": [], "progress": []}

    monkeypatch.setattr(chats, "complete_structured", model)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Xavier", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        session.add(ChatMessage(message_id=f"om_{tag}", chat_id=chat, owner_user_id=user_id, chat_name="和 Sari 的私聊",
                                sender_open_id="ou_sari", sender_name="Sari", text="请确认 Medan 报价", mentions=[],
                                created_at=datetime.now(UTC)))
        await session.commit()
    try:
        async with locks.hold_user(user_id) as got:
            assert got
            assert await worker.run_user(None, user_id) == "busy"  # 同一个用户不会同时跑两份主流程
            assert await chats.extract_parallel(None) == 0  # 他的主流程在跑：这批先不处理
            async with SessionLocal() as session:
                assert (await session.execute(select(ChatMessage.processed).where(ChatMessage.chat_id == chat))).scalar() is False
        assert await chats.extract_parallel(None) == 1  # 锁放开后处理，不丢
        assert len(calls) == 1
        async with SessionLocal() as session:
            titles = (await session.execute(select(FollowUp.title).where(FollowUp.user_id == user_id))).scalars().all()
            assert titles == ["Sari 让你：确认 Medan 报价"]
            assert (await session.execute(select(ChatMessage.processed).where(ChatMessage.chat_id == chat))).scalar() is True
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()


async def test_rate_limited_model_calls_back_off_and_retry(monkeypatch):
    from app.llm.base import Completion
    from app.proactive import llm

    attempts, waits = [], []

    class Provider:
        async def stream(self, **kwargs):
            attempts.append(1)
            if len(attempts) <= 2:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            yield Completion(blocks=[{"type": "tool_use", "id": "1", "name": "t", "input": {"ok": True}}], stop_reason="tool_use", usage={})

    async def no_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(llm, "_model", lambda: (Provider(), "m", "p:m"))
    monkeypatch.setattr(llm.asyncio, "sleep", no_sleep)
    tool = {"name": "t", "input_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}
    assert await llm.complete_structured("s", "p", tool) == {"ok": True}
    assert len(attempts) == 3 and len(waits) == 2 and waits[0] < waits[1]

    class Broken:
        async def stream(self, **kwargs):
            raise ValueError("bad request")
            yield  # pragma: no cover

    monkeypatch.setattr(llm, "_model", lambda: (Broken(), "m", "p:m"))
    with pytest.raises(ValueError):
        await llm.complete_structured("s", "p", tool)  # 不是限流：不重试
