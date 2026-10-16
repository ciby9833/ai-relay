"""Agent 循环 + 真实数据库的集成测试，模型用脚本化的假供应商代替。

需要数据库，默认跳过：
    docker compose run --rm -e RUN_DB_TESTS=1 api pytest
"""

import os
import uuid

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class ScriptedProvider:
    name = "fake"

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def stream(self, *, model, system, messages, tools):
        from app.llm.base import Completion, TextDelta

        self.calls.append([dict(m) for m in messages])
        blocks, stop_reason = self.turns.pop(0)
        for block in blocks:
            if block["type"] == "text":
                yield TextDelta(block["text"])
        yield Completion(blocks=blocks, stop_reason=stop_reason, raw="RAW")


def tool_call(name, arguments, call_id="call_1"):
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


async def test_turn_with_tools_persists_valid_history(monkeypatch):
    from app.agent import loop
    from app.db import SessionLocal, engine
    from app.llm import registry
    from app.memory import service as memory_service
    from app.models import Conversation, Memory, Message, ScheduledTask, User

    async def no_embedding(text):
        return None

    monkeypatch.setattr(memory_service, "embed", no_embedding)

    provider = ScriptedProvider(
        [
            # 第一轮：记一条记忆 + 一个参数不合法的调用，然后回答
            (
                [
                    {"type": "text", "text": "好的。"},
                    tool_call("remember", {"content": "负责印尼线的报价", "kind": "profile"}, "c1"),
                    tool_call("forget", {"memory_id": "不是数字"}, "c2"),
                ],
                "tool_use",
            ),
            ([{"type": "text", "text": "记住了。"}], "end"),
            # 第二轮：创建定时任务；被截断的工具调用不执行
            ([tool_call("create_scheduled_task", {"title": "周报", "prompt": "写周报", "cron": "0 9 * * 1"})], "tool_use"),
            ([{"type": "text", "text": "半句"}, tool_call("forget", {"memory_id": 1})], "max_tokens"),
        ]
    )
    monkeypatch.setattr(registry, "resolve", lambda model_id: (provider, "fake", "fake:fake"))

    async with SessionLocal() as session:
        user = User(feishu_open_id=f"test-{uuid.uuid4().hex}", name="测试", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        conversation = Conversation(user_id=user.id, channel="web")
        session.add(conversation)
        await session.commit()
        user_id = user.id

        try:
            events = [
                event
                async for event in loop.run_turn(
                    session, user=user, conversation=conversation, text="我负责印尼线的报价", feishu=None
                )
            ]
            assert [e["type"] for e in events] == [
                "text", "tool_start", "tool_end", "tool_start", "tool_end", "text", "done",
            ]
            assert [e["ok"] for e in events if e["type"] == "tool_end"] == [True, False]
            assert conversation.title == "我负责印尼线的报价"

            memories = list(
                (await session.execute(select(Memory).where(Memory.user_id == user.id))).scalars()
            )
            assert [m.content for m in memories] == ["负责印尼线的报价"]

            # 同一轮内第二次请求带着供应商原始输出回传
            assert provider.calls[1][-2]["raw"] == "RAW"
            assert provider.calls[1][-2]["raw_provider"] == "fake"

            reply = await loop.run_turn_text(
                session, user=user, conversation=conversation, text="每周一提醒我写周报", feishu=None
            )
            assert reply == "半句\n\n（回答过长，被截断了）"

            # 第二轮的历史来自数据库：不带 raw，上一轮记住的内容出现在 context 块里
            second_turn = provider.calls[2]
            assert all("raw" not in message for message in second_turn)
            assert "负责印尼线的报价" in second_turn[-1]["content"][0]["text"]
            assert second_turn[-1]["content"][0]["meta"] == "context"

            tasks = list(
                (
                    await session.execute(
                        select(ScheduledTask).where(ScheduledTask.user_id == user.id)
                    )
                ).scalars()
            )
            assert len(tasks) == 1 and tasks[0].next_run_at is not None

            # 落库的历史里，每个工具调用后面都紧跟着它的结果
            rows = list(
                (
                    await session.execute(
                        select(Message)
                        .where(Message.conversation_id == conversation.id)
                        .order_by(Message.id)
                    )
                ).scalars()
            )
            for index, row in enumerate(rows):
                call_ids = [b["id"] for b in row.content if b["type"] == "tool_use"]
                if call_ids:
                    answered = [
                        b["tool_use_id"] for b in rows[index + 1].content if b["type"] == "tool_result"
                    ]
                    assert answered == call_ids
            assert loop.sanitize_history(
                [{"role": r.role, "content": r.content} for r in rows]
            ) == [{"role": r.role, "content": r.content} for r in rows]
        finally:
            await session.rollback()
            await session.delete(await session.get(User, user_id))
            await session.commit()
    await engine.dispose()


async def test_proactive_post_waits_for_active_turn():
    from app.db import SessionLocal, engine
    from app.home import ConversationBusy, home_conversation, post, turn_lock
    from app.models import User

    async with SessionLocal() as session:
        user = User(feishu_open_id=f"test-{uuid.uuid4().hex}", name="测试", timezone="Asia/Jakarta")
        session.add(user)
        conversation = await home_conversation(session, user)
        await session.commit()
        user_id = user.id
        try:
            async with turn_lock(conversation.id):
                with pytest.raises(ConversationBusy):
                    await post(session, user, event="e", text="打扰一下")
                await session.rollback()
            # 这一轮结束后就能发了
            await post(session, await session.get(User, user_id), event="e", text="打扰一下")
            await session.commit()
        finally:
            await session.rollback()
            await session.delete(await session.get(User, user_id))
            await session.commit()
            await engine.dispose()
