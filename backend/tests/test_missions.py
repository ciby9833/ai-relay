"""长期任务的集成测试：真实数据库 + 假飞书 + 按剧本行动的假模型。

    docker compose run --rm -e RUN_DB_TESTS=1 api pytest
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class ScriptedProvider:
    """每次被调用时按顺序给出预先写好的回复（工具调用或文字）。"""

    name = "fake"

    def __init__(self):
        self.turns: list[tuple[list[dict], str]] = []
        self.prompts: list[str] = []

    def add(self, *blocks, stop="tool_use"):
        self.turns.append((list(blocks), stop))

    async def stream(self, *, model, system, messages, tools):
        from app.llm.base import Completion, TextDelta

        last = messages[-1]["content"]
        self.prompts.append("\n".join(b.get("text") or str(b.get("content", "")) for b in last))
        self.tool_names = [t["name"] for t in tools]
        blocks, stop = self.turns.pop(0)
        for block in blocks:
            if block["type"] == "text":
                yield TextDelta(block["text"])
        yield Completion(blocks=blocks, stop_reason=stop)


def call(name, **arguments):
    return {"type": "tool_use", "id": f"call_{uuid.uuid4().hex[:8]}", "name": name, "input": arguments}


class FakeFeishu:
    def __init__(self):
        self.sent: list[dict] = []
        self.cards: list[dict] = []
        self.replies: list[dict] = []  # 以用户身份拉取会话消息时返回的内容

    async def send_card(self, open_id, card, fallback):
        self.cards.append(card)
        return f"om_{uuid.uuid4().hex}"

    async def send_text(self, open_id, text):
        pass

    async def user_api(self, user, method, path, **kwargs):
        if path == "/im/v1/messages" and method == "GET":  # 以用户本人身份查会话里的新消息
            return {"items": self.replies}
        if path == "/im/v1/messages":  # 以用户本人身份发消息
            self.sent.append({**kwargs["json"], "as_user": True})
            return {"message_id": "om_u", "chat_id": "oc_p2p_" + kwargs["json"]["receive_id"]}
        from app.feishu.client import FeishuError

        raise FeishuError("测试中没有用户授权")

    async def tenant_api(self, method, path, **kwargs):
        if path == "/im/v1/messages":
            self.sent.append(kwargs["json"])
            return {"message_id": "om_x"}
        raise AssertionError(path)


async def test_mission_lifecycle(monkeypatch):
    from app.db import SessionLocal, engine
    from app.llm import registry
    from app.memory import service as memory_service
    from app.missions import service
    from app.models import ChatMessage, Mission, MissionLog, PendingAction, Person, User
    from app.proactive import callbacks
    from app.sources import people

    async def no_embedding(text):
        return None

    provider = ScriptedProvider()
    monkeypatch.setattr(memory_service, "embed", no_embedding)
    monkeypatch.setattr(registry, "resolve", lambda model_id: (provider, "fake", "fake:fake"))
    monkeypatch.setattr(service, "in_work_hours", lambda *args, **kwargs: True)
    feishu = FakeFeishu()

    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="阿明", timezone="Asia/Jakarta", email="me@co.com")
        session.add(user)
        # Andrew 在群里说过话，所以 Relay 认识他（收到群消息时会记进名册）
        session.add(ChatMessage(message_id=f"om_{uuid.uuid4().hex}", chat_id="oc_test_m", sender_open_id="ou_andrew",
                                sender_name="Zorvan", text="收到"))
        await people.remember(session, [("ou_andrew", "Zorvan", "sender")])
        await session.flush()
        mission = await service.create(session, user, "催 Andrew 交运单明细", "让 Andrew 本周内交 9 月运单明细，交了就算完成")
        await session.commit()
        user_id, open_id, mission_id = user.id, user.feishu_open_id, mission.id

    async def mission_now():
        async with SessionLocal() as session:
            return await session.get(Mission, mission_id)

    try:
        # 第一次醒来：列计划、准备一条给 Andrew 的消息、明天再看
        provider.add(
            call("update_plan", steps=[{"step": "提醒 Andrew 交明细", "done": False}, {"step": "确认收到", "done": False}]),
            call("prepare_chat_message", to="Zorvan", text="Andrew 你好，9 月运单明细本周内能给我吗？"),
        )
        provider.add(call("wait_until", hours=24, why="等 Andrew 回复"))  # 决定了接下来怎么办，这一轮就结束
        async with SessionLocal() as session:
            await service.run_due(session, feishu)

        assert "start_mission" not in provider.tool_names and "wait_until" in provider.tool_names
        assert "confirm_action" not in provider.tool_names  # 后台不能替用户确认
        assert "催 Andrew" in provider.prompts[0] and "<mission" in provider.prompts[0]
        m = await mission_now()
        assert m.status == "active" and m.next_run_at > datetime.now(UTC) + timedelta(hours=23)
        assert [s["step"] for s in m.plan] == ["提醒 Andrew 交明细", "确认收到"]
        async with SessionLocal() as session:
            action = (await session.execute(select(PendingAction).where(PendingAction.mission_id == mission_id))).scalars().one()
        assert action.status == "pending" and action.payload["receive_id"] == "ou_andrew"
        assert feishu.sent == []  # 没授权：只准备，不发送
        assert "下一步需要你确认" in str(feishu.cards[-1])  # 已经把确认按钮推给用户

        # 用户在飞书上点确认 → 消息发出 → 任务被叫醒，知道结果
        await callbacks.handle_card_action(feishu, open_id, {"relay": "confirm", "action_id": action.id})
        # 默认以用户本人的名义发出（不带“代发”字样）
        assert "Andrew 你好" in feishu.sent[0]["content"] and feishu.sent[0]["as_user"] and "代发" not in feishu.sent[0]["content"]
        async with SessionLocal() as session:
            ready = await service.due(session)
        assert ready and "[操作有了结果]" in ready[0][1] and "已执行" in ready[0][1]

        provider.add(call("wait_for_reply", kind="chat", chat_id="oc_test_m", from_name="Zorvan", timeout_hours=48))  # 决定了接下来怎么办，这一轮就结束
        async with SessionLocal() as session:
            await service.run_due(session, feishu)
        m = await mission_now()
        assert m.status == "waiting" and m.wait_for["from_open_id"] == "ou_andrew"

        # 用户授权“给同事发飞书消息”自动执行；Andrew 在群里回了
        async with SessionLocal() as session:
            m = await session.get(Mission, mission_id)
            m.grants = ["send_chat"]
            session.add(ChatMessage(message_id=f"om_{uuid.uuid4().hex}", chat_id="oc_test_m", sender_open_id="ou_andrew",
                                    sender_name="Zorvan", text="明天上午发你"))
            await session.commit()
        provider.add(call("prepare_chat_message", to="Zorvan", text="好的，谢谢！"))
        provider.add(call("ask_user", question="Andrew 说明天上午发，要不要同步给财务？"))  # 决定了接下来怎么办，这一轮就结束
        async with SessionLocal() as session:
            await service.run_due(session, feishu)
        assert "[对方回复了]" in provider.prompts[-2] and "明天上午发你" in provider.prompts[-2]
        assert '好的，谢谢！' in feishu.sent[-1]["content"] and '"tag": "md"' in feishu.sent[-1]["content"]  # 已授权：直接发出（富文本）
        m = await mission_now()
        assert m.status == "asking" and "财务" in m.question

        # 用户回答 → 任务带着回答醒来 → 完成
        async with SessionLocal() as session:
            await service.answer(session, await session.get(Mission, mission_id), "不用")
            await session.commit()
        provider.add(call("complete_mission", result="Andrew 答应明天上午交明细", success=True))  # 决定了接下来怎么办，这一轮就结束
        async with SessionLocal() as session:
            await service.run_due(session, feishu)
        assert "[用户回答了你的问题] 不用" in provider.prompts[-1]
        assert provider.turns == []  # 剧本正好用完：每次决定等待后都没有多余的模型调用
        m = await mission_now()
        assert m.status == "done" and "明天上午" in m.result
        async with SessionLocal() as session:
            kinds = [log.kind for log in (await session.execute(select(MissionLog).where(MissionLog.mission_id == mission_id))).scalars()]
        assert {"wake", "action", "ask", "done", "report"} <= set(kinds)
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, user_id))
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == "oc_test_m"))
            await session.execute(delete(Person).where(Person.open_id == "ou_andrew"))
            await session.commit()
        await engine.dispose()


def test_free_slots_respect_work_hours_and_busy_time():
    from app.sources.scheduling import free_slots

    tz = "Asia/Jakarta"
    # 周一 08:10（雅加达）开始找；10:00-11:00 有人忙
    start = datetime(2026, 10, 19, 1, 10, tzinfo=UTC)
    busy = [(datetime(2026, 10, 19, 3, 0, tzinfo=UTC), datetime(2026, 10, 19, 4, 0, tzinfo=UTC))]
    slots = free_slots(busy, start, start + timedelta(days=1), timedelta(minutes=60), tz, limit=3)
    local = [s.astimezone(__import__("zoneinfo").ZoneInfo(tz)).strftime("%H:%M") for s, _ in slots]
    assert local == ["09:00", "11:00", "12:00"]


async def test_meeting_prepare_confirm_and_track_responses(monkeypatch):
    """“帮我约 @Andrew @Nikki 下周五 9:30 开一小时会”：直接用名册里的人 → 准备邀请 → 确认后发出 → 查回复。"""
    from app.agent.tools import ToolContext, execute
    from app.db import SessionLocal, engine
    from app.models import Conversation, PendingAction, Person, User
    from app.proactive import actions
    from app.sources import people

    class CalendarFeishu(FakeFeishu):
        def __init__(self):
            super().__init__()
            self.calls = []

        async def user_api(self, user, method, path, **kwargs):
            if path == "/search/v1/user":
                return {"users": {
                    "测试甲": [{"name": "Quillan（测试甲）", "open_id": "ou_a"}],
                    "测试乙": [{"name": "Nikki（测试乙）", "open_id": "ou_n"}],
                }.get(kwargs["params"]["query"], [])}
            self.calls.append((method, path, kwargs))
            if path == "/calendar/v4/calendars/primary":
                return {"calendars": [{"calendar": {"calendar_id": "cal1"}}]}
            if path == "/calendar/v4/calendars/cal1/events" and method == "POST":
                return {"event": {"event_id": "ev9", "app_link": "https://applink/ev9"}}
            if path.endswith("/events/ev9/attendees") and method == "POST":
                return {}
            if path.endswith("/events/ev9/attendees") and method == "GET":
                return {"items": [
                    {"type": "user", "display_name": "阿明", "rsvp_status": "accept", "is_organizer": True},
                    {"type": "user", "display_name": "Quillan（测试甲）", "user_id": "ou_a", "rsvp_status": "accept"},
                    {"type": "user", "display_name": "Nikki（测试乙）", "user_id": "ou_n", "rsvp_status": "needs_action"},
                ]}
            raise AssertionError(path)

    feishu = CalendarFeishu()
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="阿明", timezone="Asia/Jakarta", email="me@co.com")
        session.add(user)
        await session.flush()
        conversation = Conversation(user_id=user.id, channel="home")
        session.add(conversation)
        await people.remember(session, [("ou_a", "Quillan（测试甲）", "mention"), ("ou_n", "Nikki（测试乙）", "mention")])
        await session.commit()
        user_id = user.id
        try:
            ctx = ToolContext(session=session, user=user, conversation=conversation, feishu=feishu)
            start = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0).isoformat()
            text, error = await execute(ctx, "prepare_meeting", {
                "title": "IT 复盘会议", "attendees": ["Quillan（测试甲）", "测试乙"], "start": start, "duration_minutes": 60,
            })
            assert not error, text
            action = (await session.execute(select(PendingAction).where(PendingAction.user_id == user_id))).scalars().one()
            assert [a["open_id"] for a in action.payload["attendees"]] == ["ou_a", "ou_n"]
            assert not feishu.calls  # 只准备，没有建会议

            result = await actions.execute(session, feishu, user, action)
            assert action.status == "done", result
            invited = [kw for m, p, kw in feishu.calls if p.endswith("/attendees") and m == "POST"][0]
            assert invited["json"]["attendees"] == [{"type": "user", "user_id": "ou_a"}, {"type": "user", "user_id": "ou_n"}]
            await session.commit()

            text, error = await execute(ctx, "get_meeting_responses", {"meeting": action.id})
            assert not error and "接受 1" in text and "Nikki（测试乙）：还没回复" in text
        finally:
            await session.rollback()
            await session.delete(await session.get(User, user_id))
            await session.execute(delete(Person).where(Person.open_id.in_(["ou_a", "ou_n"])))
            await session.commit()
            await engine.dispose()


async def test_model_failure_never_leaves_mission_asleep_forever(monkeypatch):
    """模型调用失败后要能按时重试：以前恢复成 waiting 却清掉了等待条件，任务就再也不会醒。"""
    from app.db import SessionLocal, engine
    from app.llm import registry
    from app.llm.base import LLMError
    from app.missions import service
    from app.models import Conversation, Mission, User

    class Failing:
        name = "fake"

        async def stream(self, **kwargs):
            raise LLMError("Gemini 接口错误 (400)")
            yield  # pragma: no cover

    monkeypatch.setattr(registry, "resolve", lambda model_id: (Failing(), "fake", "fake:fake"))
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        conversation = Conversation(user_id=user.id, channel="mission", title="t")
        session.add(conversation)
        await session.flush()
        mission = Mission(user_id=user.id, conversation_id=conversation.id, title="t", goal="g", status="waiting",
                          wait_for={"type": "chat_message", "chat_id": "oc_x"}, next_run_at=datetime.now(UTC) - timedelta(minutes=1))
        session.add(mission)
        await session.commit()
        user_id, mission_id = user.id, mission.id
    try:
        async with SessionLocal() as session:
            await service.run(session, None, await session.get(Mission, mission_id), "[等待超时]")
        async with SessionLocal() as session:
            m = await session.get(Mission, mission_id)
            assert m.status == "waiting" and m.wait_for == {"type": "chat_message", "chat_id": "oc_x"}
            assert m.next_run_at > datetime.now(UTC)
            # 已经卡住的旧数据（waiting 但没有等待条件）到点也要醒
            m.wait_for, m.next_run_at = None, datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()
            assert await service.wake_reason(session, m) == "[到点了] 按计划回来看看进展"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()



async def test_reply_rules_polling_timing_and_auto_send_limits(monkeypatch):
    """复盘 #18 后的规则：以用户身份查回复、没提时间不当天反复催、换会话/催多了/下班后要确认、对方回复一定告诉用户。"""
    from app.agent.tools.base import ToolContext, execute
    from app.db import SessionLocal, engine
    from app.llm import registry
    from app.missions import service
    from app.models import Conversation, Message, Mission, MissionLog, PendingAction, User

    provider = ScriptedProvider()
    monkeypatch.setattr(registry, "resolve", lambda model_id: (provider, "fake", "fake:fake"))
    feishu = FakeFeishu()
    feishu.user_name = lambda open_id: _name(open_id)

    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        home = Conversation(user_id=user.id, channel="home", title="主线")
        session.add(home)
        await session.flush()
        session.add(Message(conversation_id=home.id, role="user", content=[
            {"type": "text", "text": "<context>…</context>", "meta": "context"},
            {"type": "text", "text": "提醒下 Nikki 把需求进度同步给需求人，让他给个结果，帮我盯着"},
        ]))
        await session.commit()
        user_id = user.id
    try:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            home = (await session.execute(select(Conversation).where(Conversation.user_id == user_id))).scalars().first()
            ctx = ToolContext(session, user, home, feishu)
            await execute(ctx, "start_mission", {"title": "盯 Nikki", "goal": "让 Nikki 给个结果", "criteria": ["Nikki 给出结果"]})
            mission = (await session.execute(select(Mission).where(Mission.user_id == user_id))).scalars().one()
            assert mission.instruction == "提醒下 Nikki 把需求进度同步给需求人，让他给个结果，帮我盯着"
            assert mission.due_at is None
            mission.grants = ["send_chat"]
            # 第一条消息已由用户确认发出（私聊）
            first = PendingAction(user_id=user_id, kind="send_chat", summary="给 Nikki 发消息", status="done", mission_id=mission.id,
                                  decided_at=datetime.now(UTC),
                                  payload={"receive_id": "ou_nikki", "receive_id_type": "open_id", "to": "Nikki", "body": "记得同步",
                                           "chat_id": "oc_p2p_nikki", "sent_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()})
            session.add(first)
            await session.commit()

            mctx = ToolContext(session, user, await session.get(Conversation, mission.conversation_id), feishu, mission=mission)
            # 没提时间：等回复的超时最早到下一个工作日上午，并默认等刚才那条消息所在的私聊
            text, error = await execute(mctx, "wait_for_reply", {"kind": "chat", "timeout_hours": 2}, user_initiated=False)
            assert not error, text
            assert mission.wait_for["chat_id"] == "oc_p2p_nikki"
            assert mission.next_run_at >= service.next_work_morning(user.timezone) - timedelta(seconds=5)
            mission.updated_at = datetime.now(UTC)  # 和真实一轮结束时一样
            await session.commit()

            # 自己发的消息不算回复；对方在私聊里回了（机器人收不到，靠用户身份拉取）
            assert await service.wake_reason(session, mission, feishu) is None
            sent_at = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp() * 1000)
            feishu.replies = [
                {"sender": {"id": user.feishu_open_id, "sender_type": "user"}, "msg_type": "text",
                 "body": {"content": '{"text": "记得同步"}'}, "create_time": str(sent_at)},
                {"sender": {"id": "ou_nikki", "sender_type": "user"}, "msg_type": "text",
                 "body": {"content": '{"text": "1"}'}, "create_time": str(sent_at + 1000)},
                {"sender": {"id": "ou_nikki", "sender_type": "user"}, "msg_type": "text",
                 "body": {"content": '{"text": "预计月底前完成"}'}, "create_time": str(sent_at + 2000)},
            ]
            reason = await service.wake_reason(session, mission, feishu)
            assert reason.startswith(service.REPLY_MARK) and "预计月底前完成" in reason and "记得同步" not in reason
            assert "承诺了时间" in await service.briefing(session, mission, reason, user)

            # 模型没汇报：对方回复了也要告诉用户
            provider.add(call("wait_until", hours=24))
            await service.run(session, feishu, mission, reason)
            reports = (await session.execute(select(MissionLog.text).where(
                MissionLog.mission_id == mission.id, MissionLog.kind == "report"))).scalars().all()
            assert any("预计月底前完成" in r for r in reports)

            # 自动发消息的边界
            monkeypatch.setattr(service, "in_work_hours", lambda *args, **kwargs: True)
            group = PendingAction(user_id=user_id, kind="send_chat", summary="群里催", mission_id=mission.id,
                                  payload={"receive_id": "oc_group", "receive_id_type": "chat_id"})
            assert "新的会话" in await service.auto_send_blocked(session, mission, user, group)
            again = PendingAction(user_id=user_id, kind="send_chat", summary="再催", mission_id=mission.id,
                                  payload={"receive_id": "ou_nikki", "receive_id_type": "open_id"})
            assert await service.auto_send_blocked(session, mission, user, again) is None
            for _ in range(service.MAX_NUDGES):
                session.add(PendingAction(user_id=user_id, kind="send_chat", summary="催", status="done", mission_id=mission.id,
                                          payload={"receive_id": "ou_nikki", "receive_id_type": "open_id"}))
            await session.flush()
            assert "已经发过" in await service.auto_send_blocked(session, mission, user, again)
            monkeypatch.setattr(service, "in_work_hours", lambda *args, **kwargs: False)
            await session.execute(delete(PendingAction).where(PendingAction.mission_id == mission.id, PendingAction.summary == "催"))
            assert "工作时间" in await service.auto_send_blocked(session, mission, user, again)
            await session.rollback()
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()


async def _name(open_id):
    return {"ou_nikki": "Nikki"}.get(open_id)


def test_next_work_morning_skips_weekend():
    from app.missions import service

    friday_evening = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)  # 雅加达周五 18:00
    monday = service.next_work_morning("Asia/Jakarta", friday_evening)
    assert monday.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%a %H:%M") == "Mon 09:30"


async def test_new_message_after_interrupted_tool_turn_keeps_turns_valid(monkeypatch):
    """上一轮在工具调用后被打断（例如部署重启）：发给模型的消息里，新问题必须是独立的一轮，前面补一句助手的话。"""
    from app.agent.loop import run_turn_text
    from app.db import SessionLocal, engine
    from app.llm import registry
    from app.memory import service as memory_service
    from app.models import Conversation, Message, User

    seen = []

    class Recorder:
        name = "fake"

        async def stream(self, *, model, system, messages, tools):
            from app.llm.base import Completion, TextDelta

            seen.append(messages)
            yield TextDelta("好的")
            yield Completion(blocks=[{"type": "text", "text": "好的"}], stop_reason="end")

    async def no_embedding(text):
        return None

    monkeypatch.setattr(memory_service, "embed", no_embedding)
    monkeypatch.setattr(registry, "resolve", lambda model_id: (Recorder(), "fake", "fake:fake"))
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        conversation = Conversation(user_id=user.id, channel="home", title="主线")
        session.add(conversation)
        await session.flush()
        session.add_all([
            Message(conversation_id=conversation.id, role="user", content=[{"type": "text", "text": "查一下群"}]),
            Message(conversation_id=conversation.id, role="assistant", content=[{"type": "tool_use", "id": "t1", "name": "find_chats", "input": {}}]),
            Message(conversation_id=conversation.id, role="user", content=[{"type": "tool_result", "tool_use_id": "t1", "name": "find_chats", "content": "群A"}]),
        ])
        await session.commit()
        user_id = user.id
        try:
            await run_turn_text(session, user=user, conversation=conversation, text="新问题", feishu=None)
            roles = [m["role"] for m in seen[0]]
            assert roles[-3:] == ["user", "assistant", "user"]
            assert seen[0][-2]["content"][0]["text"].startswith("（上一轮处理被中断")
            assert all(b["type"] != "tool_result" for b in seen[0][-1]["content"])
        finally:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
