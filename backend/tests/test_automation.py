"""多维表格新增记录；定时任务里“确认，以后直接办”；自动办的事能看到、能收回、能撤销。"""
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.sources import bitable

USER = SimpleNamespace(id="u", name="Quillan", feishu_open_id="ou_me", timezone="Asia/Jakarta")
FIELDS = [
    {"field_name": "是否点早餐", "type": 3, "property": {"options": [{"name": "是"}, {"name": "否"}]}},
    {"field_name": "早餐类型", "type": 3, "property": {"options": [{"name": "无"}, {"name": "早市套餐"}, {"name": "重庆小面"}]}},
    {"field_name": "重庆小面菜单", "type": 3, "property": {"options": [{"name": "重庆小面（素面）"}, {"name": "红汤牛肉面"}]}},
    {"field_name": "备注", "type": 1},
    {"field_name": "姓名", "type": 1003},
    {"field_name": "日期", "type": 1001},
]


def test_parse_base_link():
    assert bitable.parse_target("https://x.feishu.cn/base/HR3mb05fba5j7fs40bCcdy9ZnDf?table=tblA4Y1Ev3OHMqTY&view=vew") == \
        ("HR3mb05fba5j7fs40bCcdy9ZnDf", "tblA4Y1Ev3OHMqTY")
    with pytest.raises(bitable.BaseError):
        bitable.parse_target("https://x.feishu.cn/sheets/abc")


async def test_values_follow_field_types():
    values, shown = await bitable.convert(None, USER, FIELDS, {"是否点早餐": "是", "早餐类型": "重庆小面", "重庆小面菜单": "素面"})
    assert values == {"是否点早餐": "是", "早餐类型": "重庆小面", "重庆小面菜单": "重庆小面（素面）"}  # 唯一匹配的选项
    with pytest.raises(bitable.BaseError, match="没有“炒饭”这个选项"):
        await bitable.convert(None, USER, FIELDS, {"早餐类型": "炒饭"})
    with pytest.raises(bitable.BaseError, match="创建人"):
        await bitable.convert(None, USER, FIELDS, {"姓名": "我"})
    with pytest.raises(bitable.BaseError, match="没有「午餐」这个字段"):
        await bitable.convert(None, USER, FIELDS, {"午餐": "是"})
    assert "系统生成" in bitable.describe_fields(FIELDS) and "可选：无、早市套餐、重庆小面" in bitable.describe_fields(FIELDS)


class BaseFeishu:
    def __init__(self):
        self.added, self.deleted = [], []

    async def user_api(self, user, method, path, **kwargs):
        if path.endswith("/tables") and method == "GET":
            return {"items": [{"table_id": "tblMeal", "name": "明日小厨"}]}
        if path.endswith("/fields"):
            return {"items": FIELDS}
        if path.endswith("/records/search"):
            return {"items": []}
        if path.endswith("/records") and method == "POST":
            self.added.append(kwargs["json"]["fields"])
            return {"record": {"record_id": f"rec{len(self.added)}"}}
        if method == "DELETE" and "/records/" in path:
            self.deleted.append(path.rsplit("/", 1)[1])
            return {}
        raise AssertionError((method, path))


@pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")
async def test_scheduled_task_grant_auto_run_revoke_and_undo():
    from sqlalchemy import delete, select

    from app import automation
    from app.agent.tools.base import ToolContext, execute
    from app.db import SessionLocal, engine
    from app.models import Conversation, PendingAction, ScheduledTask, User, UserDecision
    from app.proactive import actions

    feishu = BaseFeishu()
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        task = ScheduledTask(user_id=user.id, title="提交工作餐", prompt="提交", cron="0 14 * * 1-5", timezone="Asia/Jakarta",
                             next_run_at=datetime.now(UTC))
        conversation = Conversation(user_id=user.id, channel="task", external_id="t", title="提交工作餐")
        session.add_all([task, conversation])
        await session.commit()
        user_id = user.id
        try:
            args = {"base": "https://x.feishu.cn/base/HR3mb05fba5j7fs40bCcdy9ZnDf?table=tblMeal",
                    "fields": {"是否点早餐": "是", "早餐类型": "重庆小面", "重庆小面菜单": "素面"}}
            ctx = ToolContext(session, user, conversation, feishu, task=task)
            # 第一次：没授权，只准备，等用户确认
            text, error = await execute(ctx, "prepare_add_base_record", args, user_initiated=False)
            assert not error and "待确认" in text and feishu.added == []
            first = (await session.execute(select(PendingAction).where(PendingAction.user_id == user_id))).scalars().one()
            assert first.scheduled_task_id == task.id and first.status == "pending"

            # 用户点“确认，以后直接办”：这次执行，并授权这个任务、这张表
            await actions.execute(session, feishu, user, first)
            automation.grant_task(task, first)
            await session.commit()
            assert feishu.added and task.grants[0]["scope"] == {"app_token": "HR3mb05fba5j7fs40bCcdy9ZnDf", "table_id": "tblMeal"}

            # 第二次：直接提交，标记为自动办理
            ctx = ToolContext(session, user, conversation, feishu, task=task)
            text, error = await execute(ctx, "prepare_add_base_record", args, user_initiated=False)
            assert not error and "已在《明日小厨》提交" in text and len(feishu.added) == 2
            second = (await session.execute(select(PendingAction).where(
                PendingAction.user_id == user_id, PendingAction.id != first.id))).scalars().one()
            assert second.auto and second.status == "done" and automation.undoable(second)

            overview = await automation.overview(session, user)
            assert overview["grants"][0]["source"] == "task" and overview["history"][0]["action_id"] == second.id

            # 撤销：删掉提交的记录，不能再撤一次
            assert "已删除" in await automation.undo(session, feishu, user, second)
            assert feishu.deleted == ["rec2"] and not automation.undoable(second)
            decisions = (await session.execute(select(UserDecision.decision, UserDecision.via).where(
                UserDecision.user_id == user_id))).all()
            assert ("confirm", "auto") in decisions

            # 收回授权：之后又要先问
            await automation.revoke(session, user, "task", task.id, "base_record", 0)
            await session.commit()
            ctx = ToolContext(session, user, conversation, feishu, task=task)
            text, error = await execute(ctx, "prepare_add_base_record", args, user_initiated=False)
            assert not error and "待确认" in text and len(feishu.added) == 2
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


def test_client_token_is_stable_uuid_v4():
    import uuid as _uuid

    from app.proactive.actions import idempotency_key

    user, action = SimpleNamespace(id="u1"), SimpleNamespace(id=42)
    key = idempotency_key(user, action)
    parsed = _uuid.UUID(key)
    assert parsed.version == 4 and parsed.variant == _uuid.RFC_4122
    assert key == idempotency_key(user, action)  # 同一个操作重试时不变
    assert key != idempotency_key(user, SimpleNamespace(id=43))
