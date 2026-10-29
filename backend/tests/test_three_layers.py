"""背景 / 跟踪 / 现在通知 三层，以及真实卡片上的反馈。

场景来自生产：
- 私聊里一句“哥，这个可以发给我吗？”被直接建成待办推给他——前后文看不出“这个”是什么、急不急。
  现在先作候选留在后台；对方补了一句“21 号的报表，今天下班前要”才转成正式事项。
- 打断他的卡片标题写“1 件事需要你知道”，正文却说“有 3 件事……另外两件已经完成”：已完成的结果混进了打断卡片。
- “我已处理 / 少提醒这类”分不清提醒有没有用：现在是“已处理”和“不用跟了 → 原因”，只结束这一件。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_attention import Feishu

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


@db
async def test_unclear_private_asks_wait_in_the_background(monkeypatch):
    from sqlalchemy import delete, select, update

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, User
    from app.proactive import chats, items

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

        def message(n, sender, text, minutes):
            return ChatMessage(message_id=f"om_{tag}_{n}", chat_id=chat, owner_user_id=user_id, chat_name="和 Callesya 的私聊",
                               sender_open_id=me.feishu_open_id if sender == "me" else "ou_c",
                               sender_name="Xavier(吴川)" if sender == "me" else "Callesya", text=text, mentions=[],
                               created_at=now + timedelta(minutes=minutes))

        try:
            session.add(message(0, "c", "哥， 这个可以发给我吗？", 0))
            await session.commit()
            script.append({"tasks": [{"message_ref": 0, "requester": "Callesya", "assignee": "Xavier(吴川)", "task": "把“这个”发给 Callesya",
                                      "due": "none", "basis": "unclear", "why": "Callesya 问能不能发给她，但没说是什么"}],
                           "asks": [], "progress": []})
            await chats.extract(session, None, only_chats=[chat])
            item = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars().one()
            assert item.status == items.CANDIDATE and item.announced_at is not None  # 不上看板、不推送
            assert item.facets["private"] is True and item.facets["basis"] == "unclear"
            # 推送挑的是“未告知的正式事项”：候选不在里面
            pending = (await session.execute(select(FollowUp).where(
                FollowUp.user_id == user_id, FollowUp.status == items.OPEN, FollowUp.announced_at.is_(None)))).scalars().all()
            assert pending == []

            # 对方补充了：是 21 号的报表，今天下班前要 → 转成正式事项，依据写清楚
            session.add(message(1, "c", "就是 21 号的盘点报表，今天下班前要", 5))
            await session.commit()
            script.append({"tasks": [], "asks": [], "progress": [{"item_id": item.id, "verdict": "track",
                                                                  "evidence": "Callesya 说要 21 号的盘点报表，今天下班前要"}]})
            await chats.extract(session, None, only_chats=[chat])
            assert f"[#{item.id}]（候选）" in prompts[-1]
            await session.refresh(item)
            assert item.status == items.OPEN and item.announced_at is None
            assert item.recommendation == "Callesya 说要 21 号的盘点报表，今天下班前要"

            # 另一句随口的问话，2 天没有下文：安静作废
            session.add(message(2, "c", "那个呢？", 10))
            await session.commit()
            script.append({"tasks": [{"message_ref": 0, "requester": "Callesya", "assignee": "Xavier(吴川)", "task": "答复“那个”",
                                      "due": "none", "basis": "unclear", "why": "问得没头没尾"}], "asks": [], "progress": []})
            await chats.extract(session, None, only_chats=[chat])
            other = (await session.execute(select(FollowUp).where(
                FollowUp.user_id == user_id, FollowUp.status == items.CANDIDATE))).scalars().one()
            await session.execute(update(FollowUp).where(FollowUp.id == other.id).values(remind_at=now - timedelta(minutes=1)))
            await session.commit()
            await chats.extract(session, None, only_chats=[chat])
            await session.refresh(other)
            assert other.status == items.EXPIRED
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_cards_count_what_they_say_and_take_feedback(monkeypatch):
    from sqlalchemy import delete, select

    from app import deps
    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import ChatMessage, FeishuCard, FollowUp, ItemFeedback, Signal, User
    from app.proactive import attention, callbacks, items
    from app.proactive.settings import merged
    from app.sources.base import add_signal

    narrated = []

    async def no_post(*args, **kwargs):
        return None

    async def narrate(system, prompt):
        narrated.append(prompt)
        return "先处理 Hendra 的报价。"

    monkeypatch.setattr(items, "post", no_post)
    monkeypatch.setattr(items, "complete_text", narrate)
    monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
    clock = {"digest": False}
    monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: clock["digest"])
    feishu = Feishu()
    settings = merged({})
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Pieter", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            # 两个结果（等的审批通过了）+ 一件上级的急事 + 一件不急的
            for n in range(2):
                await add_signal(session, user, "approval", f"r{n}-{tag}", kind="chat_result", title=f"你发起的第 {n} 张单子通过了",
                                 payload={}, occurred_at=datetime.now(UTC), status="result")
            boss = FollowUp(user_id=user_id, key=f"chat:boss-{tag}", kind="request", owner="me", title="Hendra 让你：今天把印尼线报价发我",
                            facets={"people": ["Hendra"], "open_ids": ["ou_boss"]})
            later = FollowUp(user_id=user_id, key=f"mail-thread:{tag}", kind="review", owner="me", title="看一下 客户A 的周报", facets={})
            session.add_all([boss, later])
            await session.commit()
            await items.announce(session, feishu, user, settings, [])
            assert len(feishu.cards) == 1
            assert "通过了" not in feishu.cards[0]  # 已完成的结果不混进打断他的卡片
            assert narrated == []  # 只有一件要他处理：不另写一段（顺带的不急的事在下面单独一组）
            results = (await session.execute(select(Signal.status).where(Signal.user_id == user_id, Signal.kind == "chat_result"))).scalars().all()
            assert results == ["result", "result"]  # 留给汇总

            clock["digest"] = True
            await items.announce(session, feishu, user, settings, [])
            assert len(feishu.cards) == 2 and "汇总" in (await session.execute(
                select(FeishuCard.title).where(FeishuCard.user_id == user_id).order_by(FeishuCard.created_at.desc()).limit(1))).scalar()

            # 飞书卡片：点“不用跟了” → 这件事的按钮换成原因；选“提醒前就处理了” → 只结束这一件，记下反馈
            card = (await session.execute(select(FeishuCard).where(FeishuCard.user_id == user_id).order_by(FeishuCard.created_at))).scalars().first()
            await callbacks.handle_card_action(feishu, user.feishu_open_id, {"relay": "item_reasons", "item_id": boss.id}, card.message_id)
            await session.refresh(card)
            asking = [c for _, group in card.sections for c in group if c.get("item_id") == boss.id]
            assert asking and asking[0]["asking"] is True
            result = await callbacks.handle_card_action(
                feishu, user.feishu_open_id, {"relay": "item_feedback", "item_id": boss.id, "outcome": "handled_before"}, card.message_id)
            assert result["ok"] and result["message"] == "提醒前你就处理了"
            assert "提醒前就处理了" not in str(result["card"])  # 原因选完，按钮收回
            await session.refresh(boss)
            await session.refresh(later)
            assert boss.status == "done" and later.status == "open"  # 提醒前他就办完了；同一张卡片上的另一件不受影响
            fb = (await session.execute(select(ItemFeedback).where(ItemFeedback.user_id == user_id))).scalars().one()
            assert (fb.outcome, fb.via, fb.source) == ("handled_before", "feishu_card", "group")
            assert fb.pushed_at is not None and fb.seconds_after_push is not None

            # 网页：提醒过的点“已处理” = 提醒后处理了
            import httpx
            app.dependency_overrides[deps.get_current_user] = lambda: user
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
                    response = await client.post(f"/api/items/{later.id}/feedback", json={"outcome": "handled"})
                    assert response.status_code == 200
                    assert (await client.post(f"/api/items/{later.id}/feedback", json={"outcome": "nonsense"})).status_code == 422
            finally:
                app.dependency_overrides.pop(deps.get_current_user, None)
            outcomes = (await session.execute(select(ItemFeedback.outcome).where(ItemFeedback.user_id == user_id)
                                              .order_by(ItemFeedback.id))).scalars().all()
            assert outcomes == ["handled_before", "handled_after"]

            # 管理员：只看数字。提醒后处理 1 件、提醒前已处理 1 件 → 准确率 50%、迟到率 50%
            admin = User(feishu_open_id=f"ou_admin_{tag}", name="Admin", timezone="Asia/Jakarta", is_admin=True)
            session.add(admin)
            await session.commit()
            app.dependency_overrides[deps.get_current_user] = lambda: admin
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
                    data = (await client.get("/api/insights/reminders")).json()
            finally:
                app.dependency_overrides.pop(deps.get_current_user, None)
            mine = next(r for r in data["users"] if r["user"] == "Pieter" and r["pushed"] >= 2)
            assert mine["feedback"] == {"handled_before": 1, "handled_after": 1} and mine["accuracy"] == 0.5 and mine["late"] == 0.5
            assert "报价" not in str(data) and "周报" not in str(data)
            await session.delete(admin)
            await session.commit()
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_chat_items_wait_until_newer_messages_are_read(monkeypatch):
    """推送前复查：那段聊天里还有没读过的新消息（可能就是答复），先不说。"""
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, User
    from app.proactive import chats, items

    tag = uuid.uuid4().hex[:8]
    chat = f"oc_{tag}"
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Pieter", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        item = FollowUp(user_id=user_id, key=f"chat:om_{tag}:x", kind="request", owner="me", title="Budi 让你：发报价",
                        url=chats.chat_link(chat), facets={})
        session.add(item)
        session.add(ChatMessage(message_id=f"om_{tag}_new", chat_id=chat, sender_open_id="ou_b", sender_name="Budi", text="不用了，我拿到了",
                                mentions=[], created_at=datetime.now(UTC)))
        await session.commit()
        await session.refresh(item)
        try:
            assert await items.unread_context(session, [item]) == {item.id}
            await session.execute(ChatMessage.__table__.update().where(ChatMessage.chat_id == chat).values(processed=True))
            await session.commit()
            await session.refresh(item)
            assert await items.unread_context(session, [item]) == set()
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
