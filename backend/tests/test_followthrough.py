"""一件事一张卡片、谁在问和等了多久、邮件“请你看一下”的结束规则、委托写入的读回核对。"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import FollowUp, PendingAction, Signal, User
from app.proactive import attention, verify
from tests.test_attention import Feishu

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")
NOW = datetime(2026, 10, 21, 3, 0, tzinfo=UTC)


def _user():
    return User(id=uuid.uuid4(), feishu_open_id="ou_me", name="Pieter", timezone="Asia/Jakarta")


def _ask(created, summary="「报价发我」", kind="request"):
    return FollowUp(kind=kind, owner="me", title="Budi 让你：发报价", summary=summary, importance="normal", facets={"people": ["Budi"]},
                    created_at=created, signal_ids=[])


def test_who_asks_and_how_long_they_waited():
    fresh = attention.decide(_ask(NOW - timedelta(minutes=20)), None, _user(), [], None, NOW)
    assert fresh.level == "batch"  # 刚问：攒着一起说
    waited = attention.decide(_ask(NOW - timedelta(hours=5)), None, _user(), [], None, NOW)
    assert (waited.level, waited.note, waited.critical) == ("now", "Budi 已经等了 5 小时", False)  # 受每小时次数限制
    again = attention.decide(_ask(NOW - timedelta(minutes=20), "「报价发我」\n「报价呢？」"), None, _user(), [], None, NOW)
    assert (again.level, again.note) == ("now", "Budi 追问了")
    old = attention.decide(_ask(NOW - timedelta(days=5)), None, _user(), [], None, NOW)
    assert old.level == "batch"  # 回填进来的旧事：不因为“等得久”打断
    approval = FollowUp(kind="approval", owner="me", title="请假", importance="normal", facets={"people": ["Budi"]}, created_at=NOW - timedelta(hours=6))
    assert attention.decide(approval, None, _user(), [], None, NOW).level == "batch"  # 审批不是“有人在等他答复”


class Docs:
    def __init__(self, content="", values=None):
        self.content, self.values = content, values or []

    async def user_api(self, user, method, path, **kwargs):
        if path.endswith("/raw_content"):
            return {"content": self.content}
        if "/values/" in path:
            return {"valueRange": {"values": self.values}}
        if path.startswith("/docx/v1/documents/"):
            return {"document": {"title": "周报"}}
        raise AssertionError(path)


async def test_delegated_writes_are_read_back():
    user = _user()
    append = PendingAction(kind="cloud_write", payload={"operation": "append_doc_text", "arguments": {"document_id": "d1", "text": "本周 Medan 延误 3 单"}})
    assert (await verify.check(Docs("标题\n本周 Medan 延误 3 单\n"), user, append))["ok"] is True
    assert (await verify.check(Docs("标题\n"), user, append))["ok"] is False
    write = PendingAction(kind="cloud_write", payload={"operation": "write_sheet_range", "arguments": {
        "spreadsheet_token": "s1", "range": "abc!A1:B2", "values": [["网点", "单量"], ["Medan", 12]]}})
    assert (await verify.check(Docs(values=[["网点", "单量"], ["Medan", "12"]]), user, write))["ok"] is True
    bad = await verify.check(Docs(values=[["网点", "单量"], ["Medan", "21"]]), user, write)
    assert bad["ok"] is False and "第 2 行第 2 列" in bad["detail"]
    created = PendingAction(kind="cloud_write", payload={"operation": "create_doc", "arguments": {"title": "周报"},
                                                         "response": {"document": {"document_id": "d9"}}})
    assert (await verify.check(Docs(), user, created))["ok"] is True


@db
async def test_review_mail_items_close_by_rule():
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.proactive import items
    from app.sources.base import add_signal

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Pieter", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            await add_signal(session, user, "mail", f"m-{tag}", kind="mail", title="周报", payload={"thread_id": f"th-{tag}"},
                             occurred_at=datetime.now(UTC) - timedelta(days=1), status="tracked")
            await session.flush()
            from sqlalchemy import select
            signal = (await session.execute(select(Signal).where(Signal.user_id == user_id))).scalars().one()
            old = datetime.now(UTC) - timedelta(days=4)
            quiet = FollowUp(user_id=user_id, key=f"batch:a:{tag}", kind="review", owner="me", title="看一下 A 的周报",
                             signal_ids=[], facets={}, created_at=old, updated_at=old)
            replied = FollowUp(user_id=user_id, key=f"batch:b:{tag}", kind="review", owner="me", title="看一下 B 的周报",
                               signal_ids=[signal.id], facets={}, created_at=datetime.now(UTC) - timedelta(hours=3))
            fresh = FollowUp(user_id=user_id, key=f"batch:c:{tag}", kind="review", owner="me", title="看一下 C 的周报", signal_ids=[], facets={})
            session.add_all([quiet, replied, fresh])
            await add_signal(session, user, "mail", f"sent-{tag}", kind="mail_sent", title="Re: 周报", payload={"thread_id": f"th-{tag}"},
                             occurred_at=datetime.now(UTC), status="done")
            await session.commit()
            await items.advance(session, user)
            for i in (quiet, replied, fresh):
                await session.refresh(i)
            assert (quiet.status, quiet.resolution) == ("dismissed", "3 天没有新的往来，不再跟进")
            assert (replied.status, replied.resolution) == ("done", "你已经回复了")
            assert fresh.status == "open"
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_one_item_one_card(monkeypatch):
    """发过卡片的事又有动静：原地更新，不另发；对方等了一天再提醒时另发一条，旧卡片上它收成一行；办完后卡片跟着更新。"""
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import FeishuCard
    from app.proactive import items
    from app.proactive.settings import merged

    async def no_post(*args, **kwargs):
        return None

    async def narrate(system, prompt):
        return "有几件事。"

    monkeypatch.setattr(items, "post", no_post)
    monkeypatch.setattr(items, "complete_text", narrate)
    monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
    monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: False)
    feishu = Feishu()
    settings = merged({})
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Pieter", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            item = FollowUp(user_id=user_id, key=f"chat:boss-{tag}", kind="request", owner="me", title="Hendra 让你：今天把报价发我",
                            summary="「报价发我」", facets={"people": ["Hendra"], "open_ids": ["ou_boss"]})
            session.add(item)
            await session.commit()
            await items.announce(session, feishu, user, settings, [])
            assert len(feishu.cards) == 1

            # 两小时后又有动静（合并进来一句补充）：原地更新那张卡片，不另发
            item.announced_at, item.pushed_at = None, datetime.now(UTC) - timedelta(hours=2)
            await session.commit()
            await items.announce(session, feishu, user, settings, [])
            assert len(feishu.cards) == 1 and len(feishu.patched) == 1

            # 过了一天还没处理：再提醒一次（另发），旧卡片上这件事收成一行
            item.pushed_at = datetime.now(UTC) - timedelta(days=1, minutes=5)
            await session.commit()
            reminders = await items.due_reminders(session, feishu, user)
            assert [fact for _, fact in reminders] == [f"Hendra 已经等你 {attention._span(datetime.now(UTC) - item.created_at)}：Hendra 让你：今天把报价发我"]
            await items.announce(session, feishu, user, settings, reminders)
            assert len(feishu.cards) == 2
            cards = (await session.execute(select(FeishuCard).where(FeishuCard.user_id == user_id).order_by(FeishuCard.created_at))).scalars().all()
            assert [c.get("moved") for _, group in cards[0].sections for c in group] == [True]
            assert [c.get("moved") for _, group in cards[1].sections for c in group] == [None]

            # 他在别处办完了：两张卡片都跟着更新成“已处理”，不另发
            items.close(item, "done", "你在群里发了报价")
            await session.commit()
            patched = len(feishu.patched)
            assert await items.sync_cards(session, feishu, user) == 2
            assert len(feishu.patched) == patched + 2 and len(feishu.cards) == 2
            assert await items.sync_cards(session, feishu, user) == 0  # 没有新变化就不再更新
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_undo_reopens_only_that_item():
    import httpx
    from sqlalchemy import delete, select

    from app import deps
    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import ItemFeedback

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Pieter", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        a = FollowUp(user_id=user_id, key=f"a-{tag}", kind="approval", owner="me", title="Ricky：新功能申请", facets={})
        b = FollowUp(user_id=user_id, key=f"b-{tag}", kind="approval", owner="me", title="Gray：新功能申请", facets={})
        session.add_all([a, b])
        await session.commit()
        app.dependency_overrides[deps.get_current_user] = lambda: user
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
                assert (await client.post(f"/api/items/{a.id}/feedback", json={"outcome": "paused"})).status_code == 200
                assert (await client.post(f"/api/items/{b.id}/undo")).status_code == 409  # 没标记过的不能撤销
                progress = (await client.get("/api/progress")).json()
                entry = next(i for d in progress["days"] for i in d["items"] if i["id"] == a.id)
                assert entry["resolution"] == "你说暂时不跟进" and entry["undoable"] is True
                assert (await client.post(f"/api/items/{a.id}/undo")).json()["message"] == "已撤销，这件事回到待处理"
            await session.refresh(a)
            await session.refresh(b)
            assert (a.status, b.status) == ("open", "open") and a.announced_at is not None  # 回到待处理，不重新提醒
            assert (await session.execute(select(ItemFeedback).where(ItemFeedback.user_id == user_id))).scalars().all() == []
        finally:
            app.dependency_overrides.pop(deps.get_current_user, None)
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
