"""群里@了他：先读上下文再决定要不要等他回（复盘“是的，用PDA”那件事）。

他在群里问“他PDA有是把这个上传吗？”，对方在话题里 @他回答“是的，用PDA”。以前两小时后提醒他“@你的消息还没回”，
直到他在群里说话才结束；现在这种答复直接结束，真正在问他的才盯着，而且别人替他答了、讨论有了结论也会结束。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


@db
async def test_mentions_are_judged_in_context(monkeypatch):
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, Signal, User
    from app.proactive import chats, items
    from app.sources.base import add_signal

    tag = uuid.uuid4().hex[:8]
    chat = f"oc_{tag}"
    now = datetime.now(UTC)
    prompts, script = [], []

    async def fake(system, prompt, tool):
        prompts.append(prompt)
        return script.pop(0)

    monkeypatch.setattr(chats, "complete_structured", fake)
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_x_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(me)
        await session.flush()
        user_id = me.id

        def message(n, sender, text, minutes, parent=None, mention=False, processed=False):
            return ChatMessage(message_id=f"om_{tag}_{n}", chat_id=chat, sender_open_id=f"ou_{sender}", sender_name=sender,
                               text=text, processed=processed, parent_message_id=parent, created_at=now + timedelta(minutes=minutes),
                               mentions=[{"open_id": me.feishu_open_id, "name": "Xavier(吴川)"}] if mention else [])

        async def mention(n, sender, text):
            await add_signal(session, me, "message", f"om_{tag}_{n}", kind="mention", title="群里有人@你", body=text,
                             payload={"chat_id": chat, "chat_name": "【重要项目】Cargo终端项目", "sender_name": sender},
                             occurred_at=now, status="watching")

        try:
            question = message(0, "Xavier(吴川)", "他PDA有是把这个上传吗？", 0, processed=True)
            question.sender_open_id = me.feishu_open_id
            session.add(question)
            session.add(message(1, "Callesya", "@Xavier(吴川) 是的，用PDA", 8, parent=f"om_{tag}_0", mention=True))
            session.add(message(2, "Yohannes", "@Xavier(吴川) 这个周末国内上班吗？", 9, mention=True))
            await mention(1, "Callesya", "@Xavier(吴川) 是的，用PDA")
            await mention(2, "Yohannes", "@Xavier(吴川) 这个周末国内上班吗？")
            await session.commit()

            # 模型读了上下文：第一条是答复，第二条是在问他
            script.append({"tasks": [], "progress": [], "asks": [{"message_ref": 1, "to": "Xavier(吴川)", "question": "这个周末国内上不上班"}]})
            await chats.extract(session, None, only_chats=[chat])
            assert "Callesya（回复 Xavier(吴川)：他PDA有是把这个上传吗？）：@Xavier(吴川) 是的，用PDA" in prompts[0]
            signals = {s.external_id: s for s in (await session.execute(select(Signal).where(Signal.user_id == user_id))).scalars()}
            answered, asking = signals[f"om_{tag}_1"], signals[f"om_{tag}_2"]
            await session.refresh(answered)
            await session.refresh(asking)
            assert answered.status == "done" and "不需要他回复" in answered.payload["settled"]
            assert asking.status == "watching" and asking.payload["ask"] == "这个周末国内上不上班"

            # 两小时后还没回：事项写明问的是什么，带上会话链接
            asking.status, asking.importance = "notify", "normal"
            await session.commit()
            await items.track(session, None, me)
            item = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars().one()
            assert item.title == "Yohannes 在【重要项目】Cargo终端项目问你：这个周末国内上不上班"
            assert item.url == chats.chat_link(chat)

            # 别人替他答了：这件事和群里其他未结事项一起判断，结束
            session.add(message(3, "Ruson", "国内这周六上班的", 20))
            await session.commit()
            script.append({"tasks": [], "asks": [], "progress": [{"item_id": item.id, "verdict": "done", "evidence": "Ruson 答了国内周六上班"}]})
            await chats.extract(session, None, only_chats=[chat])
            assert f"[#{item.id}]" in prompts[-1]
            await session.refresh(item)
            assert item.status == "done" and "Ruson" in item.resolution
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_when_the_model_fails_mentions_keep_the_old_safety_net(monkeypatch):
    """模型出错、没给出判断：@ 继续盯着（两小时后照旧提醒），不会因为出错把真正的问题吞掉。"""
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, Signal, User
    from app.proactive import chats
    from app.sources.base import add_signal

    async def broken(system, prompt, tool):
        raise RuntimeError("timeout")

    monkeypatch.setattr(chats, "complete_structured", broken)
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_x_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(me)
        await session.flush()
        user_id = me.id
        session.add(ChatMessage(message_id=f"om_{tag}", chat_id=f"oc_{tag}", sender_open_id="ou_y", sender_name="Yohannes",
                                text="@Xavier(吴川) 周末上班吗？", mentions=[{"open_id": me.feishu_open_id, "name": "Xavier(吴川)"}]))
        await add_signal(session, me, "message", f"om_{tag}", kind="mention", title="群里有人@你", body="周末上班吗？",
                         payload={"chat_id": f"oc_{tag}"}, occurred_at=datetime.now(UTC), status="watching")
        await session.commit()
        try:
            await chats.extract(session, None, only_chats=[f"oc_{tag}"])
            signal = (await session.execute(select(Signal).where(Signal.user_id == user_id))).scalars().one()
            assert signal.status == "watching"
            # 消息没丢：标回未处理，下一轮再试；连续失败 3 次才放弃
            stored = (await session.execute(select(ChatMessage).where(ChatMessage.chat_id == f"oc_{tag}"))).scalars().one()
            assert stored.processed is False
            await chats.extract(session, None, only_chats=[f"oc_{tag}"])
            await chats.extract(session, None, only_chats=[f"oc_{tag}"])
            await session.refresh(stored)
            assert stored.processed is True
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == f"oc_{tag}"))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
