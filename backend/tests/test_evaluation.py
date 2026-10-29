"""线上评估：账本增量计算（只处理新事件、出错重试、历史任务不进来）；每个人只看自己的、只标自己的；管理员只看数字。"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.ledger import engine, shadow

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class Scripted:
    name = "fake"

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def stream(self, *, model, system, messages, tools):
        from app.llm.base import Completion

        self.calls.append(model)
        answer = self.answers.pop(0) if self.answers else {}
        if answer == "fail":
            raise RuntimeError("429")
        yield Completion(blocks=[{"type": "tool_use", "id": "x", "name": tools[0]["name"], "input": answer}], stop_reason="tool_use",
                         usage={"input_tokens": 10, "output_tokens": 1})


@db
async def test_incremental_ledger(monkeypatch):
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine as db_engine
    from app.models import ChatMessage, LedgerCommitment, LedgerEvent, LedgerMatter, Signal, SourceState, User
    from app.sources.base import add_signal

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr("asyncio.sleep", no_sleep)
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(me)
        await session.flush()
        user_id = me.id
        session.add(ChatMessage(message_id=f"om_{tag}_1", chat_id=f"oc_{tag}", chat_name="终端项目", sender_open_id="ou_c", sender_name="Callesya",
                                text="@Xavier(吴川) 能不能帮忙看一下盘点逻辑？", mentions=[{"open_id": me.feishu_open_id}],
                                created_at=now - timedelta(hours=2)))
        # 两个月前派的、没有截止时间的飞书任务：历史遗留，不进账本
        await add_signal(session, me, "task", f"t-{tag}", kind="task", title="针对公司业务，进行一次chatgpt培训", status="digest",
                         occurred_at=now - timedelta(days=60), payload={"creator_name": "王国全"})
        await session.commit()
        try:
            provider = Scripted([
                {"assignments": [{"event": f"[chat:om_{tag}_1] …", "matter": "new", "title": "盘点逻辑", "people": ["Callesya"]}]},
                {"summary": "Callesya 请他看盘点逻辑", "commitments": [{"owner": "me", "party": "Callesya", "what": "看一下盘点逻辑",
                                                                   "status": "open", "evidence": "她@他请他看"}]},
            ])
            await engine.enroll(session, me, days=1)
            await engine.advance(session, provider, me, now)
            state = await session.get(SourceState, (user_id, engine.STATE))
            assert state.cursor["backfilled"] is True and state.cursor["progress"] == state.cursor["until"]
            matters =(await session.execute(select(LedgerMatter).where(LedgerMatter.user_id == user_id))).scalars().all()
            assert [m.title for m in matters] == ["盘点逻辑"]
            commitments = (await session.execute(select(LedgerCommitment).where(LedgerCommitment.user_id == user_id))).scalars().all()
            assert [(c.owner, c.status) for c in commitments] == [("me", "open")]
            refs = set((await session.execute(select(LedgerEvent.ref).where(LedgerEvent.user_id == user_id))).scalars())
            assert refs == {f"chat:om_{tag}_1"}  # 历史任务没进来
            assert provider.calls == [shadow.ATTACH_MODEL, shadow.RECONCILE_MODEL]

            # 再跑一次：没有新事件就不调模型
            again = Scripted([])
            await engine.advance(session, again, me, now + timedelta(minutes=5))
            assert again.calls == []

            # 新消息来了，但模型出错：处理点停在出错之前，下次重试
            session.add(ChatMessage(message_id=f"om_{tag}_2", chat_id=f"oc_{tag}", chat_name="终端项目", sender_open_id="ou_c",
                                    sender_name="Callesya", text="@Xavier(吴川) 看完了吗？", mentions=[{"open_id": me.feishu_open_id}],
                                    created_at=now + timedelta(minutes=10)))
            await session.commit()
            await engine.advance(session, Scripted(["fail", "fail", "fail"]), me, now + timedelta(minutes=20))
            state = await session.get(SourceState, (user_id, engine.STATE))
            assert datetime.fromisoformat(state.cursor["until"]) < now + timedelta(minutes=10)
            retry = Scripted([
                {"assignments": [{"event": f"chat:om_{tag}_2", "matter": str(matters[0].id)}]},
                {"summary": "还在等他看", "commitments": [{"owner": "me", "party": "Callesya", "what": "看一下盘点逻辑",
                                                       "status": "open", "evidence": "她追问"}]},
            ])
            await engine.advance(session, retry, me, now + timedelta(minutes=25))
            assert retry.calls == [shadow.ATTACH_MODEL, shadow.RECONCILE_MODEL]
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == f"oc_{tag}"))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await db_engine.dispose()


@db
async def test_each_person_sees_and_labels_only_their_own():
    from sqlalchemy import delete

    from app import deps
    from app.db import SessionLocal, engine as db_engine
    from app.main import app
    from app.models import FollowUp, LedgerCommitment, LedgerMatter, User

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_a_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        other = User(feishu_open_id=f"ou_b_{tag}", name="Kange", timezone="Asia/Jakarta", is_admin=False)
        admin = User(feishu_open_id=f"ou_c_{tag}", name="Admin", timezone="Asia/Jakarta", is_admin=True)
        session.add_all([me, other, admin])
        await session.flush()
        ids = [me.id, other.id, admin.id]
        matter = LedgerMatter(user_id=me.id, title="盘点逻辑", people=["Callesya"], created_at=now, last_at=now)
        session.add(matter)
        await session.flush()
        session.add(LedgerCommitment(user_id=me.id, matter_id=matter.id, owner="me", party="Callesya", what="看一下盘点逻辑",
                                     status="open", evidence="她@他", updated_at=now))
        item = FollowUp(user_id=me.id, key=f"k-{tag}", kind="task", owner="me", title="派给你的任务：chatgpt培训", facets={})
        session.add(item)
        await session.commit()
        item_id = matter_id = None
        item_id, matter_id = item.id, matter.id

    as_user = {"current": None}
    app.dependency_overrides[deps.get_current_user] = lambda: as_user["current"]
    try:
        async with SessionLocal() as session:
            users = {u.id: u for u in [await session.get(User, i) for i in ids]}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
            as_user["current"] = users[ids[0]]
            assert (await client.post("/api/eval/enroll", json={"days": 2})).json()["enrolled"]
            data = (await client.get("/api/eval")).json()
            # 刚开始：排队中，范围定为开始时选的 2 天；再点开始不会改范围
            assert (data["status"], data["progress"], data["days"]) == ("queued", 0.0, 2)
            await client.post("/api/eval/enroll", json={"days": 3})
            assert (await client.get("/api/eval")).json()["days"] == 2
            assert [c["what"] for c in data["ledger"]] == ["看一下盘点逻辑"]
            assert [c["title"] for c in data["current"]] == ["派给你的任务：chatgpt培训"]
            key = data["ledger"][0]["key"]
            assert (await client.put("/api/eval/labels", json={"target": "ledger", "key": key, "label": "up"})).status_code == 200
            assert (await client.put("/api/eval/labels", json={"target": "followup", "key": str(item_id), "label": "down",
                                                               "reason": "too_old", "note": "两个月前的任务"})).status_code == 200
            assert (await client.post("/api/eval/feedback", json={"kind": "missed", "text": "等 Hendri 发运单明细"})).status_code == 200
            labeled = (await client.get("/api/eval")).json()
            assert labeled["ledger"][0]["feedback"]["label"] == "up"
            assert labeled["current"][0]["feedback"] == {"label": "down", "reason": "too_old", "note": "两个月前的任务"}

            # 别人看不到他的，也标不了他的
            as_user["current"] = users[ids[1]]
            mine = (await client.get("/api/eval")).json()
            assert mine["ledger"] == [] and mine["current"] == [] and mine["enrolled"] is False
            assert (await client.put("/api/eval/labels", json={"target": "followup", "key": str(item_id), "label": "up"})).status_code == 404
            assert (await client.put("/api/eval/labels", json={"target": "ledger", "key": f"{matter_id}:me:x", "label": "up"})).status_code == 404
            assert (await client.get("/api/insights/eval")).status_code == 403

            # 管理员只看到数字
            as_user["current"] = users[ids[2]]
            overview = (await client.get("/api/insights/eval")).json()
            row = next(r for r in overview["users"] if r["user"] == "Xavier(吴川)")
            assert row["ledger"]["correct"] == 1.0 and row["current"]["reasons"] == {"too_old": 1} and row["current"]["real"] == 0.0
            assert row["missed"] == 1
            assert "盘点逻辑" not in str(overview) and "chatgpt" not in str(overview) and "Hendri" not in str(overview)
            assert "两个月前" not in str(overview)  # 备注也只有本人看得到
    finally:
        app.dependency_overrides.pop(deps.get_current_user, None)
        async with SessionLocal() as session:
            await session.execute(delete(User).where(User.id.in_(ids)))
            await session.commit()
        await db_engine.dispose()

