"""同一件事的完整生命周期：跨渠道关联、在 Relay 之外的操作、提醒去重和允许的再次提醒。

场景：Sari 发邮件请 Xavier 确认 Medan 报价 → 私聊里 Xavier 说还在核对、明天给 → 周会纪要写明报价已确认。
三处信息落在同一个事项上，各自保留依据；同一时间 Sari 还在跟他讨论 Batam 排班——同一个人、不同的事，不能被合并或误关。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_attention import Feishu as CardFeishu

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


async def _user(session, tag):
    from app.models import User

    user = User(feishu_open_id=f"ou_x_{tag}", name="Xavier(吴川)", email="xavier@jt.id", timezone="Asia/Jakarta")
    session.add(user)
    await session.flush()
    return user


async def _cleanup(session, user_id, chat=None):
    from sqlalchemy import delete

    from app.db import engine
    from app.models import ChatMessage, User

    await session.rollback()
    if chat:
        await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat))
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()
    await engine.dispose()


@db
async def test_mail_then_private_chat_then_minutes_update_one_matter(monkeypatch):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import ChatMessage, FollowUp, Signal
    from app.proactive import chats, items, meetings
    from app.sources.base import add_signal

    tag = uuid.uuid4().hex[:8]
    chat = f"oc_p_{tag}"
    chat_prompts, minutes_prompts = [], []
    async with SessionLocal() as session:
        user = await _user(session, tag)
        user_id = user.id
        try:
            quote = FollowUp(user_id=user_id, key=f"mail-thread:q-{tag}", kind="reply", owner="me", title="回复 Sari：Medan 报价确认",
                             summary="请 Xavier 确认 Medan 报价", facets={"people": ["Sari"]})
            roster = FollowUp(user_id=user_id, key=f"mail-thread:r-{tag}", kind="reply", owner="me", title="回复 Sari：Batam 排班调整",
                              summary="请确认 Batam 下周排班", facets={"people": ["Sari"]})
            session.add_all([quote, roster])
            await session.flush()
            items.add_evidence(quote, "邮件", "Sari：请确认 Medan 报价")
            await session.commit()

            # ② 私聊：同一个人，说的是报价——关联到邮件里的那件事；Batam 那件不给模型看，模型乱写它的编号也不算
            def message(n, mine, text, minutes):
                return ChatMessage(message_id=f"om_{tag}_{n}", chat_id=chat, owner_user_id=user_id, chat_name="和 Sari 的私聊",
                                   sender_open_id=user.feishu_open_id if mine else "ou_sari", sender_name="Xavier(吴川)" if mine else "Sari",
                                   text=text, mentions=[], created_at=datetime.now(UTC) + timedelta(minutes=minutes))

            session.add_all([message(0, False, "Medan 报价那份你看了吗？", 0), message(1, True, "还在核对，明天给你", 1)])
            await session.commit()

            async def chat_model(system, prompt, tool):
                chat_prompts.append(prompt)
                return {"tasks": [], "asks": [], "progress": [
                    {"item_id": quote.id, "verdict": "committed", "evidence": "你说还在核对 Medan 报价，明天给 Sari"},
                    {"item_id": roster.id, "verdict": "done", "evidence": "（模型写错了编号）"}]}

            monkeypatch.setattr(chats, "complete_structured", chat_model)
            await chats.extract(session, None, only_chats=[chat])
            assert f"[#{quote.id}]（来自邮件）" in chat_prompts[0] and f"#{roster.id}" not in chat_prompts[0]
            await session.refresh(quote)
            await session.refresh(roster)
            assert quote.status == "open" and quote.summary.startswith("你答应了：")  # 他答应了，还没给：仍是未结
            assert roster.status == "open"  # 同一个人、别的事：没有被误关
            assert [e["channel"] for e in quote.facets["evidence"]] == ["邮件", "聊天"]
            assert (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars().all().__len__() == 2  # 没有另建

            # ③ 会议纪要确认报价已定：同一个事项结束，依据来自纪要；纪要也提到 Batam 但没有结论，Batam 不动
            start = datetime.now(UTC) - timedelta(hours=2)
            await add_signal(session, user, "calendar", f"ev_{tag}@1", kind="meeting", title="Medan 周会", occurred_at=start,
                             payload={"event_id": f"ev_{tag}", "end": (start + timedelta(hours=1)).isoformat(), "organizer": "Sari"},
                             status="notified")
            await session.commit()

            class Docs:
                async def user_api(self, user, method, path, **kwargs):
                    if path == "/search/v2/doc_wiki/search":
                        return {"res_units": [{"title_highlighted": "Medan 周会 纪要", "result_meta": {
                            "url": "https://x.feishu.cn/docx/MIN", "update_time": int(datetime.now(UTC).timestamp())}}]}
                    if path.startswith("/docx/v1/documents/MIN"):
                        return {"content": "1. Medan 报价已确认，按 B 方案执行。2. Batam 排班下周再议。"}
                    raise AssertionError(path)

            async def minutes_model(system, prompt, tool):
                minutes_prompts.append(prompt)
                return {"actions": [], "progress": [{"item_id": quote.id, "verdict": "done", "evidence": "Medan 报价已确认，按 B 方案执行"}]}

            monkeypatch.setattr(meetings, "complete_structured", minutes_model)
            await meetings.collect_minutes(session, Docs(), user)
            await session.refresh(quote)
            await session.refresh(roster)
            assert f"[#{quote.id}]（来自邮件）" in minutes_prompts[0]
            assert quote.status == "done" and "会议《Medan 周会》纪要" in quote.resolution
            assert [e["channel"] for e in quote.facets["evidence"]] == ["邮件", "聊天", "会议纪要"]
            assert roster.status == "open"
            assert len((await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars().all()) == 2
            meeting = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.kind == "meeting"))).scalars().one()
            assert meeting.payload["minutes"]["url"] == "https://x.feishu.cn/docx/MIN"
        finally:
            await _cleanup(session, user_id, chat)


@db
async def test_chat_restating_a_mail_request_does_not_create_a_second_item(monkeypatch):
    """跨渠道重复发现：Sari 邮件里提了，又在私聊里催同一件事——同一个事项记下依据，不另建；模型出错重试也不会重复建。"""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import ChatMessage, FollowUp
    from app.proactive import chats, items

    tag = uuid.uuid4().hex[:8]
    chat = f"oc_p_{tag}"
    calls = []
    async with SessionLocal() as session:
        user = await _user(session, tag)
        user_id = user.id
        try:
            quote = FollowUp(user_id=user_id, key=f"mail-thread:q-{tag}", kind="reply", owner="me", title="回复 Sari：Medan 报价确认",
                             summary="请确认 Medan 报价", facets={"people": ["Sari"]})
            session.add(quote)
            session.add(ChatMessage(message_id=f"om_{tag}", chat_id=chat, owner_user_id=user_id, chat_name="和 Sari 的私聊",
                                    sender_open_id="ou_sari", sender_name="Sari", text="哥，Medan 报价麻烦确认一下", mentions=[],
                                    created_at=datetime.now(UTC)))
            await session.commit()

            async def flaky(system, prompt, tool):
                calls.append(prompt)
                if len(calls) == 1:
                    raise RuntimeError("429")  # 第一次限流：消息标回未处理，下一轮重试
                return {"tasks": [], "asks": [], "progress": [{"item_id": quote.id, "verdict": "same", "evidence": "Sari 在私聊里又催了一次"}]}

            monkeypatch.setattr(chats, "complete_structured", flaky)
            await chats.extract(session, None, only_chats=[chat])
            await chats.extract(session, None, only_chats=[chat])
            await chats.extract(session, None, only_chats=[chat])  # 处理过了：不再问模型
            assert len(calls) == 2
            rows = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars().all()
            assert [r.id for r in rows] == [quote.id]
            await session.refresh(quote)
            assert quote.facets["evidence"][-1]["text"] == "Sari 在私聊里又催了一次"
        finally:
            await _cleanup(session, user_id, chat)


@db
async def test_actions_outside_relay_update_the_same_item(monkeypatch):
    """在邮箱里直接回“晚点看”：仍是他的事；在飞书里审批了：结束、没发的草稿作废、卡片跟着更新；
    迟到的旧消息不会重新打开已经结束的事；他说不归他的，同一线程再来信也不重新打开。"""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import FeishuCard, FollowUp, PendingAction, Signal
    from app.proactive import attention, items
    from app.proactive.settings import merged
    from app.sources.base import add_signal

    judged = []

    async def later(theirs, mine, lang="zh"):
        judged.append(mine)
        return "mine", "你答应晚点看报价"

    async def no_post(*args, **kwargs):
        return None

    monkeypatch.setattr(items, "judge_reply", later)
    monkeypatch.setattr(items, "post", no_post)
    monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
    monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: True)
    feishu = CardFeishu()
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = await _user(session, tag)
        user_id = user.id
        try:
            sent_at = datetime.now(UTC) - timedelta(hours=1)
            await add_signal(session, user, "mail", f"m-{tag}", kind="mail", title="Medan 报价", payload={"thread_id": f"th-{tag}", "from_name": "Sari"},
                             occurred_at=sent_at - timedelta(hours=1), status="tracked")
            await add_signal(session, user, "mail", f"s-{tag}", kind="mail_sent", title="Re: Medan 报价", body="收到，晚点看",
                             payload={"thread_id": f"th-{tag}"}, occurred_at=sent_at, status="ignored")
            await add_signal(session, user, "approval", f"ap-{tag}", kind="approval_pending", title="报销", payload={}, status="done")
            await session.flush()
            mail_signal, _, approval_signal = (await session.execute(select(Signal).where(Signal.user_id == user_id).order_by(Signal.id))).scalars().all()
            reply = FollowUp(user_id=user_id, key=f"mail-thread:th-{tag}", kind="reply", owner="me", title="回复 Sari：Medan 报价",
                             signal_ids=[mail_signal.id], facets={"people": ["Sari"]})
            draft = PendingAction(user_id=user_id, kind="approval_decision", summary="批准报销", payload={})
            session.add(draft)
            await session.flush()
            approval = FollowUp(user_id=user_id, key=f"approval:{tag}", kind="approval", owner="me", title="Budi：报销",
                                signal_ids=[approval_signal.id], action_id=draft.id, facets={})
            session.add_all([reply, approval])
            await session.commit()
            await items.announce(session, feishu, user, merged({}), [])
            assert len(feishu.cards) == 1

            await items.advance(session, user)
            await items.advance(session, user)  # 同一封回复只判断一次
            for row in (reply, approval, draft):
                await session.refresh(row)
            assert (reply.status, reply.owner, reply.summary) == ("open", "me", "你答应晚点看报价") and len(judged) == 1
            assert (approval.status, approval.resolution) == ("done", "审批已处理")
            assert draft.status == "cancelled" and draft.result == "事情已经结束，这份草稿作废"
            assert await items.sync_cards(session, feishu, user) == 1 and len(feishu.cards) == 1  # 卡片原地更新，不另发

            # 迟到的旧消息：比这件事结束得还早，不重新打开；之后的新消息可以
            items.close(reply, "done", "你回复了报价")
            await session.commit()
            old = Signal(user_id=user_id, source="mail", kind="mail", external_id=f"old-{tag}", title="Medan 报价",
                         occurred_at=reply.closed_at - timedelta(hours=3), payload={})
            session.add(old)
            await session.flush()
            await items.upsert(session, user, reply.key, old, silent=False, kind="reply", owner="me", title="回复 Sari：Medan 报价")
            assert reply.status == "done" and old.id in reply.signal_ids
            # 他说不归他的：同一线程又来信，也不自动重新打开
            reply.resolution = "你说这件不归你"
            newer = Signal(user_id=user_id, source="mail", kind="mail", external_id=f"new-{tag}", title="Medan 报价",
                           occurred_at=datetime.now(UTC) + timedelta(minutes=1), payload={})
            session.add(newer)
            await session.flush()
            await items.upsert(session, user, reply.key, newer, silent=False, kind="reply", owner="me", title="回复 Sari：Medan 报价")
            assert reply.status == "done"
            reply.resolution = "你回复了报价"
            await items.upsert(session, user, reply.key, newer, silent=False, kind="reply", owner="me", title="回复 Sari：Medan 报价")
            assert reply.status == "open"  # 真正的新消息：重新打开
            assert len((await session.execute(select(FeishuCard).where(FeishuCard.user_id == user_id))).scalars().all()) == 1
        finally:
            await _cleanup(session, user_id)


@db
async def test_dedup_survives_retries_and_restarts_but_real_changes_notify_again(monkeypatch):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.feishu.client import FeishuError
    from app.models import FeishuCard, FollowUp, User
    from app.proactive import attention, items
    from app.proactive.settings import merged

    async def no_post(*args, **kwargs):
        return None

    async def narrate(system, prompt):
        return "有几件事。"

    monkeypatch.setattr(items, "post", no_post)
    monkeypatch.setattr(items, "complete_text", narrate)
    monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
    monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: True)

    class Flaky(CardFeishu):
        def __init__(self):
            super().__init__()
            self.fail = 1

        async def send_card(self, open_id, card, fallback):
            if self.fail:
                self.fail -= 1
                raise FeishuError("网络超时")
            return await super().send_card(open_id, card, fallback)

    feishu = Flaky()
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = await _user(session, tag)
        user_id = user.id
        try:
            item = FollowUp(user_id=user_id, key=f"mail-thread:w-{tag}", kind="waiting", owner="others", title="等 Sari 回复报价",
                            waiting_on="Sari", facets={"people": ["Sari"]})
            session.add(item)
            await session.commit()
            await items.announce(session, feishu, user, merged({}), [])
            assert feishu.cards == [] and item.announced_at is None  # 没发出去：留着下一轮重发
            await items.announce(session, feishu, user, merged({}), [])
            assert len(feishu.cards) == 1
            # 重复同步（同一件事又 upsert 一次、没有新状态）+ 服务重启后再跑：原地更新，不另发
            await items.upsert(session, user, item.key, None, silent=False, kind="waiting", owner="others", title="等 Sari 回复报价")
            await session.commit()
        finally:
            pass
    async with SessionLocal() as session:  # 重启：新的会话、新的对象
        user = await session.get(User, user_id)
        try:
            await items.announce(session, feishu, user, merged({}), [])
            await items.announce(session, feishu, user, merged({}), [])
            assert len(feishu.cards) == 1

            # 从“等对方”变成“要你确认”（Sari 回了，要他拍板）：允许再说一次，旧卡片收成一行
            item = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars().one()
            await items.upsert(session, user, item.key, None, silent=False, kind="reply", owner="me", title="回复 Sari：请你确认报价")
            await session.commit()
            await items.announce(session, feishu, user, merged({}), [])
            assert len(feishu.cards) == 2
            first = (await session.execute(select(FeishuCard).where(FeishuCard.user_id == user_id).order_by(FeishuCard.created_at))).scalars().first()
            assert [c.get("moved") for _, g in first.sections for c in g] == [True]

            # 临近明确的截止时间：再说一次，同一个截止时间只说一次
            item.due_at = datetime.now(UTC) + timedelta(hours=2)
            item.pushed_at = datetime.now(UTC) - timedelta(days=1)
            await session.commit()
            reminders = await items.due_reminders(session, feishu, user)
            assert [fact for _, fact in reminders if "截止" in fact] and item.announced_at is None
            await items.announce(session, feishu, user, merged({}), reminders)
            assert len(feishu.cards) == 3
            assert [fact for _, fact in await items.due_reminders(session, feishu, user) if "截止" in fact] == []
        finally:
            await _cleanup(session, user_id)


@db
async def test_clear_request_without_deadline_or_clear_owner_is_still_tracked(monkeypatch):
    """“请确认这份报价”：没写时间也要进待处理（时间：未约定，不编）；发给一群人、看不出是不是归他，也进，并请他先确认。
    没有任何具体要求的通报才算知会。"""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Signal
    from app.proactive import engine as proactive
    from app.proactive import items
    from app.sources.base import add_signal

    answers = {
        "报价": {"importance": "normal", "notify_now": False, "needs_reply": True, "action_type": "reply", "due": "none",
                 "summary": "请确认报价", "reason": "有明确要求", "ask": "确认这份 Medan 报价", "responsible": "unclear"},
        "通报": {"importance": "low", "notify_now": False, "needs_reply": False, "action_type": "review", "due": "none",
                 "summary": "通报", "reason": "通报"},
    }

    async def classify(system, prompt, tool):
        return answers["报价" if "报价" in prompt else "通报"]

    monkeypatch.setattr(proactive, "complete_structured", classify)
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = await _user(session, tag)
        user_id = user.id
        try:
            for subject in ("报价", "通报"):
                await add_signal(session, user, "mail", f"{subject}-{tag}", kind="mail", title=subject, body=f"请大家确认{subject}",
                                 payload={"from": "Sari", "from_name": "Sari", "to_addresses": [{"mail_address": "ops@jt.id"}]}, status="new")
            await session.commit()
            await proactive.triage(session, user)
            rows = {s.title: s for s in (await session.execute(select(Signal).where(Signal.user_id == user_id))).scalars()}
            assert rows["报价"].status == "notify" and rows["报价"].payload["when"] is None and rows["报价"].payload["responsible"] == "unclear"
            assert rows["通报"].status == "ignored"  # 没有具体要求：知会
            mail = rows["报价"].payload
            assert items.why_line(mail, rows["报价"]) == "还不确定是不是要你负责（时间：未约定）"
            assert items.ask_line(mail, "回复") == "确认这份 Medan 报价（先确认这件事是不是归你）"
        finally:
            await _cleanup(session, user_id)
