"""同一件事跨入口：邮件里要他推进的事，“待处理”和“邮件”里是同一个事项（同一个编号、同一个状态）；
处理后两边同步、飞书卡片跟着更新，不重复提醒；回了信不一定办完，可能转成等对方。
“需要你看”必须说得出为什么和他有关、要他做什么、什么时候——说不出来的不进待处理。"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tests.test_attention import Feishu

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


@db
async def test_one_mail_item_one_state_across_entries(monkeypatch):
    from sqlalchemy import delete, select

    from app import deps
    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import FeishuCard, FollowUp, PendingAction, Signal, User
    from app.proactive import attention, items
    from app.proactive.settings import merged
    from app.sources.base import add_signal

    async def no_post(*args, **kwargs):
        return None

    async def narrate(system, prompt):
        return "有几件事。"

    async def still_waiting(theirs, mine, lang="zh"):
        return "waiting", "你答应周五给方案，等 Sari 确认"

    monkeypatch.setattr(items, "post", no_post)
    monkeypatch.setattr(items, "complete_text", narrate)
    monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
    monkeypatch.setattr(items, "judge_reply", still_waiting)
    monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: True)
    feishu = Feishu()
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Xavier", email="xavier@jt.id", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            await add_signal(session, user, "mail", f"m-{tag}", kind="mail", title="Medan 延误复盘", body="请 Xavier 周五前给出改善方案",
                             payload={"thread_id": f"th-{tag}", "from_name": "Sari", "subject": "Medan 延误复盘"},
                             occurred_at=datetime.now(UTC), status="tracked")
            await session.flush()
            signal = (await session.execute(select(Signal).where(Signal.user_id == user_id))).scalars().one()
            item = FollowUp(user_id=user_id, key=f"mail-thread:th-{tag}", kind="reply", owner="me", title="回复 Sari：Medan 延误复盘",
                            signal_ids=[signal.id], facets={"people": ["Sari"]}, next_step="给出改善方案")
            other = FollowUp(user_id=user_id, key=f"chat:x-{tag}", kind="request", owner="me", title="Budi 让你：发报价", facets={})
            session.add_all([item, other])
            await session.commit()

            # 两个入口读的是同一份：待处理里有它（标着是邮件），邮件入口按 is_mail 取的也是同一个编号
            app.dependency_overrides[deps.get_current_user] = lambda: user
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
                board = (await client.get("/api/board")).json()
            mine = {i["id"]: i for i in board["me"]}
            assert set(mine) == {item.id, other.id} and mine[item.id]["is_mail"] and not mine[other.id]["is_mail"]

            # 推送：一件事一张卡片；同一轮再跑不会重复提醒
            await items.announce(session, feishu, user, merged({}), [])
            await items.announce(session, feishu, user, merged({}), [])
            assert len(feishu.cards) == 1

            # 他在 Relay 里发了回复：发出去不等于办完——Sari 还要确认，转成等对方（同一个事项），不另发提醒，卡片原地更新
            action = PendingAction(user_id=user_id, kind="send_mail", signal_id=signal.id, summary="回复 Sari", status="done",
                                   payload={"body": "周五前给方案。"})
            session.add(action)
            await session.flush()
            item.action_id = action.id
            await session.commit()
            await items.advance(session, user)
            await session.refresh(item)
            assert (item.id, item.kind, item.owner, item.status) == (item.id, "waiting", "others", "open")
            assert item.summary == "你答应周五给方案，等 Sari 确认"
            await items.announce(session, feishu, user, merged({}), [])
            assert len(feishu.cards) == 1
            assert await items.sync_cards(session, feishu, user) == 1
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
                board = (await client.get("/api/board")).json()
                assert [i["id"] for i in board["others"]] == [item.id] and item.id not in [i["id"] for i in board["me"]]
                # 在任一入口标“已处理”：同一个事项结束，两边都不再出现
                assert (await client.post(f"/api/items/{item.id}/feedback", json={"outcome": "handled"})).status_code == 200
                board = (await client.get("/api/board")).json()
            assert item.id not in [i["id"] for i in board["me"] + board["others"]]
            assert len((await session.execute(select(FollowUp).where(FollowUp.user_id == user_id, FollowUp.key == item.key))).scalars().all()) == 1
            assert len((await session.execute(select(FeishuCard).where(FeishuCard.user_id == user_id))).scalars().all()) == 1
        finally:
            app.dependency_overrides.pop(deps.get_current_user, None)
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_needs_your_review_must_say_why_what_and_when(monkeypatch):
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import Signal, User
    from app.proactive import engine as proactive
    from app.sources.base import add_signal

    answers = {
        "周报": {"importance": "normal", "notify_now": False, "needs_reply": False, "action_type": "review", "due": "none",
                 "summary": "本周网点周报", "reason": "周报"},  # 说不出为什么和他有关：不进待处理
        "方案": {"importance": "normal", "notify_now": False, "needs_reply": False, "action_type": "review", "due": "this_week",
                 "summary": "看改善方案", "reason": "要他看", "why_me": "抄送给他，但正文点名请他作为运营负责人确认方案",
                 "ask": "确认 Medan 改善方案是否可行", "when": "周五前"},
    }

    async def classify(system, prompt, tool):
        assert "这封信里他是：只在抄送里" in prompt
        return answers["方案" if "方案" in prompt else "周报"]

    monkeypatch.setattr(proactive, "complete_structured", classify)
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Xavier", email="xavier@jt.id", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            for subject in ("周报", "方案"):
                await add_signal(session, user, "mail", f"{subject}-{tag}", kind="mail", title=subject, body=f"{subject}内容",
                                 payload={"from": "Sari", "to_addresses": [{"mail_address": "ops@jt.id"}],
                                          "cc_addresses": [{"mail_address": "xavier@jt.id"}]}, status="new")
            await session.commit()
            await proactive.triage(session, user)
            rows = {s.title: s for s in (await session.execute(select(Signal).where(Signal.user_id == user_id))).scalars()}
            assert rows["周报"].status == "ignored" and rows["周报"].payload["action_type"] == "fyi"
            assert rows["方案"].status == "notify" and rows["方案"].payload["ask"] == "确认 Medan 改善方案是否可行"
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
