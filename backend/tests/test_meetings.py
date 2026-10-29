"""会议：会前准备只用确实相关的材料，找不到就说找不到；会后按纪要提取行动项。

以前的会前准备按“参会人发来的邮件”找材料：Budi 也在会上，他发来的报销邮件就被当成了会前材料。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class Feishu:
    def __init__(self, docs=(), contents=None):
        self.docs, self.contents, self.reads = list(docs), contents or {}, []

    async def user_api(self, user, method, path, **kwargs):
        if path == "/search/v2/doc_wiki/search":
            return {"res_units": [{"title_highlighted": d["title"], "result_meta": {"url": d["url"], "update_time": d.get("updated")}}
                                  for d in self.docs]}
        if path.startswith("/docx/v1/documents/"):
            token = path.split("/")[4]
            self.reads.append(token)
            return {"content": self.contents.get(token, "")}
        raise AssertionError(path)


@db
async def test_prep_uses_only_related_material(monkeypatch):
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.models import FollowUp, Signal, User
    from app.proactive import meetings
    from app.sources.base import add_signal

    prompts = []

    async def write(system, prompt):
        prompts.append(prompt)
        return "**为什么开这个会** 复盘 Medan 延误【1】"

    monkeypatch.setattr(meetings, "complete_text", write)
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            series = f"ev_{tag}"
            # 上一次的会：有纪要；留下一个没办完的行动项
            await add_signal(session, user, "calendar", f"{series}_1@1", kind="meeting", title="Medan 运营周会", occurred_at=now - timedelta(days=7),
                             payload={"event_id": f"{series}_1", "base_event_id": series,
                                      "minutes": {"url": "https://x.feishu.cn/docx/old", "title": "Medan 运营周会 纪要", "summary": "- Budi：查延误原因"}},
                             status="notified")
            session.add(FollowUp(user_id=user_id, key=f"meeting:{tag}:0", kind="waiting", owner="others", title="等 Budi：查延误原因",
                                 facets={"meeting": series}))
            meeting_link = "https://x.feishu.cn/docx/AGENDA1"
            await add_signal(session, user, "calendar", f"{series}_2@2", kind="meeting", title="Medan 运营周会", occurred_at=now + timedelta(minutes=10),
                             body=f"议程见 {meeting_link}",
                             payload={"event_id": f"{series}_2", "base_event_id": series, "description": f"议程见 {meeting_link}",
                                      "attendees": ["Budi"]}, status="scheduled")
            # 标题写明了这个会的邮件：相关；Budi 发来的报销邮件：不相关（只是参会人相同）
            await add_signal(session, user, "mail", f"m1-{tag}", kind="mail", title="Re: Medan 运营周会 数据", occurred_at=now - timedelta(days=1),
                             payload={"from_name": "Sari"}, status="tracked")
            await add_signal(session, user, "mail", f"m2-{tag}", kind="mail", title="报销单", occurred_at=now - timedelta(days=1),
                             payload={"from_name": "Budi"}, status="tracked")
            await session.commit()
            from sqlalchemy import select
            meeting = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.external_id == f"{series}_2@2"))).scalars().one()
            feishu = Feishu(docs=[{"title": "别的周会纪要", "url": "https://x.feishu.cn/docx/other"}],
                            contents={"AGENDA1": "1. Medan 延误复盘 2. 下周排班"})
            prep = await meetings.prepare(session, feishu, user, meeting, "zh")
            kinds = [s["kind"] for s in prep["sources"]]
            assert kinds == ["agenda", "doc", "minutes", "actions", "mail"]
            assert "报销单" not in prompts[0] and "别的周会" not in prompts[0]
            assert "等 Budi：查延误原因（未完成）" in prompts[0] and "Medan 延误复盘" in prompts[0]
            assert prep["worth_pushing"] and meeting.payload["prep"]["text"].startswith("**为什么开这个会**")

            # 一个什么材料都没有的会：直说没找到，不推送，也不让模型编
            await add_signal(session, user, "calendar", f"solo-{tag}@3", kind="meeting", title="1:1", occurred_at=now + timedelta(minutes=10),
                             payload={"event_id": f"solo-{tag}"}, status="scheduled")
            await session.commit()
            solo = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.external_id == f"solo-{tag}@3"))).scalars().one()
            empty = await meetings.prepare(session, Feishu(), user, solo, "zh")
            assert empty["sources"] == [] and not empty["worth_pushing"] and "没有找到" in empty["text"]
            assert len(prompts) == 1
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_actions_come_from_the_actual_minutes(monkeypatch):
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import FollowUp, Signal, User
    from app.proactive import meetings
    from app.sources.base import add_signal

    async def extract(system, prompt, tool):
        assert "这次的结论" in prompt
        return {"actions": [{"owner": "吴川", "task": "周五前给出 Medan 排班方案", "due": "周五", "evidence": "吴川：周五前给排班方案"},
                            {"owner": "Budi", "task": "补齐延误数据", "evidence": "Budi 补数据"}]}

    monkeypatch.setattr(meetings, "complete_structured", extract)
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            start = now - timedelta(hours=2)
            await add_signal(session, user, "calendar", f"ev_{tag}@1", kind="meeting", title="Medan 运营周会", occurred_at=start,
                             payload={"event_id": f"ev_{tag}", "base_event_id": f"ev_{tag}", "end": (start + timedelta(hours=1)).isoformat(),
                                      "organizer": "Sari"}, status="notified")
            await session.commit()
            feishu = Feishu(docs=[{"title": "Medan 运营周会 纪要（上周）", "url": "https://x.feishu.cn/docx/OLD",
                                   "updated": int((start - timedelta(days=7)).timestamp())},
                                  {"title": "Medan 运营周会 会议纪要", "url": "https://x.feishu.cn/docx/NEW",
                                   "updated": int((start + timedelta(hours=1)).timestamp())}],
                            contents={"NEW": "这次的结论：吴川周五前给排班方案；Budi 补数据"})
            assert await meetings.collect_minutes(session, feishu, user) == 1
            assert feishu.reads == ["NEW"]  # 上周的旧纪要不算
            mine = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id))).scalars().all()
            assert [(i.owner, i.title) for i in mine] == [("me", "会议《Medan 运营周会》：周五前给出 Medan 排班方案")]  # 他不是组织者：Budi 的只作背景
            meeting = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.kind == "meeting"))).scalars().one()
            assert meeting.payload["minutes"]["url"] == "https://x.feishu.cn/docx/NEW" and meeting.payload["minutes"]["actions"] == 2
            assert await meetings.collect_minutes(session, feishu, user) == 0  # 处理过的会不再读
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
