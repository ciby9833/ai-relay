"""工作区内的协作委托：请求 → 接受 / 拒绝 / 提修改 → 提交 → 验收 / 退回；取消；变更记录。

只在同一工作区的双方之间；对方只能看到委托里写明的内容；双方“待处理”跟着委托变；
重复点击、基于旧状态的操作不会执行两次；“待处理”里点完成不能代替提交或验收；助理准备的操作要本人确认。
用虚构的数据。
"""
import os
import uuid

import httpx
import pytest

from app import tenancy

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")
PASSWORD = "collab-pass-1"


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay")


async def _login(app, email, tenant_id):
    client = _client(app)
    res = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD, "tenant_id": str(tenant_id)})
    assert res.status_code == 200, res.text
    return client


async def _member(session, tenant_id, name, tag):
    from app.models import Account, User

    account = Account(email=f"{name.lower()}-{tag}@collab.test", name=name, password_hash=tenancy.hash_password(PASSWORD))
    session.add(account)
    await session.flush()
    user = User(tenant_id=tenant_id, account_id=account.id, name=f"{name} {tag}", email=account.email, timezone="Asia/Jakarta")
    session.add(user)
    await session.flush()
    return user


async def test_delegation_lifecycle_stays_between_the_two_people():
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import Account, Delegation, FollowUp, PendingAction, Tenant, User
    from app.proactive import actions

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        owner_account = Account(email=f"ana-{tag}@collab.test", name="Ana", password_hash=tenancy.hash_password(PASSWORD))
        session.add(owner_account)
        await session.flush()
        ana = await tenancy.create_workspace(session, owner_account, f"Alpha {tag}")
        alpha = ana.tenant_id
        budi = await _member(session, alpha, "Budi", tag)
        cici = await _member(session, alpha, "Cici", tag)
        other_account = Account(email=f"dewi-{tag}@collab.test", name="Dewi", password_hash=tenancy.hash_password(PASSWORD))
        session.add(other_account)
        await session.flush()
        dewi = await tenancy.create_workspace(session, other_account, f"Beta {tag}")
        await session.commit()
        ids = {"ana": ana.id, "budi": budi.id, "cici": cici.id, "dewi": dewi.id}
        tenants = [alpha, dewi.tenant_id]

    async def item_of(user_id, delegation_id):
        async with SessionLocal() as session:
            return (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id,
                                                                 FollowUp.key == f"collab:{delegation_id}"))).scalars().first()

    try:
        a = await _login(app, f"ana-{tag}@collab.test", alpha)
        b = await _login(app, f"budi-{tag}@collab.test", alpha)
        c = await _login(app, f"cici-{tag}@collab.test", alpha)
        d = await _login(app, f"dewi-{tag}@collab.test", tenants[1])

        # 只能请本工作区的同事：成员列表里没有别的公司的人，也不能请自己
        names = {m["name"] for m in (await a.get("/api/collab/members")).json()}
        assert names == {f"Budi {tag}", f"Cici {tag}"}
        base = {"title": "整理 9 月运单明细", "brief": "客户对账要用", "deliverable": "运单明细表"}
        assert (await a.post("/api/collab", json={**base, "assignee_id": str(ids["dewi"])})).status_code == 400
        assert (await a.post("/api/collab", json={**base, "assignee_id": str(ids["ana"])})).status_code == 400
        # 本地路径对方打不开：不接受
        bad = {**base, "assignee_id": str(ids["budi"]), "materials": [{"title": "表", "url": "file:///Users/ana/a.xlsx"}]}
        assert (await a.post("/api/collab", json=bad)).status_code == 400

        created = (await a.post("/api/collab", json={**base, "assignee_id": str(ids["budi"]),
                                                      "materials": [{"title": "对账模板", "url": "https://docs.example/t"}]})).json()
        did = created["id"]
        assert created["status"] == "requested" and created["due_at"] is None  # 没约定期限就是没有
        # 双方的“待处理”：轮到 Budi，要告诉他；Ana 在等，不用打扰她
        mine, theirs = await item_of(ids["budi"], did), await item_of(ids["ana"], did)
        assert mine.owner == "me" and mine.kind == "collab" and mine.announced_at is None
        assert theirs.owner == "others" and theirs.announced_at is not None

        # 只有双方能看：同工作区的旁人、别的公司的人都看不到
        assert (await c.get(f"/api/collab/{did}")).status_code == 404
        assert (await d.get(f"/api/collab/{did}")).status_code == 404
        seen = (await b.get(f"/api/collab/{did}")).json()
        assert seen["role"] == "assignee" and set(seen["actions"]) == {"accept", "decline", "counter"}
        assert seen["materials"] == [{"title": "对账模板", "url": "https://docs.example/t"}]

        # 请求方不能替承接方接受；旧版本、重复点击不执行两次
        assert (await a.post(f"/api/collab/{did}/act", json={"action": "accept", "version": 1})).status_code == 400
        assert (await b.post(f"/api/collab/{did}/act", json={"action": "accept", "version": 1})).json()["status"] == "accepted"
        assert (await b.post(f"/api/collab/{did}/act", json={"action": "accept", "version": 1})).status_code == 409

        # “待处理”里点完成 / 不跟了：不能代替提交
        budi_item = await item_of(ids["budi"], did)
        res = (await b.post(f"/api/items/{budi_item.id}/done")).json()
        assert "协作" in res["message"] and (await item_of(ids["budi"], did)).status == "open"
        assert (await b.post(f"/api/items/{budi_item.id}/dismiss")).status_code == 400

        # 提交要写明交付了什么；提交后轮到 Ana 验收，告诉她
        assert (await b.post(f"/api/collab/{did}/act", json={"action": "submit", "version": 2})).status_code == 400
        sub = (await b.post(f"/api/collab/{did}/act", json={"action": "submit", "version": 2, "note": "第一版",
                                                             "materials": [{"title": "明细", "url": "https://docs.example/v1"}]})).json()
        assert sub["status"] == "submitted"
        theirs = await item_of(ids["ana"], did)
        assert theirs.owner == "me" and theirs.announced_at is None
        # 退回要说明；退回后又轮到 Budi
        assert (await a.post(f"/api/collab/{did}/act", json={"action": "return", "version": 3})).status_code == 400
        await a.post(f"/api/collab/{did}/act", json={"action": "return", "version": 3, "note": "缺 9 月 30 日"})
        assert (await item_of(ids["budi"], did)).owner == "me"
        await b.post(f"/api/collab/{did}/act", json={"action": "submit", "version": 4, "note": "补齐了"})
        done = (await a.post(f"/api/collab/{did}/act", json={"action": "approve", "version": 5})).json()
        assert done["status"] == "completed" and [e["kind"] for e in done["log"]] == ["request", "accept", "submit", "return", "submit", "approve"]
        assert (await item_of(ids["ana"], did)).status == "done" and (await item_of(ids["budi"], did)).status == "done"

        # 提修改 → 请求方同意：按修改后的条件开始
        second = (await a.post("/api/collab", json={**base, "title": "报价单", "assignee_id": str(ids["budi"])})).json()["id"]
        assert (await b.post(f"/api/collab/{second}/act", json={"action": "counter", "version": 1})).status_code == 400
        await b.post(f"/api/collab/{second}/act", json={"action": "counter", "version": 1, "note": "周五做不完",
                                                         "changes": {"deliverable": "报价单初稿", "due_at": "2026-11-10T17:00:00+07:00"}})
        assert (await item_of(ids["ana"], second)).owner == "me"
        agreed = (await a.post(f"/api/collab/{second}/act", json={"action": "agree", "version": 2})).json()
        assert agreed["status"] == "accepted" and agreed["deliverable"] == "报价单初稿" and agreed["due_at"].startswith("2026-11-10")
        # 已接受后请求方取消：告诉 Budi 不用再做，这时“待处理”里可以直接关掉
        await a.post(f"/api/collab/{second}/act", json={"action": "cancel", "version": 3})
        notice = await item_of(ids["budi"], second)
        assert notice.status == "open" and "不用再做" in notice.next_step and notice.announced_at is None
        assert (await b.post(f"/api/items/{notice.id}/dismiss")).status_code == 200

        # 拒绝：请求方要知道，自己决定另找人还是放下
        third = (await a.post("/api/collab", json={**base, "title": "盘点", "assignee_id": str(ids["cici"])})).json()["id"]
        await c.post(f"/api/collab/{third}/act", json={"action": "decline", "version": 1, "note": "这周在外地"})
        told = await item_of(ids["ana"], third)
        assert told.status == "open" and told.owner == "me" and "这周在外地" in told.next_step

        # 助理准备的操作：本人确认才生效；准备之后委托变了，就不执行
        async with SessionLocal() as session:
            me = await session.get(User, ids["ana"])
            action = PendingAction(user_id=me.id, kind="collab", summary="请 Cici", payload={
                "op": "create", "assignee_id": str(ids["cici"]), "title": "周报", "brief": "汇总本周", "deliverable": "周报"})
            session.add(action)
            await session.flush()
            assert await session.scalar(select(Delegation.id).where(Delegation.title == "周报", Delegation.requester_id == me.id)) is None
            result = await actions.execute(session, None, me, action)
            await session.commit()
            assert action.status == "done" and "周报" in result
            fourth = await session.scalar(select(Delegation.id).where(Delegation.title == "周报", Delegation.requester_id == me.id))
            cici_user = await session.get(User, ids["cici"])
            stale = PendingAction(user_id=cici_user.id, kind="collab", summary="接受", payload={
                "op": "act", "delegation_id": fourth, "action": "accept", "version": 1})
            session.add(stale)
            await session.commit()
        await a.post(f"/api/collab/{fourth}/act", json={"action": "revise", "version": 1, "changes": {"deliverable": "周报 + 下周计划"}})
        async with SessionLocal() as session:
            stale = await session.get(PendingAction, stale.id)
            cici_user = await session.get(User, ids["cici"])
            await actions.execute(session, None, cici_user, stale)
            await session.commit()
            assert stale.status == "failed" and "变化" in stale.result  # 要求改过了：不能按旧的接受
            assert (await session.get(Delegation, fourth)).status == "requested"

        for client in (a, b, c, d):
            await client.aclose()
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(Delegation).where(Delegation.tenant_id.in_(tenants)))
            await session.execute(delete(User).where(User.tenant_id.in_(tenants)))
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenants)))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        await engine.dispose()
