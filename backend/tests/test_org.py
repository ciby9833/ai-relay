"""组织架构：新建工作区、部门树、成员资料（部门 / 上级 / 岗位 / 负责什么）、团队与汇总、飞书通讯录同步。

用虚构的数据，飞书用一个假的客户端。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import tenancy

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")
PASSWORD = "org-pass-123"


class FakeDirectory:
    """假的飞书通讯录：总部 → 运营中心 → Medan 站；Budi 的上级是 Ana。"""

    settings = None

    def __init__(self, ana: str, budi: str):
        self.ana, self.budi = ana, budi

    async def tenant_api(self, method, path, **kwargs):
        if path == "/contact/v3/departments/0/children":
            return {"items": [
                {"open_department_id": "od-ops", "name": "运营中心", "parent_department_id": "0", "leader_user_id": self.ana},
                {"open_department_id": "od-medan", "name": "Medan 站", "parent_department_id": "od-ops"},
            ], "has_more": False}
        if path == f"/contact/v3/users/{self.ana}":
            return {"user": {"department_ids": ["od-ops"], "job_title": "运营总监"}}
        if path == f"/contact/v3/users/{self.budi}":
            return {"user": {"department_ids": ["od-medan"], "leader_user_id": self.ana, "job_title": "站长"}}
        raise AssertionError(path)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay")


async def test_organization_profiles_teams_and_sync():
    from sqlalchemy import delete, select

    from app import org
    from app.agent.loop import build_context
    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import Account, Conversation, Department, FollowUp, Team, Tenant, User
    from app.proactive import attention

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        account = Account(email=f"ana-{tag}@org.test", name="Ana", password_hash=tenancy.hash_password(PASSWORD))
        session.add(account)
        await session.flush()
        ana = await tenancy.create_workspace(session, account, f"Org {tag}")
        ana.feishu_open_id = f"ou_ana_{tag}"
        budi_account = Account(email=f"budi-{tag}@org.test", name="Budi", password_hash=tenancy.hash_password(PASSWORD))
        session.add(budi_account)
        await session.flush()
        budi = User(tenant_id=ana.tenant_id, account_id=budi_account.id, name="Budi", email=budi_account.email,
                    timezone="Asia/Jakarta", feishu_open_id=f"ou_budi_{tag}")
        session.add(budi)
        await session.commit()
        tenant_id, ana_id, budi_id = ana.tenant_id, ana.id, budi.id
    tenants = [tenant_id]

    a, b = _client(app), _client(app)
    try:
        await a.post("/api/auth/login", json={"email": f"ana-{tag}@org.test", "password": PASSWORD})
        await b.post("/api/auth/login", json={"email": f"budi-{tag}@org.test", "password": PASSWORD})

        # 管理员建部门树；部门不能挂到自己的下级下面
        ops = (await a.post("/api/org/departments", json={"name": "运营中心"})).json()
        medan = (await a.post("/api/org/departments", json={"name": "Medan 站", "parent_id": ops["id"]})).json()
        assert (await a.patch(f"/api/org/departments/{ops['id']}", json={"parent_id": medan["id"]})).status_code == 400
        assert (await b.post("/api/org/departments", json={"name": "我自己的部门"})).status_code == 403

        # 成员资料：管理员设部门和上级；上下级不能成环；本人只能改岗位和负责什么
        assert (await a.patch(f"/api/org/members/{budi_id}", json={"department_id": medan["id"], "manager_id": str(ana_id)})).status_code == 200
        assert (await a.patch(f"/api/org/members/{ana_id}", json={"manager_id": str(budi_id)})).status_code == 400
        assert (await b.patch(f"/api/org/members/{budi_id}", json={"manager_id": None})).status_code == 403
        assert (await b.patch(f"/api/org/members/{ana_id}", json={"title": "x"})).status_code == 403
        mine = (await b.patch(f"/api/org/members/{budi_id}", json={"title": "Medan 站长", "responsibilities": "Medan 线路、客户 PT Maju"})).json()
        assert mine["title"] == "Medan 站长" and set(mine["locks"]) == {"department_id", "manager_id", "title", "responsibilities"}  # 管理员和本人改过的都锁住
        assert (await b.get("/api/org/me")).json()["department"] == "运营中心 / Medan 站"
        everyone = (await b.get("/api/org")).json()  # 成员都能看组织架构
        assert {m["name"] for m in everyone["members"]} == {"Ana", "Budi"} and not everyone["can_edit"]

        async with SessionLocal() as session:
            budi = await session.get(User, budi_id)
            # 提醒分级用 Relay 的上下级：Ana 是 Budi 的直属上级
            chain = await attention.leaders(session, None, budi)
            assert [(c["name"], c["depth"]) for c in chain] == [("Ana", 1)]
            # 助理的上下文里有他的组织资料（事实，不是规则）
            conversation = Conversation(user_id=budi_id, channel="web")
            session.add(conversation)
            await session.flush()
            context = await build_context(session, budi, conversation, "你好")
            assert "部门：运营中心 / Medan 站" in context and "直属上级：Ana" in context and "负责：Medan 线路" in context
            # 团队汇总的数据：一件逾期、一件在等别人
            now = datetime.now(UTC)
            session.add_all([FollowUp(user_id=budi_id, key=f"t1-{tag}", kind="request", owner="me", title="机密：客户投诉",
                                      due_at=now - timedelta(days=1), signal_ids=[]),
                             FollowUp(user_id=budi_id, key=f"t2-{tag}", kind="waiting", owner="others", title="等回复", signal_ids=[])])
            await session.commit()

        # 团队：负责人看到数量，看不到内容；不是负责人看不到
        team = (await a.post("/api/org/teams", json={"name": "Medan 项目组", "lead_id": str(ana_id), "member_ids": [str(budi_id)]})).json()
        summary = (await a.get(f"/api/org/teams/{team['id']}/summary")).json()
        assert summary == [{"id": str(budi_id), "name": "Budi", "open": 1, "overdue": 1, "waiting": 1}]
        assert "客户投诉" not in str(summary)
        assert (await b.get(f"/api/org/teams/{team['id']}/summary")).status_code == 403

        # 飞书通讯录同步：部门树、上级、岗位；Budi 自己改过的岗位不被覆盖；再同步一次不重复
        async with SessionLocal() as session:
            actor = await session.get(User, ana_id)
            directory = FakeDirectory(f"ou_ana_{tag}", f"ou_budi_{tag}")
            await session.execute(select(User).where(User.id == budi_id))
            (await session.get(User, budi_id)).manager_id = None
            await session.flush()
            stats = await org.sync_from_feishu(session, actor, directory)
            await org.sync_from_feishu(session, actor, directory)
            await session.commit()
            assert stats["departments"] == 2
            synced = {d.external_id: d for d in (await session.execute(select(Department).where(
                Department.tenant_id == tenant_id, Department.source == "feishu"))).scalars()}
            assert set(synced) == {"od-ops", "od-medan"} and synced["od-medan"].parent_id == synced["od-ops"].id
            assert synced["od-ops"].lead_id == ana_id
            budi = await session.get(User, budi_id)
            ana = await session.get(User, ana_id)
            assert budi.manager_id is None  # 上级是管理员手工设过的（锁住），同步不覆盖
            assert budi.title == "Medan 站长" and ana.title == "运营总监"
            assert ana.department_id == synced["od-ops"].id

        # 已登录的账号新建一个工作区，切换过去，自己是所有者
        created = (await b.post("/api/auth/workspaces", json={"name": f"Budi 的小组 {tag}"})).json()
        assert created["role"] == "owner" and created["tenant"]["name"] == f"Budi 的小组 {tag}" and created["workspaces"] == 2
        tenants.append(uuid.UUID(created["tenant"]["id"]))
    finally:
        await a.aclose()
        await b.aclose()
        async with SessionLocal() as session:
            await session.execute(delete(Team).where(Team.tenant_id.in_(tenants)))
            await session.execute(delete(FollowUp).where(FollowUp.user_id == budi_id))
            await session.execute(delete(Conversation).where(Conversation.user_id == budi_id))
            for tid in tenants:
                await session.execute(User.__table__.update().where(User.tenant_id == tid).values(department_id=None, manager_id=None))
            await session.execute(delete(Department).where(Department.tenant_id.in_(tenants)))
            await session.execute(delete(User).where(User.tenant_id.in_(tenants)))
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenants)))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        await engine.dispose()
