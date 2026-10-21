"""长期任务的验收：清单只有用户能改；做到要有证据；结束前独立核对，过不了就退回，两轮后交给用户；写入后读回核对。

场景用 Nikki 那件事：用户只要“让 Nikki 给个结果”。她先回“1”，再回“预计月底前完成”，最后才说“已经同步给需求人了”。
"""
import os
import uuid
from datetime import UTC, datetime

import pytest

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class Judge:
    """按剧本给出核对结论，并记下核对者看到了什么。"""

    def __init__(self):
        self.seen, self.verdicts = [], []

    async def __call__(self, system, prompt, tool):
        self.seen.append(prompt)
        return self.verdicts.pop(0)


@db
async def test_acceptance_flow(monkeypatch):
    from sqlalchemy import delete

    from app.agent.tools.base import ToolContext, execute
    from app.db import SessionLocal, engine
    from app.missions import criteria, service
    from app.models import Conversation, MissionLog, PendingAction, User
    from app.proactive import llm

    judge = Judge()
    monkeypatch.setattr(llm, "complete_structured", judge)

    async def no_notify(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "notify", no_notify)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        home = Conversation(user_id=user.id, channel="home", title="主线")
        session.add(home)
        await session.flush()
        try:
            ctx = ToolContext(session, user, home, None)
            text, error = await execute(ctx, "start_mission", {"title": "盯 Nikki", "goal": "让 Nikki 给个结果",
                                                              "criteria": ["Nikki 给出需求进度的结果"]})
            assert not error and "验收清单" in text
            from sqlalchemy import select
            from app.models import Mission

            mission = (await session.execute(select(Mission).where(Mission.user_id == user_id))).scalars().one()
            mctx = ToolContext(session, user, await session.get(Conversation, mission.conversation_id), None, mission=mission)

            # 清单在任务里改不了：没有这个工具
            text, error = await execute(mctx, "edit_mission_criteria", {"mission_id": mission.id, "criteria": ["给出详细清单"]},
                                        user_initiated=False)
            assert error

            # 没有证据不能算办成
            text, error = await execute(mctx, "complete_mission", {"result": "Nikki 已经给了结果", "success": True}, user_initiated=False)
            assert error and "还没有证据" in text
            # 证据要指向真实发生的事
            text, error = await execute(mctx, "check_criterion", {"criterion_id": 1, "met": True, "evidence": "她回了"},
                                        user_initiated=False)
            assert error and "证据编号" in text
            other = PendingAction(user_id=user_id, kind="send_chat", summary="别的任务发的", payload={}, status="done")
            session.add(other)
            await session.flush()
            text, error = await execute(mctx, "check_criterion", {"criterion_id": 1, "met": True, "evidence": "x", "ref": f"action:{other.id}"},
                                        user_initiated=False)
            assert error and "不是这个任务里的" in text

            # 她回了“1”和“预计月底前完成”：拿来当证据，核对者不认
            reply = MissionLog(mission_id=mission.id, kind="reply", text="[对方回复了]（和 Nikki 的私聊）\n- Nikki：1\n- Nikki：预计月底前完成")
            session.add(reply)
            await session.flush()
            text, error = await execute(mctx, "check_criterion", {"criterion_id": 1, "met": True, "evidence": "Nikki 回复了", "ref": f"log:{reply.id}"},
                                        user_initiated=False)
            assert not error
            await session.flush()
            await session.refresh(mission, ["criteria"])
            assert mission.criteria[0]["status"] == "met"
            judge.verdicts.append({"criteria": [{"id": 1, "supported": False, "why": "只是答应月底前完成，还没有结果"}],
                                   "goal_supported": False, "result_faithful": False, "issues": ["把承诺说成了完成"]})
            text, error = await execute(mctx, "complete_mission", {"result": "Nikki 已经给出结果", "success": True}, user_initiated=False)
            assert not error and "独立核对没通过" in text and "月底前" in text
            assert mission.status != "done" and mission.check_rounds == 1 and mission.criteria[0]["status"] == "open"
            await session.flush()
            await session.refresh(mission, ["criteria"])
            assert mission.criteria[0]["status"] == "open"
            assert "预计月底前完成" in judge.seen[0] and "让 Nikki 给个结果" in judge.seen[0]  # 核对者看到原话和证据原文

            # 后来她真的同步了：有证据，核对通过才结束
            done = MissionLog(mission_id=mission.id, kind="reply", text="[对方回复了]\n- Nikki：已经同步给需求人了，结论是下周上线")
            session.add(done)
            await session.flush()
            await execute(mctx, "check_criterion", {"criterion_id": 1, "met": True, "evidence": "Nikki 说已同步，结论是下周上线", "ref": f"log:{done.id}"},
                          user_initiated=False)
            judge.verdicts.append({"criteria": [{"id": 1, "supported": True, "why": "她给出了结论"}], "goal_supported": True, "result_faithful": True, "issues": []})
            text, error = await execute(mctx, "complete_mission", {"result": "Nikki 已同步给需求人：下周上线", "success": True}, user_initiated=False)
            assert not error and mission.status == "done"

            # 两次真正的核验失败自动转交用户，且事件和状态能从数据库回读。
            twice = await service.create(session, user, "复核业务结果", "降低异常件")
            twice.criteria = criteria.new_list(["异常件数量下降"])
            tctx = ToolContext(session, user, await session.get(Conversation, twice.conversation_id), None, mission=twice)
            for _ in range(2):
                twice.criteria = [{**twice.criteria[0], "status": "met", "evidence": "完成", "ref": f"log:{done.id}"}]
                text, error = await execute(tctx, "complete_mission", {"result": "完成", "success": True}, user_initiated=False)
                assert not error  # 跨任务证据被确定性拒绝，拒绝记录仍提交
            await session.flush()
            await session.refresh(twice)
            assert twice.status == "asking" and twice.check_rounds == 2 and tctx.stop_turn
            assert twice.criteria[0]["status"] == "open"
            from app.models import AssuranceEvent
            recorded = (await session.scalars(select(AssuranceEvent).where(AssuranceEvent.mission_id == twice.id))).all()
            assert [e.kind for e in recorded].count("completion_check") == 2
            assert [e.kind for e in recorded].count("human_takeover") == 1
            await service.answer(session, twice, "已补充业务来源，请重新核验")
            assert twice.check_rounds == 0 and twice.status == "active"
            assert twice.criteria[0]["status"] == "open"

            # 两轮核对不过：不再自己反复改，交给用户
            stuck = await service.create(session, user, "盯 Budi", "让 Budi 交报价", instruction="让 Budi 交报价")
            stuck.criteria = criteria.new_list(["Budi 交了报价"])
            stuck.check_rounds = criteria.MAX_CHECK_ROUNDS
            stuck.criteria[0].update(status="met", evidence="x", ref=f"log:{done.id}")
            sctx = ToolContext(session, user, await session.get(Conversation, stuck.conversation_id), None, mission=stuck)
            text, error = await execute(sctx, "complete_mission", {"result": "交了", "success": True}, user_initiated=False)
            assert error and "ask_user" in text
            # 办不成可以如实结束
            text, error = await execute(sctx, "complete_mission", {"result": "Budi 说做不了，需要你定", "success": False}, user_initiated=False)
            assert not error and stuck.status == "failed"

            # 用户改清单：没改的条目保留状态，新的从头开始
            keep = await service.create(session, user, "约会", "约齐人开会", instruction="约齐人开会")
            keep.criteria = criteria.new_list(["张三接受邀请", "李四接受邀请"])
            keep.criteria[0].update(status="met", evidence="接受了", ref=f"log:{done.id}")
            uctx = ToolContext(session, user, home, None)
            text, error = await execute(uctx, "edit_mission_criteria", {"mission_id": keep.id, "criteria": ["张三接受邀请", "王五接受邀请"]})
            assert not error and [c["status"] for c in keep.criteria] == ["met", "open"]
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


async def test_writes_are_read_back():
    """填表后读回来不一致、记录缺字段、消息读不到：如实标出；长期任务不能拿它当证据。"""
    from types import SimpleNamespace

    from app.proactive import verify

    class Feishu:
        def __init__(self, cells, record, message):
            self.cells, self.record, self.message = cells, record, message

        async def user_api(self, user, method, path, **kwargs):
            if "/values_batch_get" in path or "/values_batch" in path:
                return {"valueRanges": [{"range": f"s1!{c}:{c}", "values": [[v]]} for c, v in self.cells.items()]}
            if "/records/" in path:
                return {"record": {"fields": self.record}}
            return {"items": [self.message] if self.message else []}

        tenant_api = None

    user = SimpleNamespace(id=1)
    sheet = SimpleNamespace(id=1, kind="cloud_write", payload={"operation": "fill_sheet_cells", "spreadsheet_token": "t", "sheet_id": "s1",
                                                               "cells": [{"cell": "S49", "after": "Agreed"}, {"cell": "S50", "after": "IT"}]})
    import app.sources.sheets as sheets

    async def read_cells(feishu, user, token, sheet_id, cells):
        return feishu.cells

    sheets_read = sheets.read_cells
    sheets.read_cells = read_cells
    try:
        ok = await verify.check(Feishu({"S49": "Agreed", "S50": "IT"}, {}, None), user, sheet)
        bad = await verify.check(Feishu({"S49": "Agreed", "S50": ""}, {}, None), user, sheet)
    finally:
        sheets.read_cells = sheets_read
    assert ok["ok"] is True and bad["ok"] is False and "S50" in bad["detail"]

    record = SimpleNamespace(id=2, kind="base_record", payload={"app_token": "a", "table_id": "t", "record_id": "r1",
                                                                "fields": {"姓名": "Quillan", "套餐": "A", "备注": ""}})
    assert (await verify.check(Feishu({}, {"姓名": "Quillan", "套餐": [{"text": "A"}]}, None), user, record))["ok"] is True
    missing = await verify.check(Feishu({}, {"姓名": "Quillan"}, None), user, record)
    assert missing["ok"] is False and "套餐" in missing["detail"]
    wrong = await verify.check(Feishu({}, {"姓名": "Quillan", "套餐": "B"}, None), user, record)
    assert wrong["ok"] is False and "套餐" in wrong["detail"]  # 非空但错误也不能通过

    message = SimpleNamespace(id=3, kind="send_chat", payload={"message_id": "om_1", "as_user": True})
    assert (await verify.check(Feishu({}, {}, {"message_id": "om_1"}), user, message))["ok"] is True
    assert (await verify.check(Feishu({}, {}, None), user, message))["ok"] is False

    class Broken:
        async def user_api(self, *args, **kwargs):
            raise RuntimeError("timeout")

    unknown = SimpleNamespace(id=4, kind="send_chat", payload={"message_id": "om_2", "as_user": True})
    outcome = await verify.record(Broken(), user, unknown)
    assert outcome["ok"] is None and unknown.payload["verified"]["ok"] is None  # 没能核对 ≠ 失败
