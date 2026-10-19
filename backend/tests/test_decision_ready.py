"""提醒要能直接拍板、只给一层；用户怎么处理每件事要记下来。"""
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.agent.loop import _with_card_notes
from app.sources import approval

LEAVE = {"type": "leaveGroupV2", "name": "", "value": {
    "end": "2026-11-07T01:00:00+08:00", "interval": "2", "name": "【ID】Annual Leave HQ-2026", "reason": "长假",
    "start": "2026-11-05T01:00:00+08:00", "timezoneOffset": -420, "unit": "DAY"}}


def test_leave_widget_becomes_readable_fields():
    assert approval.group_fields(LEAVE) == [
        {"name": "请假类型", "value": "【ID】Annual Leave HQ-2026"},
        {"name": "时间", "value": "11-05 周四 至 11-06 周五"},  # 结束是次日零点，显示成最后一天
        {"name": "时长", "value": "2 天"},
        {"name": "事由", "value": "长假"},
    ]
    start, end = approval.leave_range(LEAVE)
    assert (start.hour, end.day) == (0, 7)
    remedy = {"type": "remedyGroupV2", "value": {"remedyTime": "2026-10-16T09:00:00+07:00", "reason": "忘打卡", "timezoneOffset": -420}}
    assert {"name": "补卡时间", "value": "10-16 周五 09:00"} in approval.group_fields(remedy)


async def test_short_forms_get_no_extra_summary():
    from app.proactive import items

    signal = SimpleNamespace(body="发起人：张三", payload={"detail": {"fields": [{"name": "时长", "value": "2 天"}], "leave": ["a", "b"]}})
    assert await items.summarize_approval(signal) is None
    signal.payload = {}
    assert await items.summarize_approval(signal) == items.NO_DETAIL  # 读不到表单就直说，不复述发起人


def test_card_only_message_keeps_turn_order():
    rows = [
        SimpleNamespace(role="user", content=[{"type": "text", "text": "<event>Relay 告诉用户</event>", "meta": "event"}]),
        SimpleNamespace(role="assistant", content=[{"type": "card", "card": {"kind": "doc", "title": "请假"}}]),
        SimpleNamespace(role="user", content=[{"type": "text", "text": "批了吧"}]),
    ]
    messages = _with_card_notes(rows, {}, {})
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert "请假" in messages[2]["content"][0]["text"]


@pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")
async def test_decisions_are_recorded_and_summarised():
    from sqlalchemy import delete, select

    from app import insights
    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import FollowUp, PendingAction, Signal, User, UserDecision

    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        signal = Signal(user_id=user.id, source="approval", kind="approval_pending", external_id=uuid.uuid4().hex,
                        title="补卡", payload={"definition_name": "Clock-in/out Correction——补卡"}, status="tracked",
                        occurred_at=datetime.now(UTC))
        session.add(signal)
        await session.flush()
        item = FollowUp(user_id=user.id, key=f"approval:{signal.external_id}", kind="approval", owner="me",
                        title="张三：补卡", url="https://example.feishu.cn/approval/1", signal_ids=[signal.id],
                        announced_at=datetime.now(UTC), created_at=datetime.now(UTC) - timedelta(minutes=10))
        session.add(item)
        await session.flush()
        action = PendingAction(user_id=user.id, kind="approval_decision", summary="批准补卡", signal_id=signal.id,
                               payload={"approve": True})
        session.add(action)
        await session.commit()
        user_id, item_id = user.id, item.id
        try:
            # 系统自己做的不记；网页上点的记为 web
            await insights.record(session, user, "confirm", action=action)
            token = insights.via.set("web")
            await insights.record(session, user, insights.action_decision(action), action=action)
            insights.via.reset(token)
            token = insights.via.set("auto")
            await insights.record(session, user, "confirm", action=action)
            insights.via.reset(token)
            await session.commit()
            rows = (await session.execute(select(UserDecision).where(UserDecision.user_id == user_id))).scalars().all()
            assert [(r.decision, r.via) for r in rows] == [("approve", "web"), ("confirm", "auto")]
            assert rows[0].category == "Clock-in/out Correction——补卡" and rows[0].subject == "approval"
            assert rows[0].seconds_to_decide >= 590

            # 飞书卡片上“在飞书查看”：签名链接，记一笔再跳转；签名不对不跳
            link = insights.open_link(item, "feishu")
            path = link.split("://", 1)[1].split("/", 1)[1]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
                assert (await client.get("/" + path.replace("&s=", "&s=0"))).status_code == 404
                response = await client.get("/" + path)
                assert response.status_code == 302 and response.headers["location"] == item.url
            opened = (await session.execute(select(UserDecision).where(
                UserDecision.user_id == user_id, UserDecision.decision == "open_original"))).scalars().one()
            assert opened.via == "feishu_card" and opened.item_id == item_id

            report = await insights.summary(session, user)
            assert report["handled"] == 1 and report["auto"] == 1 and report["opened_original"] == 1
            assert report["patterns"][0]["category"] == "Clock-in/out Correction——补卡"
        finally:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
