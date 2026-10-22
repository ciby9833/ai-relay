"""2026-10-22 生产复盘后的修复：查到上限也要回答、每轮结果留痕、同一件事不拆成几件、依据里不出现消息编号。"""
import os
import uuid
from datetime import UTC, datetime

import pytest

from app.proactive.chats import clean_evidence
from tests.test_missions import ScriptedProvider, call

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


def test_evidence_has_no_message_numbers():
    assert clean_evidence("[0] Veigar(吴英杰)在周四发出了“最新的结果”") == "Veigar(吴英杰)在周四发出了“最新的结果”"
    assert clean_evidence("[2][3] Veigar 表示已发过") == "Veigar 表示已发过"
    assert clean_evidence("消息[0]-[5]中 Ivan 说已填") == "Ivan 说已填"
    assert clean_evidence("没有编号的依据") == "没有编号的依据"


@db
async def test_step_limit_still_answers_and_turns_are_recorded(monkeypatch):
    """Tangerang 货量那种问题：模型一直想查。到了上限不能只报“已停止”，要按已有信息回答；每轮结果都记下来。"""
    from sqlalchemy import delete, select

    from app.agent import loop
    from app.db import SessionLocal, engine
    from app.llm import registry
    from app.memory import service as memory_service
    from app.models import AssuranceEvent, Conversation, User

    async def no_embedding(text):
        return None

    monkeypatch.setattr(memory_service, "embed", no_embedding)
    provider = ScriptedProvider()
    monkeypatch.setattr(registry, "resolve", lambda model_id: (provider, "fake", "fake:fake"))
    for _ in range(loop.MAX_STEPS - 1):
        provider.add(call("search_memory", query="tangerang tonase"))
    # 最后一步模型还想查，同时给了一段文字：只留文字
    provider.add({"type": "text", "text": "Relay 看不到 TMS 的实时货量，邮件和群里也没找到今天的数字。"}, call("search_memory", query="again"))
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        conversation = Conversation(user_id=user.id, channel="web", title="t")
        session.add(conversation)
        await session.commit()
        user_id = user.id
        try:
            text = await loop.run_turn_text(session, user=user, conversation=conversation,
                                            text="barang hari ini di gateway tangerang ada berapa ton?", feishu=None)
            assert "看不到 TMS" in text and "已停止" not in text
            assert "不能再调用了" in provider.prompts[-1]  # 最后一步告诉了模型要直接回答
            events = (await session.execute(select(AssuranceEvent).where(AssuranceEvent.user_id == user_id, AssuranceEvent.kind == "turn"))).scalars().all()
            assert [e.detail["outcome"] for e in events] == ["forced_final"]
            assert events[0].detail["tool_calls"] == loop.MAX_STEPS - 1

            # 最后一步连文字都没有：给出如实的兜底回答（按他的语言）
            for _ in range(loop.MAX_STEPS):
                provider.add(call("search_memory", query="x"))
            text = await loop.run_turn_text(session, user=user, conversation=conversation, text="did i have unrecorded absence?", feishu=None)
            assert "7" in text and ("Could you tell me" in text or "你能告诉我" in text or "Bisa beri tahu" in text)

            # 出错的轮次也留下记录（以前错误只在界面上闪过）
            class Broken:
                name = "broken"

                async def stream(self, **kwargs):
                    raise RuntimeError("Gemini 响应超时（120 秒）")
                    yield  # pragma: no cover

            monkeypatch.setattr(registry, "resolve", lambda model_id: (Broken(), "fake", "fake:fake"))
            with pytest.raises(RuntimeError):
                await loop.run_turn_text(session, user=user, conversation=conversation, text="明日工作餐帮我点一份", feishu=None)
            await session.rollback()
            events = (await session.execute(select(AssuranceEvent).where(AssuranceEvent.user_id == user_id, AssuranceEvent.kind == "turn")
                                            .order_by(AssuranceEvent.id))).scalars().all()
            assert events[-1].detail["outcome"] == "error" and "超时" in events[-1].detail["errors"][0]
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_consecutive_asks_to_the_same_person_become_one_item(monkeypatch):
    """他 11:17 和 11:20 连着对 Veigar 提了两句：只建一件事；对方一回复，这一件就结束，不会剩下一件永远挂着。"""
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, User
    from app.proactive import chats, llm

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_me_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(me)
        await session.flush()
        user_id = me.id
        chat = f"oc_{tag}"

        script = [
            {"tasks": [
                {"message_ref": 0, "requester": "Xavier(吴川)", "assignee": "Veigar(吴英杰)", "task": "单独拎出三段码叉叉的数量", "due": "none"},
                {"message_ref": 1, "requester": "Xavier(吴川)", "assignee": "Veigar(吴英杰)", "task": "抓数据核实出仓与签收三段码是否一致", "due": "none"},
            ], "progress": []},
        ]

        async def fake(system, prompt, tool):
            return script.pop(0)

        monkeypatch.setattr(chats, "complete_structured", fake)
        try:
            for n, text in enumerate(["把那个三段码叉叉的也单独拎出来看一下有多少", "@Veigar(吴英杰) 出仓的三段码和签收的是不是一致？数据需要你那边抓一下"]):
                session.add(ChatMessage(message_id=f"om_{tag}_{n}", chat_id=chat, sender_open_id=me.feishu_open_id,
                                        sender_name="Xavier(吴川)", text=text, mentions=[], created_at=datetime.now(UTC)))
            await session.commit()
            await chats.extract(session, None, only_chats=[chat])
            found = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars().all()
            assert len(found) == 1
            assert "叉叉" in found[0].title and "签收三段码" in found[0].title and found[0].summary.count("「") == 2
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_a_reply_that_settles_one_item_rechecks_its_siblings(monkeypatch):
    """之前已经拆成两件的（553/554）：Veigar 的回复让其中一件办完，另一件要再单独判断一次，而不是一直挂着。"""
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, User
    from app.proactive import chats

    tag = uuid.uuid4().hex[:8]
    chat = f"oc_{tag}"
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_me_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(me)
        await session.flush()
        user_id = me.id
        a = FollowUp(user_id=me.id, key=f"chat:a{tag}:x", kind="waiting", owner="others", title="等 Veigar(吴英杰)：单独拎出叉叉的数量",
                     waiting_on="Veigar(吴英杰)", url=chats.chat_link(chat), facets={})
        b = FollowUp(user_id=me.id, key=f"chat:b{tag}:x", kind="waiting", owner="others", title="等 Veigar(吴英杰)：核实三段码是否一致",
                     waiting_on="Veigar(吴英杰)", url=chats.chat_link(chat), facets={})
        other = FollowUp(user_id=me.id, key=f"chat:c{tag}:x", kind="waiting", owner="others", title="等 Pax：发网点清单",
                         waiting_on="Pax", url=chats.chat_link(chat), facets={})
        session.add_all([a, b, other])
        await session.flush()
        prompts = []
        script = [
            {"tasks": [], "progress": [{"item_id": b.id, "verdict": "done", "evidence": "[0] Veigar 发了最新结果"}]},
            {"tasks": [], "progress": [{"item_id": a.id, "verdict": "done", "evidence": "Veigar 说叉叉的明细也在里面"}]},
        ]

        async def fake(system, prompt, tool):
            prompts.append(prompt)
            return script.pop(0)

        monkeypatch.setattr(chats, "complete_structured", fake)
        session.add(ChatMessage(message_id=f"om_{tag}", chat_id=chat, sender_open_id=me.feishu_open_id, sender_name="Veigar(吴英杰)",
                                text="这个我发过给你们呀，叉叉的明细也在里面", mentions=[], created_at=datetime.now(UTC)))
        await session.commit()
        try:
            await chats.extract(session, None, only_chats=[chat])
            for item in (a, b, other):
                await session.refresh(item)
            assert (a.status, b.status, other.status) == ("done", "done", "open")
            assert "等 Pax" not in prompts[1] and f"[#{a.id}]" in prompts[1]  # 只复核同一个人的
            assert b.resolution == "有了结果：Veigar 发了最新结果"  # 依据里没有消息编号
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
