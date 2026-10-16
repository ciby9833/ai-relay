"""长期任务的集成测试：真实数据库 + 假飞书 + 按剧本行动的假模型。

    docker compose run --rm -e RUN_DB_TESTS=1 api pytest
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

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

    async def send_card(self, open_id, card, fallback):
        self.cards.append(card)
        return f"om_{uuid.uuid4().hex}"

    async def send_text(self, open_id, text):
        pass

    async def user_api(self, user, method, path, **kwargs):
        if path == "/im/v1/messages":  # 以用户本人身份发消息
            self.sent.append({**kwargs["json"], "as_user": True})
            return {"message_id": "om_u"}
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
        assert "[群里有新消息]" in provider.prompts[-2] and "明天上午发你" in provider.prompts[-2]
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
