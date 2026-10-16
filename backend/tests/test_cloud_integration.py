"""真实数据库、假飞书：验证审批更新和确认操作不重复。"""
import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


async def test_approval_results_and_cc_are_tracked_once():
    from app.db import SessionLocal, engine
    from app.models import FollowUp, Signal, SourceState, User
    from app.proactive import items
    from app.sources import approval

    class Feishu:
        status = 1
        read = False
        new_cc = False
        async def tenant_api(self, method, path, **kwargs):
            topic = kwargs["params"]["topic"]
            rows = []
            if topic == "3":
                rows = [{"process_code": "initiated1", "process_status": self.status, "title": "我的申请"},
                        {"process_code": "history", "process_status": 2, "title": "旧申请"}]
            if topic == ("18" if self.read else "17"):
                rows = [{"process_code": "cc1", "task_id": "cc-task", "process_status": 2, "title": "抄送"}]
                if self.new_cc:
                    rows.append({"process_code": "cc2", "task_id": "cc-task2", "process_status": 2, "title": "新抄送"})
            return {"tasks": rows}

    f = Feishu()
    async with SessionLocal() as s:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="审批测试", timezone="Asia/Jakarta")
        s.add(user)
        await s.commit()
        uid = user.id
    try:
        async with SessionLocal() as s:
            user = await s.get(User, uid)
            state = SourceState(user_id=uid, source="approval", cursor={})
            s.add(state)
            assert await approval.sync(s, f, user, state) == 3
            await items.track(s, f, user)
            found = {i.key: i for i in (await s.execute(select(FollowUp).where(FollowUp.user_id == uid))).scalars()}
            # 抄送只知会、历史结果只建档：只剩我发起且审批中的那件，静默放进“等别人”
            assert list(found) == ["approval-update:initiated:initiated1"]
            initiated = found["approval-update:initiated:initiated1"]
            assert (initiated.kind, initiated.owner) == ("waiting", "others") and initiated.announced_at and initiated.remind_at
            cc_signal = (await s.execute(select(Signal).where(Signal.user_id == uid, Signal.external_id == "cc:cc1"))).scalar_one()
            assert cc_signal.status == "done"  # 首次同步的历史抄送只建档，不进简报
            assert await approval.sync(s, f, user, state) == 0
            f.new_cc = True
            assert await approval.sync(s, f, user, state) == 1
            new_cc = (await s.execute(select(Signal).where(Signal.user_id == uid, Signal.external_id == "cc:cc2"))).scalar_one()
            assert new_cc.status == "ignored"  # 初始化之后新来的抄送：不建事项，只作简报素材
            f.read = True
            assert await approval.sync(s, f, user, state) == 0  # 抄送变已读不会新增

            # 通过：关闭“等别人”，只告诉一声，不留待办
            f.status = 2
            assert await approval.sync(s, f, user, state) == 1
            await items.track(s, f, user)
            await s.refresh(initiated)
            assert initiated.status == "done"
            facts = await items.result_facts(s, user)
            assert len(facts) == 1 and "已通过" in facts[0]
            assert await items.result_facts(s, user) == []

            # 驳回：变成“等你”，提示修改后重新提交
            f.status = 3
            assert await approval.sync(s, f, user, state) == 1
            await items.track(s, f, user)
            await s.refresh(initiated)
            assert (initiated.status, initiated.kind, initiated.owner) == ("open", "review", "me")
            assert "被驳回" in initiated.title and "重新提交" in initiated.next_step and initiated.announced_at is None
    finally:
        async with SessionLocal() as s:
            await s.delete(await s.get(User, uid))
            await s.commit()
        await engine.dispose()


async def test_confirm_concurrency_ownership_and_timeout_persistence():
    from app.agent.tools.base import ToolContext, execute as execute_tool
    from app.db import SessionLocal, engine
    from app.models import PendingAction, User
    from app.proactive import actions, callbacks

    class Feishu:
        def __init__(self):
            self.calls = 0
            self.fail = False
        async def user_api(self, *args, **kwargs):
            self.calls += 1
            await asyncio.sleep(0.02)
            if self.fail:
                raise httpx.ReadTimeout("ambiguous result")
            return {"document": {"document_id": "created"}}

    f = Feishu()
    async with SessionLocal() as s:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="写入测试", timezone="Asia/Jakarta")
        other = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="他人", timezone="Asia/Jakarta")
        s.add_all([user, other])
        await s.flush()
        action = PendingAction(user_id=user.id, kind="cloud_write", summary="创建文档",
                               payload={"operation": "create_doc", "arguments": {"title": "测试"}, "body": "预览"})
        s.add(action)
        await s.commit()
        uid, oid, aid, open_id = user.id, other.id, action.id, user.feishu_open_id
    try:
        async with SessionLocal() as s:
            with pytest.raises(actions.ActionError):
                await actions.own_action(s, await s.get(User, oid), aid)

        async def confirm():
            async with SessionLocal() as s:
                user = await s.get(User, uid)
                action = await actions.own_action(s, user, aid)
                result = await actions.execute(s, f, user, action)
                await s.commit()
                return result
        await asyncio.gather(confirm(), confirm())
        assert f.calls == 1
        async with SessionLocal() as s:
            action = await s.get(PendingAction, aid)
            assert action.status == "done" and action.payload["response"]["document"]["document_id"] == "created"
            action.status = "pending"
            await s.commit()
        f.fail = True
        # 对话工具的 savepoint 不能回滚 failed 状态。
        from types import SimpleNamespace
        async with SessionLocal() as s:
            ctx = ToolContext(s, await s.get(User, uid), SimpleNamespace(channel="web"), f)
            result, error = await execute_tool(ctx, "confirm_action", {"action_id": aid})
            assert "结果未知" in result
            await s.commit()
        await confirm()
        assert f.calls == 2
        async with SessionLocal() as s:
            action = await s.get(PendingAction, aid)
            assert action.status == "failed"
            action.status = "pending"
            await s.commit()
        # 飞书回调同样保留失败状态。
        result = await callbacks.handle_card_action(f, open_id, {"relay": "confirm", "action_id": aid})
        assert not result["ok"] and "结果未知" in result["message"]
        async with SessionLocal() as s:
            assert (await s.get(PendingAction, aid)).status == "failed"
        await confirm()
        assert f.calls == 3
    finally:
        async with SessionLocal() as s:
            await s.delete(await s.get(User, uid))
            await s.delete(await s.get(User, oid))
            await s.commit()
        await engine.dispose()
