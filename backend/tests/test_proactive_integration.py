"""主动流程的集成测试：真实数据库 + 假飞书 + 假模型。

    docker compose run --rm -e RUN_DB_TESTS=1 api pytest
"""

import base64
import email
import email.policy
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


def b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


THREADS = {"m1": "th-m1", "m2": "th-q", "m3": "th-q"}


class FakeFeishu:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.cards: list[dict] = []
        self.texts: list[str] = []
        self.mail_ids = ["m1"]
        self.sent_ids: list[str] = []  # 用户自己（在 Relay 之外）发出的邮件
        self.meeting_start = datetime.now(UTC) + timedelta(minutes=10)

    async def bot_open_id(self):
        return "ou_bot"

    async def user_name(self, open_id):
        return {"ou_boss": "李总", "ou_other": "王五"}.get(open_id)

    async def send_card(self, open_id, card, fallback):
        self.cards.append(card)
        return f"om_card_{uuid.uuid4().hex}"

    async def send_text(self, open_id, text):
        self.texts.append(text)

    async def tenant_api(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/approval/v4/tasks/query":
            if getattr(self, "approved", False) or kwargs["params"]["topic"] != "1":
                return {"tasks": []}
            return {"tasks": [{"task_id": "t1", "title": "采购申请", "initiator_names": ["张三"], "urls": {"pc": "https://x/approve"},
                               "process_code": "INST-1", "definition_code": "DEF-1"}]}
        if path == "/approval/v4/instances/INST-1":
            return {"approval_name": "采购申请", "serial_number": "001", "start_time": "1760400000000",
                    "form": '[{"name": "采购内容", "value": "仓库叉车维修"}, {"name": "金额", "value": "12000"}]'}
        if path == "/approval/v4/tasks/approve":
            self.approved = True
            return {}
        if path.startswith("/im/v1/messages/om_card_"):
            self.refreshed = kwargs["json"]["content"]
            return {}
        if path == "/attendance/v1/user_tasks/query":
            return {"user_task_results": []}
        if path.startswith("/im/v1/chats/"):
            return {"name": "印尼报价群"}
        raise AssertionError(path)

    async def user_api(self, user, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/calendar/v4/calendars/primary":
            return {"calendars": [{"calendar": {"calendar_id": "cal1"}}]}
        if path.endswith("/events/instance_view"):
            start = int(self.meeting_start.timestamp())
            return {"items": [
                {"event_id": "e1", "summary": "周会", "start_time": {"timestamp": str(start)},
                 "end_time": {"timestamp": str(start + 1800)}, "self_rsvp_status": "accept",
                 "attendees": [{"type": "user", "display_name": "李四"}]},
                {"event_id": "e2", "summary": "客户评审", "start_time": {"timestamp": str(start + 86400)},
                 "end_time": {"timestamp": str(start + 90000)}, "self_rsvp_status": "needs_action"},
            ]}
        if path == "/mail/v1/user_mailboxes/me/messages":
            return {"items": self.sent_ids if kwargs["params"]["folder_id"] == "SENT" else self.mail_ids}
        if path.startswith("/mail/v1/user_mailboxes/me/messages/"):
            message_id = path.rsplit("/", 1)[1]
            if message_id.startswith("sent"):
                return {"message": {"subject": "Re: 报价确认", "thread_id": "th-m1", "to": [{"mail_address": "a@client.com"}],
                                    "internal_date": str(int(datetime.now(UTC).timestamp() * 1000) + 1000)}}
            return {"message": {
                "subject": "报价确认", "head_from": {"name": "客户A", "mail_address": "a@client.com"},
                "to": [{"mail_address": "me@co.com"}, {"name": "Bob", "mail_address": "bob@client.com"}],
                "cc": [{"name": "Lily", "mail_address": "lily@co.com"}], "internal_date": str(int(datetime.now(UTC).timestamp() * 1000)),
                "body_plain_text": b64url("请今天确认印尼线的报价，谢谢"), "smtp_message_id": f"<{message_id}@client.com>",
                "thread_id": THREADS[message_id],
            }}
        if path == "/mail/v1/user_mailboxes/me/drafts":
            self.draft_raw = kwargs["json"]["raw"]
            return {"draft": {"id": "d1"}}
        if path.endswith("/drafts/d1/send"):
            return {"message_id": "sent1"}
        if path.endswith("/events/e2/reply"):
            return {}
        if path == "/search/v2/doc_wiki/search":
            return {"res_units": []}
        if path == "/mail/v1/user_mailboxes/me/profile":
            return {"primary_email_address": "me@co.com"}
        if path.startswith("/contact/v3/users/"):
            return {"user": {"name": "上级", "leader_user_id": None}}
        raise AssertionError(path)


def buttons(card: dict) -> list[dict]:
    """卡片里所有按钮的回调值（包括折叠面板里的）。"""
    found = []

    def walk(elements):
        for el in elements:
            if el["tag"] == "column_set":
                found.extend(col["elements"][0]["behaviors"][0].get("value") for col in el["columns"])
            elif el["tag"] == "collapsible_panel":
                walk(el["elements"])

    walk(card["body"]["elements"])
    return found


async def test_follow_up_lifecycle(monkeypatch):
    from app.api import feishu_events
    from app.api.conversations import _ordered_messages, serialize_messages
    from app.db import SessionLocal, engine
    from app.home import home_conversation
    from app.memory import service as memory_service
    from app.models import ChatMessage, FeishuCard, FollowUp, PendingAction, Signal, User
    from app.proactive import actions, callbacks, items
    from app.proactive import engine as proactive

    async def no_embedding(text):
        return None

    async def fake_structured(system, prompt, tool):
        return {"importance": "urgent", "notify_now": True, "needs_reply": True, "action_type": "reply",
                "due": "today", "summary": "客户要求今天确认报价", "reason": "客户催办且与你负责的线路相关"}

    async def fake_text(system, prompt):
        return "您好，报价【待确认：价格】今天内回复。"

    monkeypatch.setattr(memory_service, "embed", no_embedding)
    monkeypatch.setattr(proactive, "complete_structured", fake_structured)
    for module in (proactive, actions, items):
        monkeypatch.setattr(module, "complete_text", fake_text)
    monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
    # 这里验证事项的完整生命周期，不验证提醒节奏：每一轮都当作到了汇总时间（节奏见 test_attention）
    from app.proactive import attention
    monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: True)

    feishu = FakeFeishu()
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="阿明", timezone="Asia/Jakarta",
                    email="me@co.com", feishu_user_id="emp1")
        session.add(user)
        await session.commit()
        user_id, open_id = user.id, user.feishu_open_id

    async def run():
        async with SessionLocal() as session:
            await proactive.run_for_user(session, feishu, await session.get(User, user_id))

    async def sync_now():
        async with SessionLocal() as session:
            await proactive.sync_sources(session, feishu, await session.get(User, user_id), proactive.merged({}), force=True)

    async def all_items():
        async with SessionLocal() as session:
            result = await session.execute(select(FollowUp).where(FollowUp.user_id == user_id).order_by(FollowUp.id))
            return {i.key: i for i in result.scalars()}

    try:
        # 第一轮：审批、邀请是新的 → 建成事项并告诉他；存量邮件只静默建档、不起草
        await run()
        found = await all_items()
        assert found["approval:t1"].owner == "me" and found["approval:t1"].announced_at
        invite = found["invite:e2"]
        assert invite.recommendation == "那个时段你没有别的安排，建议接受" and invite.action_id
        silent = found["mail-thread:th-m1"]
        assert silent.kind == "reply" and silent.action_id is None

        # 用户在 Relay 之外自己回了这封信（出现在已发送里）→ 这件事转成“等对方回复”
        feishu.sent_ids = ["sent-1"]
        await sync_now()
        await run()
        replied = (await all_items())["mail-thread:th-m1"]
        assert (replied.kind, replied.owner) == ("waiting", "others")
        assert "采购申请" in str(feishu.cards) and "客户评审" in str(feishu.cards)
        assert any("周会" in c["header"]["title"]["content"] for c in feishu.cards)  # 会前准备

        # 新邮件：先起草，再告诉他；卡片上的按钮对应这封邮件的发送
        feishu.mail_ids = ["m2", "m1"]
        await sync_now()
        await run()
        reply = (await all_items())["mail-thread:th-q"]
        assert (reply.kind, reply.owner, reply.importance) == ("reply", "me", "urgent")
        async with SessionLocal() as session:
            action = await session.get(PendingAction, reply.action_id)
            assert action.status == "pending" and "待确认" in action.payload["body"]
        assert {"relay": "confirm", "action_id": reply.action_id} in buttons(feishu.cards[-1])
        assert not any("/drafts" in path for _, path, _ in feishu.calls)  # 起草时不碰邮箱

        # 主线里是事项卡片，带最新状态
        async with SessionLocal() as session:
            home = await home_conversation(session, await session.get(User, user_id))
            messages = await serialize_messages(session, await _ordered_messages(session, home.id))
        last_card = messages[-1]["cards"][-1]
        assert last_card["kind"] == "item" and last_card["item"]["action"]["status"] == "pending"

        # 原邮件还有其他收件人：默认只回复发件人，改成回复全部后抄送他们（不含自己）
        async with SessionLocal() as session:
            action = await session.get(PendingAction, reply.action_id)
            assert action.payload["reply_all"] is False and len(action.payload["others"]) == 2
            actions.update_draft(action, reply_all=True)
            await session.commit()

        # 别人点无效；本人确认后才发出
        await callbacks.handle_card_action(feishu, "ou_someone_else", {"relay": "confirm", "action_id": reply.action_id})
        assert not any(path.endswith("/send") for _, path, _ in feishu.calls)
        await callbacks.handle_card_action(feishu, open_id, {"relay": "confirm", "action_id": reply.action_id})
        eml = email.message_from_bytes(base64.urlsafe_b64decode(feishu.draft_raw + "=="), policy=email.policy.default)
        assert eml["In-Reply-To"] == "<m2@client.com>" and eml["Subject"] == "Re: 报价确认"
        assert "bob@client.com" in eml["Cc"] and "lily@co.com" in eml["Cc"] and "me@co.com" not in eml["Cc"]

        # 发出后：变成等对方回复
        await run()
        waiting = (await all_items())["mail-thread:th-q"]
        assert (waiting.kind, waiting.owner, waiting.waiting_on) == ("waiting", "others", "客户A")

        # 三天没回：提醒，并起草一封跟进邮件（仍要确认）
        async with SessionLocal() as session:
            item = await session.get(FollowUp, waiting.id)
            item.remind_at = datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()
        await run()
        nudged = (await all_items())["mail-thread:th-q"]
        assert nudged.nudges == 1 and nudged.action_id
        async with SessionLocal() as session:
            follow_up = await session.get(PendingAction, nudged.action_id)
            assert follow_up.status == "pending" and follow_up.summary.startswith("跟进")

        # 对方回复了（同一线程）：又变成等你回复
        feishu.mail_ids = ["m3"]
        await sync_now()
        await run()
        back = (await all_items())["mail-thread:th-q"]
        assert (back.kind, back.owner, back.status) == ("reply", "me", "open")
        assert "对方回复了" in (back.recommendation or "")

        # 邀请：按建议接受 → 回复飞书 → 事项关闭
        await callbacks.handle_card_action(feishu, open_id, {"relay": "confirm", "action_id": invite.action_id})
        replied = [kw for _, path, kw in feishu.calls if path.endswith("/events/e2/reply")]
        assert replied and replied[0]["json"] == {"rsvp_status": "accept"}
        await run()
        assert (await all_items())["invite:e2"].status == "done"

        # 群里有人@他：先盯着，他在群里说话就算回复了
        message = {"chat_id": "oc_1", "message_id": f"om_{uuid.uuid4().hex}", "message_type": "text", "content": '{"text":"@_user_1 报价呢"}'}
        await feishu_events._watch_group_message(feishu, message, "ou_other", [open_id])
        await feishu_events._watch_group_message(feishu, {**message, "message_id": "om_reply"}, open_id, [])
        async with SessionLocal() as session:
            mention = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.kind == "mention"))).scalars().one()
            assert mention.status == "done"

        # 审批：事项里有表单明细；在卡片上点“批准” → 以他的身份批准 → 事项关闭 → 卡片原地刷新
        async with SessionLocal() as session:
            approval_item = await items.item_json(session, await session.get(FollowUp, found["approval:t1"].id))
        assert {"name": "金额", "value": "12000"} in approval_item["detail"]
        async with SessionLocal() as session:
            approval_card = (await session.execute(
                select(FeishuCard).where(FeishuCard.user_id == user_id).order_by(FeishuCard.created_at)
            )).scalars().first()
        result = await callbacks.handle_card_action(
            feishu, open_id, {"relay": "approval", "signal_id": found["approval:t1"].signal_ids[-1], "approve": True},
            approval_card.message_id,
        )
        approve = [kw for _, path, kw in feishu.calls if path == "/approval/v4/tasks/approve"]
        assert approve[0]["json"] == {"approval_code": "DEF-1", "instance_code": "INST-1", "user_id": open_id, "task_id": "t1", "comment": ""}
        assert (await all_items())["approval:t1"].status == "done"
        assert result["ok"] and "~~" in str(result["card"])  # 新卡片随回调响应返回，显示为已处理

        # 需要审批人补填（例如分配 IT 处理人）的单子：不能直接批准，只能去飞书原生审批
        async with SessionLocal() as session:
            needs_fill = Signal(
                user_id=user_id, source="approval", kind="approval_pending", external_id="t2", title="需求申请",
                status="tracked", url="https://x/approve2",
                payload={"task_id": "t2", "process_code": "INST-2", "definition_code": "DEF-2",
                         "detail": {"fields": [], "needs_input": True, "input_hint": "IT 处理人"}},
            )
            session.add(needs_fill)
            await session.commit()
            needs_fill_id = needs_fill.id
        approvals_before = len([1 for _, path, _ in feishu.calls if path == "/approval/v4/tasks/approve"])
        result = await callbacks.handle_card_action(feishu, open_id, {"relay": "approval", "signal_id": needs_fill_id, "approve": True})
        assert not result["ok"] and "去飞书审批" in result["message"] and "IT 处理人" in result["message"]
        assert len([1 for _, path, _ in feishu.calls if path == "/approval/v4/tasks/approve"]) == approvals_before

        # “我已处理”按钮
        await callbacks.handle_card_action(feishu, open_id, {"relay": "item_done", "item_id": back.id})
        assert (await all_items())["mail-thread:th-q"].status == "done"
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, user_id))
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id.in_(["oc_1", "oc_9"])))
            await session.commit()
        await engine.dispose()


async def test_group_chat_tasks(monkeypatch):
    from app.api import feishu_events
    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, Signal, User
    from app.proactive import chats

    seen_prompts = []

    async def fake_tasks(system, prompt, tool):
        seen_prompts.append(prompt)
        return {"tasks": [
            {"message_ref": 0, "requester": "李总", "assignee": "阿明", "task": "周五前把印尼线报价发给李总", "due": "this_week"},
            {"message_ref": 1, "requester": "阿明", "assignee": "Andrew", "task": "整理 9 月运单明细", "due": "today"},
        ]}

    monkeypatch.setattr(chats, "complete_structured", fake_tasks)
    feishu = FakeFeishu()
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="阿明", timezone="Asia/Jakarta", email="me@co.com")
        session.add(user)
        await session.commit()
        user_id, open_id = user.id, user.feishu_open_id
    try:
        boss = {"chat_id": "oc_9", "message_id": f"om_{uuid.uuid4().hex}", "message_type": "text",
                "content": '{"text":"@_user_1 周五前把印尼线报价发我"}',
                "mentions": [{"key": "@_user_1", "id": {"open_id": open_id}, "name": "阿明"}]}
        await feishu_events._watch_group_message(feishu, boss, "ou_boss", [open_id])
        mine = {"chat_id": "oc_9", "message_id": f"om_{uuid.uuid4().hex}", "message_type": "text",
                "content": '{"text":"@_user_1 今天把 9 月运单明细整理一下"}',
                "mentions": [{"key": "@_user_1", "id": {"open_id": "ou_andrew"}, "name": "Andrew"}]}
        await feishu_events._watch_group_message(feishu, mine, open_id, ["ou_andrew"])

        async with SessionLocal() as session:
            await chats.extract(session, feishu, only_chats=["oc_9"])
        # 模型看到的是人名，不是 @_user_1
        assert "@阿明 周五前把印尼线报价发我" in seen_prompts[0] and "@_user_1" not in seen_prompts[0]

        async with SessionLocal() as session:
            found = {i.kind: i for i in (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars()}
            assert found["request"].owner == "me" and "报价" in found["request"].title and found["request"].due_at
            assert found["waiting"].owner == "others" and found["waiting"].waiting_on == "Andrew"
            # 已经建成待办的那条@，不再单独提醒“没回”
            mention = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.kind == "mention"))).scalars().one()
            assert mention.status == "done"

        # 再跑一遍不会重复提取
        async with SessionLocal() as session:
            await chats.extract(session, feishu, only_chats=["oc_9"])
        assert len(seen_prompts) == 1
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, user_id))
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id.in_(["oc_1", "oc_9"])))
            await session.commit()
        await engine.dispose()
