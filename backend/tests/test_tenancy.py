"""工作区（租户）：账号、成员、角色、邀请、工作区之间的隔离、每个工作区自己的飞书接入。

旧用户和旧代码路径（没指定工作区的 User）都归入默认工作区，原有能力不变。
"""
import os
import uuid

import httpx
import pytest

from app import tenancy

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


def test_passwords_are_salted_and_checked_in_constant_time():
    stored = tenancy.hash_password("correct horse")
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert tenancy.verify_password("correct horse", stored)
    assert not tenancy.verify_password("wrong", stored) and not tenancy.verify_password("x", None)
    assert stored != tenancy.hash_password("correct horse")  # 每次加盐不同
    with pytest.raises(tenancy.TenancyError):
        tenancy.hash_password("short")


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay")


@db
async def test_invite_join_login_switch_and_isolation():
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import DEFAULT_TENANT_ID, Account, Integration, Tenant, User

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        # 旧代码创建用户不指定工作区：归入默认工作区
        legacy = User(feishu_open_id=f"ou_old_{tag}", name="老用户", timezone="Asia/Jakarta")
        session.add(legacy)
        await session.flush()
        assert legacy.tenant_id == DEFAULT_TENANT_ID and legacy.role == "member"
        owner_account = Account(email=f"owner-{tag}@a.test", name="Owner A", password_hash=tenancy.hash_password("owner-pass-1"))
        session.add(owner_account)
        await session.flush()
        owner_a = await tenancy.create_workspace(session, owner_account, f"Alpha {tag}")
        other_account = Account(email=f"boss-{tag}@b.test", name="Owner B", password_hash=tenancy.hash_password("boss-pass-1"))
        session.add(other_account)
        await session.flush()
        owner_b = await tenancy.create_workspace(session, other_account, f"Beta {tag}")
        session.add(Integration(key=f"k{tag}", name="TMS", secret_enc="x", tenant_id=owner_a.tenant_id, created_by=owner_a.id))
        await session.commit()
        ids = [legacy.id, owner_a.id, owner_b.id]
        tenants = [owner_a.tenant_id, owner_b.tenant_id]
        accounts = [owner_account.id, other_account.id]

    try:
        async with _client(app) as a:
            # A 的所有者登录（只在一个工作区：直接进入）
            me = (await a.post("/api/auth/login", json={"email": f"OWNER-{tag}@a.test", "password": "owner-pass-1"})).json()
            assert me["role"] == "owner" and me["tenant"]["name"] == f"Alpha {tag}"
            assert (await a.post("/api/auth/login", json={"email": f"owner-{tag}@a.test", "password": "nope"})).status_code == 400
            # 邀请 Budi：链接只用一次
            link = (await a.post("/api/tenant/invitations", json={"email": f"budi-{tag}@a.test", "role": "member"})).json()["link"]
            token = link.rsplit("/", 1)[1]
            async with _client(app) as anon:
                info = (await anon.get(f"/api/auth/invitations/{token}")).json()
                assert info["workspace"] == f"Alpha {tag}" and info["has_account"] is False
                budi = (await anon.post(f"/api/auth/invitations/{token}/accept", json={"password": "budi-pass-1", "name": "Budi"})).json()
                assert budi["role"] == "member" and budi["tenant"]["name"] == f"Alpha {tag}"
                assert (await anon.post(f"/api/auth/invitations/{token}/accept", json={"password": "budi-pass-1", "name": "Budi"})).status_code == 400
                assert (await anon.get("/api/tenant/members")).status_code == 403  # 普通成员不能管理

            # B 的所有者也邀请 Budi（同一个账号加入第二个工作区）
            async with _client(app) as b:
                await b.post("/api/auth/login", json={"email": f"boss-{tag}@b.test", "password": "boss-pass-1"})
                token_b = (await b.post("/api/tenant/invitations", json={"email": f"budi-{tag}@a.test"})).json()["link"].rsplit("/", 1)[1]
                # 隔离：B 的管理员看不到 A 的成员、接入，也改不了 A 的成员
                names = {m["name"] for m in (await b.get("/api/tenant/members")).json()}
                assert names == {"Owner B"}
                assert (await b.get("/api/integrations")).json() == []
                assert (await b.patch(f"/api/tenant/members/{owner_a.id}", json={"role": "member"})).status_code == 404
                stats = (await b.get("/api/insights/notifications")).json()
                assert {row["user"] for row in stats} <= {"Owner B"}  # 统计只算本工作区（今天新建的账号不计入天数）
            async with _client(app) as budi_client:
                await budi_client.post(f"/api/auth/invitations/{token_b}/accept", json={"password": "budi-pass-1"})
                # 再登录：两个工作区，先选；可以切换
                choose = (await budi_client.post("/api/auth/login", json={"email": f"budi-{tag}@a.test", "password": "budi-pass-1"})).json()
                assert {c["name"] for c in choose["choose"]} == {f"Alpha {tag}", f"Beta {tag}"}
                me = (await budi_client.post("/api/auth/login", json={"email": f"budi-{tag}@a.test", "password": "budi-pass-1",
                                                                     "tenant_id": str(tenants[1])})).json()
                assert me["tenant"]["name"] == f"Beta {tag}" and me["workspaces"] == 2
                switched = (await budi_client.post("/api/auth/switch", json={"tenant_id": str(tenants[0])})).json()
                assert switched["tenant"]["name"] == f"Alpha {tag}"
                assert (await budi_client.post("/api/auth/switch", json={"tenant_id": str(DEFAULT_TENANT_ID)})).status_code == 403

            # 角色规则：不能把唯一的所有者降级；停用后会话失效
            async with SessionLocal() as session:
                budi_a = (await session.execute(select(User).where(User.tenant_id == tenants[0], User.name == "Budi"))).scalars().one()
            assert (await a.patch(f"/api/tenant/members/{budi_a.id}", json={"role": "owner"})).status_code == 200
            assert (await a.patch(f"/api/tenant/members/{budi_a.id}", json={"status": "deactivated"})).status_code == 200
            async with SessionLocal() as session:
                actor = await session.get(User, owner_a.id)
                with pytest.raises(tenancy.TenancyError):
                    await tenancy.change_member(session, actor, actor, role="member")  # 不能改自己
            # 只剩一位在用的所有者时，不能把他降级（Budi 已停用，不算）
            async with SessionLocal() as session:
                budi_owner = await session.get(User, budi_a.id)
                budi_owner.status = "active"
                with pytest.raises(tenancy.TenancyError):
                    target = await session.get(User, owner_a.id)
                    budi_owner.status = "deactivated"
                    await tenancy.change_member(session, budi_owner, target, role="member")
                await session.rollback()
        async with _client(app) as budi_again:
            res = await budi_again.post("/api/auth/login", json={"email": f"budi-{tag}@a.test", "password": "budi-pass-1",
                                                                 "tenant_id": str(tenants[0])})
            assert "choose" in res.json() and {c["name"] for c in res.json()["choose"]} == {f"Beta {tag}"}  # 在 A 被停用：只剩 B
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(User).where(User.tenant_id.in_(tenants)))
            await session.execute(delete(User).where(User.id.in_(ids)))
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenants)))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        await engine.dispose()


@db
async def test_each_workspace_uses_its_own_feishu_app_and_secrets_stay_hidden():
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import DEFAULT_TENANT_ID, Account, Tenant, TenantConnection, User

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        account = Account(email=f"it-{tag}@c.test", name="IT", password_hash=tenancy.hash_password("it-pass-123"))
        session.add(account)
        await session.flush()
        owner = await tenancy.create_workspace(session, account, f"Gamma {tag}")
        await session.commit()
        tenant_id = owner.tenant_id
        # 没接飞书的工作区：拿不到任何飞书客户端（不能用默认工作区的应用替它做事）；默认工作区退回服务器配置的客户端
        assert await tenancy.feishu_for(session, tenant_id, None, fallback="server") is None
    try:
        async with _client(app) as c:
            await c.post("/api/auth/login", json={"email": f"it-{tag}@c.test", "password": "it-pass-123"})
            saved = (await c.put("/api/tenant/connections/feishu", json={"app_id": "cli_gamma", "app_secret": "s3cr3t-value",
                                                                         "tenant_key": "tk_gamma"})).json()
            assert saved["configured"] and saved["secrets"] == {"app_secret": True, "verification_token": False, "encrypt_key": False}
            assert "s3cr3t-value" not in str(saved)
            shown = (await c.get("/api/tenant/connections/feishu")).json()
            assert shown["config"] == {"app_id": "cli_gamma", "tenant_key": "tk_gamma"} and "s3cr3t-value" not in str(shown)
            # 留空不改：密钥还在
            again = (await c.put("/api/tenant/connections/feishu", json={"app_id": "cli_gamma", "app_secret": ""})).json()
            assert again["secrets"]["app_secret"] is True
        async with SessionLocal() as session:
            conn = await tenancy.connection(session, tenant_id)
            assert "s3cr3t-value" not in (conn.secrets_enc or "")  # 加密存储
            client = await tenancy.feishu_for(session, tenant_id, None, fallback="server")
            assert client.settings.feishu_app_id == "cli_gamma" and client.settings.feishu_tenant_key == "tk_gamma"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(TenantConnection).where(TenantConnection.tenant_id == tenant_id))
            await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        await engine.dispose()
