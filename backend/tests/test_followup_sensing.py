"""复盘 Fiona 那件事后的规则：他回了什么决定还等不等；对方在别处回应了就不再催；群里有答复就结束。"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.sources.mail import strip_quote


def test_strip_quote_keeps_only_new_text():
    text = "Joining now, see you.\n\nOn Mon, Oct 19, 2026 at 4:06 PM Fiona <f@openai.com> wrote:\n> Will you be attending?"
    assert strip_quote(text) == "Joining now, see you."
    assert strip_quote("好的，周一见\n\n发件人：Fiona\n主题：Re") == "好的，周一见"
    assert strip_quote("没有引用") == "没有引用"
    inline = 'We can proceed as scheduled. Thank you! Best regards, Wu Chuan From: "Fiona Cheong"<fiona@sales.openai.com> Date: Mon'
    assert strip_quote(inline) == "We can proceed as scheduled. Thank you! Best regards, Wu Chuan"
    assert strip_quote("Meet me at the front desk. From now on we use room B.") == "Meet me at the front desk. From now on we use room B."


db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


async def _setup(session):
    from app.models import FollowUp, Signal, User

    user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
    session.add(user)
    await session.flush()
    theirs = Signal(user_id=user.id, source="mail", kind="mail", external_id=uuid.uuid4().hex, title="Re: J&T Cargo // OpenAI",
                    body="Will you be attending the call? Or do you want to postpone it?", status="tracked",
                    payload={"thread_id": "th-1", "from_name": "Zorvan", "from_address": "zorvan@example.com", "from": "Zorvan"},
                    occurred_at=datetime.now(UTC) - timedelta(minutes=10), importance="urgent")
    session.add(theirs)
    await session.flush()
    item = FollowUp(user_id=user.id, key="mail-thread:th-1", kind="reply", owner="me", title="回复 Zorvan：Re: J&T Cargo // OpenAI",
                    summary="确认是否参加会议还是改期", signal_ids=[theirs.id], importance="urgent",
                    due_at=datetime.now(UTC) + timedelta(hours=2), next_step="回复这封邮件")
    session.add(item)
    await session.flush()
    return user, theirs, item


def _sent(user, text, minutes_ago=1):
    from app.models import Signal

    return Signal(user_id=user.id, source="mail_sent", kind="mail_sent", external_id=uuid.uuid4().hex, title="Re: J&T Cargo // OpenAI",
                  body=text, payload={"thread_id": "th-1"}, status="ignored", occurred_at=datetime.now(UTC) - timedelta(minutes=minutes_ago))


@db
async def test_reply_that_settles_it_closes_the_item(monkeypatch):
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.models import User
    from app.proactive import items, llm

    async def settled(system, prompt, tool):
        assert "Joining now" in prompt and "Will you be attending" in prompt
        return {"needs_response": False, "summary": "你确认了现在参会"}

    monkeypatch.setattr(llm, "complete_structured", settled)
    async with SessionLocal() as session:
        user, theirs, item = await _setup(session)
        session.add(_sent(user, "Joining now, see you."))
        await session.commit()
        try:
            await items.advance(session, user)
            await session.refresh(item)
            assert item.status == "done" and item.resolution == "你确认了现在参会"
        finally:
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()


@db
async def test_reply_that_asks_back_waits_with_fresh_fields_then_counterpart_invite_closes_it(monkeypatch):
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.models import PendingAction, Signal, User
    from app.proactive import items, llm

    async def waits(system, prompt, tool):
        return {"needs_response": True, "summary": "等 Zorvan 确认改到周三"}

    monkeypatch.setattr(llm, "complete_structured", waits)
    async with SessionLocal() as session:
        user, theirs, item = await _setup(session)
        session.add(_sent(user, "Can we move it to Wednesday?"))
        await session.commit()
        try:
            await items.advance(session, user)
            await session.refresh(item)
            # 转成“等别人”时，紧急、截止、该你回复这些旧内容都换掉
            assert (item.kind, item.owner, item.importance, item.due_at) == ("waiting", "others", "normal", None)
            assert item.summary == "等 Zorvan 确认改到周三" and item.title == "等 Zorvan 回复"
            line = await items.context_line(session, item, user.timezone)
            assert "Zorvan" in line and "你" in line and "已回复：Can we move it" in line

            # Relay 起草了跟进邮件；对方另外发来了会议邀请（另一个线程、另一个发件地址，同一个人）
            followup = PendingAction(user_id=user.id, kind="send_mail", summary="跟进 Zorvan", signal_id=theirs.id, payload={"body": "following up"})
            session.add(followup)
            await session.flush()
            item.action_id = followup.id
            session.add(Signal(user_id=user.id, source="mail", kind="mail", external_id=uuid.uuid4().hex,
                               title="Invitation: J&T Cargo // OpenAI @ Wed", status="tracked",
                               payload={"thread_id": "th-2", "from_name": "Zorvan", "from_address": "zorvan@calendar.example.com"},
                               occurred_at=datetime.now(UTC) + timedelta(seconds=5)))
            await session.commit()
            await items.advance(session, user)
            await session.refresh(item)
            await session.refresh(followup)
            assert item.status == "done" and "会议邀请" in item.resolution
            assert followup.status == "cancelled"  # 起草的跟进邮件不会再发
        finally:
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()


@db
async def test_informational_reply_in_waited_thread_closes_and_reports():
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.models import Signal, User
    from app.proactive import items

    async with SessionLocal() as session:
        user, theirs, item = await _setup(session)
        item.kind, item.owner, item.waiting_on = "waiting", "others", "Zorvan"
        thanks = Signal(user_id=user.id, source="mail", kind="mail", external_id=uuid.uuid4().hex, title="Re: J&T Cargo // OpenAI",
                        summary="对方说收到，周三见", status="notify", importance="low",
                        payload={"thread_id": "th-1", "from_name": "Zorvan", "action_type": "fyi"}, occurred_at=datetime.now(UTC))
        session.add(thanks)
        await session.commit()
        try:
            # 低优先级（只是致谢/告知）也要能结束“等对方回复”
            await items.track(session, None, user)
            await session.refresh(item)
            assert item.status == "done" and "周三见" in item.resolution
            facts = await items.result_facts(session, user)
            assert facts == ["Zorvan 回复了《Re: J&T Cargo // OpenAI》：对方说收到，周三见"]
        finally:
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()


@db
async def test_group_answer_resolves_waiting_chat_item(monkeypatch):
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, Signal, User
    from app.proactive import chats

    chat_id = f"oc_{uuid.uuid4().hex[:10]}"

    async def resolved(system, prompt, tool):
        assert "<open>" in prompt and "已经同步给需求人了" in prompt
        item_id = int(prompt.split("[#", 1)[1].split("]", 1)[0])
        return {"tasks": [], "resolved": [{"item_id": item_id, "evidence": "Nikki 说已经同步给需求人了"}]}

    monkeypatch.setattr(chats, "complete_structured", resolved)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        item = FollowUp(user_id=user.id, key=f"chat:om_x:{user.id}", kind="waiting", owner="others",
                        title="等 Nikki：把需求进度同步给需求人", url=chats.chat_link(chat_id), signal_ids=[])
        # 答复的人不是 Relay 用户、也没 @ 任何人：以前这段消息会被直接跳过
        session.add_all([item, ChatMessage(message_id=f"om_{uuid.uuid4().hex}", chat_id=chat_id, sender_open_id="ou_nikki",
                                           sender_name="Nikki", text="已经同步给需求人了")])
        await session.commit()
        try:
            await chats.extract(session, None, only_chats=[chat_id])
            await session.refresh(item)
            assert item.status == "done" and "已经同步" in item.resolution
            note = (await session.execute(select(Signal).where(Signal.user_id == user.id, Signal.kind == "chat_result"))).scalars().one()
            assert note.status == "result" and "Nikki" in note.title
        finally:
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat_id))
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()
