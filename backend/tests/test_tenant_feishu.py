"""每个工作区接自己的飞书应用：事件、按钮回调按工作区路由；名册、飞书身份、群消息按工作区隔离。

用虚构的数据，不调用真实的飞书。
"""
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app import tenancy

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class FakeFeishu:
    def __init__(self, tenant_key: str):
        self.settings = SimpleNamespace(feishu_tenant_key=tenant_key, feishu_app_id="cli_fake")

    async def bot_open_id(self):
        return "ou_bot"

    async def user_name(self, open_id):
        return {"ou_sender": "Rafi"}.get(open_id)

    async def tenant_api(self, method, path, **kwargs):
        return {"name": "测试群"}


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay")


async def _workspace(session, tag, name, app_id):
    from app.models import Account

    account = Account(email=f"{name.lower()}-{tag}@x.test", name=f"Owner {name}", password_hash=tenancy.hash_password("owner-pass-1"))
    session.add(account)
    await session.flush()
    owner = await tenancy.create_workspace(session, account, f"{name} {tag}")
    await tenancy.save_feishu(session, owner, {"app_id": f"{app_id}_{tag}", "app_secret": "s3cret", "tenant_key": f"tk_{name}_{tag}",
                                               "verification_token": f"vt-{name}-{tag}"})
    return owner


async def test_events_and_card_clicks_reach_the_right_workspace(monkeypatch):
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import Account, Tenant, TenantConnection, User
    from app.proactive import callbacks

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        owner = await _workspace(session, tag, "Gamma", "cli_gamma")
        bare_account = Account(email=f"bare-{tag}@x.test", name="Bare", password_hash=tenancy.hash_password("owner-pass-1"))
        session.add(bare_account)
        await session.flush()
        bare = await tenancy.create_workspace(session, bare_account, f"Bare {tag}")  # 没接飞书
        # 同一个飞书应用不能同时接到两个工作区（事件只能发到一个地址）
        with pytest.raises(tenancy.TenancyError):
            await tenancy.save_feishu(session, bare, {"app_id": f"cli_gamma_{tag}"})
        await session.commit()
        gamma, bare_id = owner.tenant_id, bare.tenant_id

    clicks = []

    async def record(feishu, operator, value, message_id, tenant_id=None):
        clicks.append((feishu.settings.feishu_app_id, operator, tenant_id))
        return {"ok": True, "message": "好的", "card": None, "open_id": operator}

    monkeypatch.setattr(callbacks, "handle_card_action", record)
    try:
        async with _client(app) as c:
            url = f"/api/feishu/events/{gamma}"
            # 只认这个工作区自己的 verification token
            assert (await c.post(url, json={"type": "url_verification", "token": "vt-default", "challenge": "x"})).status_code == 403
            ok = await c.post(url, json={"type": "url_verification", "token": f"vt-Gamma-{tag}", "challenge": "c1"})
            assert ok.json() == {"challenge": "c1"}
            # 没接飞书的工作区、不存在的工作区：没有这个地址
            assert (await c.post(f"/api/feishu/events/{bare_id}", json={"token": "x"})).status_code == 404
            assert (await c.post(f"/api/feishu/events/{uuid.uuid4()}", json={"token": "x"})).status_code == 404
            # 卡片按钮：用这个工作区的飞书应用处理，只在这个工作区里找点按钮的人
            click = {"schema": "2.0", "header": {"event_id": f"e-{tag}", "token": f"vt-Gamma-{tag}", "event_type": "card.action.trigger",
                                                 "tenant_key": f"tk_Gamma_{tag}"},
                     "event": {"operator": {"open_id": "ou_clicker"}, "action": {"value": {"relay": "item_done", "item_id": 1}},
                               "context": {"open_message_id": "om_card"}}}
            await c.post(url, json=click)
            assert clicks == [(f"cli_gamma_{tag}", "ou_clicker", gamma)]
            # 别的飞书企业发来的（tenant_key 不对）：不处理
            click["header"]["tenant_key"] = "tk_someone_else"
            await c.post(url, json=click)
            assert len(clicks) == 1
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(TenantConnection).where(TenantConnection.tenant_id.in_([gamma, bare_id])))
            await session.execute(delete(User).where(User.tenant_id.in_([gamma, bare_id])))
            await session.execute(delete(Tenant).where(Tenant.id.in_([gamma, bare_id])))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        await engine.dispose()


async def test_people_identities_and_group_messages_stay_inside_their_workspace():
    from sqlalchemy import delete, select

    from app.api import feishu_events
    from app.db import SessionLocal, engine
    from app.models import DEFAULT_TENANT_ID, Account, ChatMessage, FeishuEvent, Person, Signal, Tenant, TenantConnection, User
    from app.proactive import chats
    from app.sources import people

    tag = uuid.uuid4().hex[:8]
    shared = f"ou_shared_{tag}"  # 同一个 open_id 在两个工作区各有一位成员（两家公司各自的飞书应用）
    async with SessionLocal() as session:
        owner = await _workspace(session, tag, "Delta", "cli_delta")
        delta = owner.tenant_id
        here = User(tenant_id=delta, feishu_open_id=shared, name=f"Kirana {tag}", timezone="Asia/Jakarta")
        there = User(feishu_open_id=shared, name=f"Kirana {tag}", timezone="Asia/Jakarta")  # 默认工作区
        session.add_all([here, there])
        await session.commit()
        here_id, there_id = here.id, there.id

    message = {"message_id": f"om_{tag}", "chat_id": f"oc_{tag}", "chat_type": "group", "message_type": "text",
               "content": '{"text":"@Kirana 周五前把报价单发我"}',
               "mentions": [{"key": "@_user_1", "id": {"open_id": shared}, "name": f"Kirana {tag}"}]}
    try:
        await feishu_events._watch_group_message(FakeFeishu(f"tk_Delta_{tag}"), message, "ou_sender", [shared], tenant_id=delta)
        async with SessionLocal() as session:
            # @ 只提醒这个工作区里的那位，不提醒另一家公司里 open_id 相同的人
            assert await session.scalar(select(Signal.id).where(Signal.user_id == here_id, Signal.kind == "mention")) is not None
            assert await session.scalar(select(Signal.id).where(Signal.user_id == there_id)) is None
            # 名册和群消息都记在这个工作区
            rows = (await session.execute(select(Person.tenant_id, Person.open_id).where(Person.open_id.in_([shared, "ou_sender"])))).all()
            assert set(rows) == {(delta, shared), (delta, "ou_sender")}
            stored = (await session.execute(select(ChatMessage.tenant_id).where(ChatMessage.message_id == f"om_{tag}"))).scalars().all()
            assert stored == [delta]
            # 别的工作区按名字找不到这个工作区名册里的人
            assert await people.find(session, None, "Rafi", tenant_id=DEFAULT_TENANT_ID) == []
            assert [p["open_id"] for p in await people.find(session, None, "Rafi", tenant_id=delta)] == ["ou_sender"]
            # 起草回复时找群聊背景：只看自己工作区的群
            there_user = await session.get(User, there_id)
            here_user = await session.get(User, here_id)
            assert await chats.related(session, there_user, ["报价单"]) == []
            assert [m.message_id for m in await chats.related(session, here_user, ["报价单"])] == [f"om_{tag}"]

        # 跨公司的外部群：两个工作区的应用都收到同一条消息，各存一份
        await feishu_events._watch_group_message(FakeFeishu("tk"), message, "ou_sender", [shared])
        async with SessionLocal() as session:
            stored = (await session.execute(select(ChatMessage.tenant_id).where(ChatMessage.message_id == f"om_{tag}"))).scalars().all()
            assert sorted(map(str, stored)) == sorted([str(delta), str(DEFAULT_TENANT_ID)])
            assert await session.scalar(select(Signal.id).where(Signal.user_id == there_id, Signal.kind == "mention")) is not None

        # 事件只接受这个工作区绑定的那家飞书企业
        event_id = f"ev_{tag}"
        await feishu_events.dispatch_event(FakeFeishu(f"tk_Delta_{tag}"), {"header": {"event_id": event_id, "tenant_key": "tk_other",
                                                                                     "event_type": "im.message.receive_v1"}}, delta)
        async with SessionLocal() as session:
            assert await session.get(FeishuEvent, event_id) is None
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(ChatMessage).where(ChatMessage.message_id == f"om_{tag}"))
            await session.execute(delete(Person).where(Person.open_id.in_([shared]) | (Person.tenant_id == delta)))
            await session.execute(delete(Signal).where(Signal.user_id.in_([here_id, there_id])))
            await session.execute(delete(TenantConnection).where(TenantConnection.tenant_id == delta))
            await session.execute(delete(User).where(User.id.in_([here_id, there_id]) | (User.tenant_id == delta)))
            await session.execute(delete(Tenant).where(Tenant.id == delta))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        await engine.dispose()
