"""飞书任务：别人派给他的未完成任务建成事项，他在飞书里完成后自动结束；没授权时跳过，不反复提醒重新登录。"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class Feishu:
    def __init__(self, me):
        self.me, self.open = me, []
        self.calls = []

    async def user_api(self, user, method, path, **kwargs):
        self.calls.append(path)
        if path == "/task/v2/tasks":
            assert kwargs["params"]["type"] == "my_tasks" and kwargs["params"]["completed"] == "false"
            return {"items": self.open, "has_more": False}
        if path.startswith("/contact/v3/users/"):
            return {"user": {"name": "Budi Santoso"}}
        raise AssertionError(path)

    def task(self, guid, creator, summary, due=None):
        return {"guid": guid, "summary": summary, "creator": {"id": creator, "type": "user"}, "url": f"https://applink.feishu.cn/task/{guid}",
                "created_at": str(int(datetime.now(UTC).timestamp() * 1000)),
                "due": {"timestamp": str(int(due.timestamp() * 1000)), "is_all_day": False} if due else None}


@db
async def test_tasks_assigned_by_others(monkeypatch):
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import FollowUp, SourceState, User
    from app.proactive import engine as proactive, items

    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta",
                    feishu_scopes="task:task:read contact:user.base:readonly")
        session.add(user)
        await session.commit()
        user_id = user.id
        feishu = Feishu(user.feishu_open_id)
        only_tasks = proactive.merged({"sources": {k: k == "task" for k in proactive.merged({})["sources"]}})
        tag = uuid.uuid4().hex[:6]
        try:
            feishu.open = [feishu.task(f"old-{tag}", "ou_budi", "上周的任务"), feishu.task(f"self-{tag}", user.feishu_open_id, "我自己的备忘")]
            await proactive.sync_sources(session, feishu, user, only_tasks, force=True)
            feishu.open.append(feishu.task(f"new-{tag}", "ou_budi", "周五前更新 Medan 网点 SOP", datetime.now(UTC) + timedelta(days=2)))
            await proactive.sync_sources(session, feishu, user, only_tasks, force=True)
            await items.track(session, feishu, user)
            found = {i.key: i for i in (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars()}
            assert set(found) == {f"task:old-{tag}", f"task:new-{tag}"}  # 自己建给自己的不算
            new = found[f"task:new-{tag}"]
            assert new.title == "Budi Santoso 派给你的任务：周五前更新 Medan 网点 SOP" and new.due_at and new.announced_at is None
            assert found[f"task:old-{tag}"].announced_at is not None  # 第一次同步：只静默建档

            feishu.open = [t for t in feishu.open if t["guid"] != f"new-{tag}"]  # 他在飞书里完成了
            await proactive.sync_sources(session, feishu, user, only_tasks, force=True)
            await items.advance(session, user)
            await session.refresh(new)
            assert new.status == "done" and "完成" in new.resolution

            # 没授权任务权限：跳过并说明，不调接口，也不触发重新登录提醒
            user.feishu_scopes = "contact:user.base:readonly"
            feishu.calls.clear()
            await proactive.sync_sources(session, feishu, user, only_tasks, force=True)
            state = await session.get(SourceState, (user_id, "task"))
            assert "task:task:read" in state.last_error and "/task/v2/tasks" not in feishu.calls
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
