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


class Judge:
    """按剧本给出判断，并记下每次被问了什么。"""

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    async def __call__(self, system, prompt, tool):
        self.prompts.append(prompt)
        return self.answers.pop(0)


@db
async def test_reply_that_asks_back_waits_then_only_a_real_answer_closes_it(monkeypatch):
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import PendingAction, Signal, User
    from app.proactive import items, llm

    judge = Judge(
        {"needs_response": True, "summary": "等 Zorvan 确认改到周三"},  # 他问能不能改期
        {"verdict": "unrelated", "evidence": "Zorvan 发来的是周报，和改期无关"},  # 另一个线程：无关
        {"verdict": "committed", "evidence": "Zorvan 说明天上午确认", "due": "2026-10-21T10:00:00"},
        {"verdict": "done", "evidence": "Zorvan 发来周三的会议邀请"},
    )
    monkeypatch.setattr(llm, "complete_structured", judge)
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
            assert "Zorvan" in line and "已回复：Can we move it" in line

            followup = PendingAction(user_id=user.id, kind="send_mail", summary="跟进 Zorvan", signal_id=theirs.id, payload={"body": "following up"})
            session.add(followup)
            await session.flush()
            item.action_id = followup.id

            def other_mail(title, thread, address):
                return Signal(user_id=user.id, source="mail", kind="mail", external_id=uuid.uuid4().hex, title=title,
                              body=title, status="tracked", occurred_at=datetime.now(UTC) + timedelta(seconds=5),
                              payload={"thread_id": thread, "from_name": "Zorvan", "from_address": address})

            # 1) 同一个人发来无关的周报：判断为无关，什么都不变，也不会反复判断同一封
            session.add(other_mail("Weekly report", "th-9", "zorvan@example.com"))
            await session.commit()
            await items.advance(session, user)
            await items.advance(session, user)
            await session.refresh(item)
            assert item.status == "open" and len(judge.prompts) == 2 and "确认改到周三" in judge.prompts[1]

            # 2) 对方答应了时间：不关闭，改成到时候核实；起草的“跟进一下”作废
            session.add(other_mail("Re: schedule", "th-8", "zorvan@example.com"))
            await session.commit()
            await items.advance(session, user)
            await session.refresh(item)
            await session.refresh(followup)
            assert item.status == "open" and item.summary.startswith("对方答应了") and item.remind_at.day == 21
            assert followup.status == "cancelled"

            # 3) 发来会议邀请（另一个线程、另一个发件地址，同一个人）：判断为办完了才关闭
            session.add(other_mail("Invitation: J&T // OpenAI @ Wed", "th-2", "zorvan@calendar.example.com"))
            await session.commit()
            await items.advance(session, user)
            await session.refresh(item)
            assert item.status == "done" and "会议邀请" in item.resolution
            notes = (await session.execute(select(Signal.title).where(Signal.user_id == user.id, Signal.kind == "progress"))).scalars().all()
            assert any("答应了" in n for n in notes) and any("有结果了" in n for n in notes)
        finally:
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()


@db
async def test_reply_in_waited_thread_is_judged_not_assumed(monkeypatch):
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.models import Signal, User
    from app.proactive import items, llm

    judge = Judge({"verdict": "ack", "evidence": "Zorvan 说收到，还在看"}, {"verdict": "done", "evidence": "Zorvan 确认周三可以"})
    monkeypatch.setattr(llm, "complete_structured", judge)
    async with SessionLocal() as session:
        user, theirs, item = await _setup(session)
        item.kind, item.owner, item.waiting_on, item.summary = "waiting", "others", "Zorvan", "等 Zorvan 确认改到周三"

        def reply(text):
            return Signal(user_id=user.id, source="mail", kind="mail", external_id=uuid.uuid4().hex, title="Re: J&T Cargo // OpenAI",
                          summary=text, body=text, status="notify", importance="low",
                          payload={"thread_id": "th-1", "from_name": "Zorvan", "action_type": "fyi"}, occurred_at=datetime.now(UTC))

        session.add(reply("收到，我看一下"))
        await session.commit()
        try:
            # 只是“收到”：回复了不等于办完，事情继续等，但告诉他对方说了什么
            await items.track(session, None, user)
            await session.refresh(item)
            assert item.status == "open" and item.summary == "对方回复了：Zorvan 说收到，还在看"
            assert "确认改到周三" in judge.prompts[0]
            session.add(reply("周三可以"))
            await session.commit()
            await items.track(session, None, user)
            await session.refresh(item)
            assert item.status == "done" and item.resolution == "Zorvan 确认周三可以"
            facts = await items.result_facts(session, user)
            assert facts == ["Zorvan 回复了：Zorvan 说收到，还在看", "Zorvan 那边有结果了：Zorvan 确认周三可以"]
        finally:
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()


@db
async def test_chat_progress_done_vs_committed_and_private_chat_stays_private(monkeypatch):
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, Signal, User
    from app.proactive import chats

    group, private = f"oc_{uuid.uuid4().hex[:10]}", f"oc_{uuid.uuid4().hex[:10]}"
    seen = []

    async def model(system, prompt, tool):
        seen.append(prompt)
        item_id = int(prompt.split("[#", 1)[1].split("]", 1)[0]) if "[#" in prompt else None
        if group in "".join(seen[-1:]) or "群聊" in prompt:
            if "已经同步给需求人了" in prompt:
                return {"tasks": [], "progress": [{"item_id": item_id, "verdict": "done", "evidence": "Nikki 说已经同步给需求人了"}]}
            return {"tasks": [], "progress": [{"item_id": item_id, "verdict": "committed", "evidence": "Nikki 说月底前完成", "due": "2026-10-31T18:00:00"}]}
        # 私聊：对方让他周五前交报表
        return {"tasks": [{"message_ref": 0, "requester": "Zorvan", "assignee": "Quillan", "task": "周五前交报表", "due": "this_week"}], "progress": []}

    monkeypatch.setattr(chats, "complete_structured", model)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        other = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Zorvan", timezone="Asia/Jakarta")
        session.add_all([user, other])
        await session.flush()
        item = FollowUp(user_id=user.id, key=f"chat:om_x:{user.id}", kind="waiting", owner="others",
                        title="等 Nikki：把需求进度同步给需求人", url=chats.chat_link(group), signal_ids=[])
        session.add_all([item, ChatMessage(message_id=f"om_{uuid.uuid4().hex}", chat_id=group, sender_open_id="ou_nikki",
                                           sender_name="Nikki", text="1，预计月底前完成")])
        await session.commit()
        try:
            # 答应了时间：不关闭，改成到时候核实
            await chats.extract(session, None, only_chats=[group])
            await session.refresh(item)
            assert item.status == "open" and item.summary.startswith("对方答应了") and item.due_at.month == 10 and item.due_at.day == 31
            # 真正的结果：关闭并告诉他
            session.add(ChatMessage(message_id=f"om_{uuid.uuid4().hex}", chat_id=group, sender_open_id="ou_nikki",
                                    sender_name="Nikki", text="已经同步给需求人了"))
            await session.commit()
            await chats.extract(session, None, only_chats=[group])
            await session.refresh(item)
            assert item.status == "done" and "已经同步" in item.resolution
            notes = (await session.execute(select(Signal.title).where(Signal.user_id == user.id, Signal.kind == "chat_result"))).scalars().all()
            assert len(notes) == 2

            # 私聊：只给读取它的那位用户建事项；另一方即使是 Relay 用户也不替他建；私聊不当别人的背景
            session.add(ChatMessage(message_id=f"om_{uuid.uuid4().hex}", chat_id=private, sender_open_id=other.feishu_open_id,
                                    sender_name="Zorvan", text="你周五前把报表交给我", owner_user_id=user.id))
            await session.commit()
            await chats.extract(session, None, only_chats=[private])
            mine = (await session.execute(select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.url == chats.chat_link(private)))).scalars().all()
            theirs = (await session.execute(select(FollowUp).where(FollowUp.user_id == other.id))).scalars().all()
            assert [i.kind for i in mine] == ["request"] and "私聊" in mine[0].next_step and theirs == []
            assert await chats.related(session, ["报表"]) == []
        finally:
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id.in_([group, private])))
            await session.execute(delete(User).where(User.id.in_([user.id, other.id])))
            await session.commit()
            await engine.dispose()


@db
async def test_mail_sync_is_idempotent_and_skips_missing_mailbox(monkeypatch):
    from sqlalchemy import delete, func, select

    from app.db import SessionLocal, engine
    from app.feishu.client import FeishuError
    from app.models import Signal, SourceState, User
    from app.proactive import engine as proactive
    from app.proactive.settings import merged

    class MailFeishu:
        def __init__(self):
            self.no_mailbox = False

        async def user_api(self, user, method, path, **kwargs):
            if self.no_mailbox:
                raise FeishuError("user not found", 15180001)
            if path.endswith("/messages") and kwargs["params"]["folder_id"] == "INBOX":
                return {"items": ["m1", "m2"]}
            if path.endswith("/messages") and kwargs["params"]["folder_id"] == "SENT":
                return {"items": ["s1"]}
            message_id = path.rsplit("/", 1)[1]
            return {"message": {"subject": f"主题 {message_id}", "head_from": {"name": "Zorvan", "mail_address": "z@example.com"},
                                "thread_id": f"th-{message_id}", "label_ids": ["UNREAD"], "internal_date": str(int(datetime.now(UTC).timestamp() * 1000)),
                                "body_plain_text": ""}}

        async def granted_user_scopes(self):
            return []

    feishu = MailFeishu()
    settings = merged({"sources": {"calendar": False, "approval": False, "attendance": False}})
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.commit()
        try:
            count = select(func.count(Signal.id)).where(Signal.user_id == user.id)
            await proactive.sync_sources(session, feishu, user, settings, force=True)
            first = await session.scalar(count)
            await proactive.sync_sources(session, feishu, user, settings, force=True)
            await proactive.sync_sources(session, feishu, user, settings, force=True)
            assert first == 3 and await session.scalar(count) == 3  # 2 封收件 + 1 封已发送，重复同步不重复

            # 没有开通邮箱：记下，跳过，一天后自动再检测；开通后恢复
            feishu.no_mailbox = True
            await proactive.sync_sources(session, feishu, user, settings, force=True)
            state = (await session.execute(select(SourceState).where(SourceState.user_id == user.id, SourceState.source == "mail"))).scalars().one()
            assert "unavailable_until" in state.cursor and "没有开通" in state.last_error
            calls_before = state.last_synced_at
            await proactive.sync_sources(session, feishu, user, settings, force=True)  # 还没到时间：不再请求
            await session.refresh(state)
            assert state.last_synced_at == calls_before
            feishu.no_mailbox = False
            state.cursor = {**state.cursor, "unavailable_until": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
            await session.commit()
            await proactive.sync_sources(session, feishu, user, settings, force=True)
            await session.refresh(state)
            assert "unavailable_until" not in state.cursor and state.last_error is None
        finally:
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()


@db
async def test_private_chat_sync_contacts_increments_and_scope():
    from sqlalchemy import delete, func, select

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, PendingAction, SourceState, User
    from app.proactive import engine as proactive
    from app.proactive.settings import merged
    from app.sources import p2p

    now_ms = int(datetime.now(UTC).timestamp() * 1000)

    class Feishu:
        def __init__(self):
            self.items = []

        async def user_api(self, user, method, path, **kwargs):
            if path == "/im/v1/chat_p2p/batch_query":
                assert "ou_zorvan" in kwargs["json"]["chatter_ids"]
                return {"p2p_chats": [{"chat_id": "oc_p2p_z", "chatter_id1": user.feishu_open_id, "chatter_id2": "ou_zorvan"}]}
            if path == "/im/v1/messages":
                return {"items": self.items}
            if path.startswith("/contact/"):
                return {}
            raise AssertionError(path)

        async def user_name(self, open_id):
            return {"ou_zorvan": "Zorvan"}.get(open_id)

        async def granted_user_scopes(self):
            return []

    def msg(mid, sender, text, offset_s):
        return {"message_id": mid, "sender": {"id": sender, "sender_type": "user"}, "msg_type": "text",
                "body": {"content": '{"text": "%s"}' % text}, "create_time": str(now_ms + offset_s * 1000)}

    feishu = Feishu()
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta",
                    feishu_scopes="im:message im:message.p2p_msg:get_as_user")
        session.add(user)
        await session.flush()
        session.add(PendingAction(user_id=user.id, kind="send_chat", summary="给 Zorvan", status="done",
                                  payload={"receive_id": "ou_zorvan", "receive_id_type": "open_id"}))
        await session.commit()
        try:
            assert await p2p.contacts(session, feishu, user) == ["ou_zorvan"]
            settings = merged({"sources": {"mail": False, "calendar": False, "approval": False, "attendance": False, "private_chat": True}})
            feishu.items = [msg("om_a", "ou_zorvan", "你周五前把报表给我", -60), msg("om_b", user.feishu_open_id, "好的", -30)]
            await proactive.sync_sources(session, feishu, user, settings, force=True)
            await proactive.sync_sources(session, feishu, user, settings, force=True)  # 同样的消息再来一遍不重复
            rows = (await session.execute(select(ChatMessage).where(ChatMessage.owner_user_id == user.id).order_by(ChatMessage.created_at))).scalars().all()
            assert [(m.sender_name, m.text) for m in rows] == [("Zorvan", "你周五前把报表给我"), ("Quillan", "好的")]
            assert rows[0].chat_name == "和 Zorvan 的私聊"

            # 没有私聊读取授权：不读，提示重新登录
            user.feishu_scopes = "im:message"
            await session.commit()
            feishu.items = [msg("om_c", "ou_zorvan", "还有一件事", 5)]
            await proactive.sync_sources(session, feishu, user, settings, force=True)
            state = (await session.execute(select(SourceState).where(SourceState.user_id == user.id, SourceState.source == "private_chat"))).scalars().one()
            assert "重新登录" in state.last_error
            assert await session.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.owner_user_id == user.id)) == 2
        finally:
            await session.execute(delete(ChatMessage).where(ChatMessage.owner_user_id == user.id))
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()
