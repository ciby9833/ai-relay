"""会议：会前准备只用确实相关的材料，找不到就说找不到；会后按纪要提取行动项。

以前的会前准备按“参会人发来的邮件”找材料：Budi 也在会上，他发来的报销邮件就被当成了会前材料。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


def _xlsx() -> bytes:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["网点", "延误单数"])
    wb.active.append(["Medan", 12])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class Feishu:
    def __init__(self, docs=(), contents=None):
        self.docs, self.contents, self.reads = list(docs), contents or {}, []

    async def download(self, url, user=None, max_bytes=None):
        from app.feishu.client import FeishuError

        if url.endswith("/secret"):
            raise FeishuError("no permission to access this attachment")
        return _xlsx(), None

    async def user_api(self, user, method, path, **kwargs):
        if path.endswith("/attachments/download_url"):
            name = "secret" if kwargs["params"]["attachment_ids"] == "a2" else "ok"
            return {"download_urls": [{"attachment_id": kwargs["params"]["attachment_ids"], "download_url": f"https://x/{name}"}]}
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
                             payload={"from_name": "Sari", "attachments": [{"id": "a1", "filename": "延误明细.xlsx"},
                                                                         {"id": "a2", "filename": "内部名单.xlsx"}]}, status="tracked")
            # 私聊里他答应的事，提到了这个会：会前一起看，不用去待处理里另找
            session.add(FollowUp(user_id=user_id, key=f"chat:p-{tag}", kind="request", owner="me", title="Budi 让你：周会前准备 Medan 运营周会 的数据",
                                 next_step="完成后在私聊回复对方", facets={"private": True}))
            await add_signal(session, user, "mail", f"m2-{tag}", kind="mail", title="报销单", occurred_at=now - timedelta(days=1),
                             payload={"from_name": "Budi"}, status="tracked")
            await session.commit()
            from sqlalchemy import select
            meeting = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.external_id == f"{series}_2@2"))).scalars().one()
            feishu = Feishu(docs=[{"title": "别的周会纪要", "url": "https://x.feishu.cn/docx/other"}],
                            contents={"AGENDA1": "1. Medan 延误复盘 2. 下周排班"})
            prep = await meetings.prepare(session, feishu, user, meeting, "zh")
            kinds = [s["kind"] for s in prep["sources"]]
            assert kinds == ["agenda", "doc", "minutes", "actions", "attachment", "attachment", "mail", "items"]
            # 附件真的读出来用于会前准备（有来源）；没权限的写明没用到，不当作“没有材料”
            assert "附件《延误明细.xlsx》" in prompts[0] and "A: Medan | B: 12" in prompts[0]
            access = {s["title"]: s["access"] for s in prep["sources"] if s["kind"] == "attachment"}
            assert access == {"附件《延误明细.xlsx》": "ok", "附件《内部名单.xlsx》": "denied"}
            assert "没有权限读取" in prompts[0]
            assert "Budi 让你：周会前准备 Medan 运营周会 的数据" in prompts[0]
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


@db
async def test_one_meeting_with_two_calendar_entries_gives_one_item(monkeypatch):
    """生产复盘：日历里“需求优先统一”和“需求优先统一 (Nias)”是同一个会的两条记录，同一份纪要被提取了两次，一件事变成两件。"""
    from sqlalchemy import delete, select

    from app.api.workspace import list_meetings
    from app.db import SessionLocal, engine
    from app.models import FollowUp, Signal, User
    from app.proactive import casefile, items, meetings
    from app.sources.base import add_signal

    calls = []

    async def extract(system, prompt, tool):
        calls.append(prompt)
        return {"actions": [{"owner": "吴川", "task": "将所有人手中的需求统一汇总，整理完成后安排排期，推动后续执行", "evidence": "需求汇总整理 @吴川"}]}

    monkeypatch.setattr(meetings, "complete_structured", extract)
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            start = datetime.now(UTC) - timedelta(hours=3)
            for n, title in enumerate(["需求优先统一", "需求优先统一 (Nias)"]):
                await add_signal(session, user, "calendar", f"ev{n}_{tag}@1", kind="meeting", title=title, occurred_at=start,
                                 payload={"event_id": f"ev{n}_{tag}", "end": (start + timedelta(hours=1)).isoformat(), "organizer": "Felix Alvin Juandra"},
                                 status="notified")
            # 以前已经重复建出来的两件（内容只差一个“并”字）
            url = "https://x.feishu.cn/docx/MIN"
            for n, task in enumerate(["将所有人手中的需求统一汇总，整理完成后安排排期，推动后续执行",
                                      "将所有人手中的需求统一汇总，整理完成后安排排期并推动后续执行"]):
                session.add(FollowUp(user_id=user_id, key=f"meeting:old{n}_{tag}:0", kind="request", owner="me",
                                     title=f"会议《需求优先统一{' (Nias)' if n else ''}》：{task}", url=url,
                                     recommendation="来自会议纪要《智能纪要：需求优先统一 (Nias) 2026年10月28日》", facets={}))
            await session.commit()
            feishu = Feishu(docs=[{"title": "智能纪要：需求优先统一 (Nias) 2026年10月28日", "url": url,
                                   "updated": int(datetime.now(UTC).timestamp())}], contents={"MIN": "需求汇总整理 @吴川"})
            await meetings.collect_minutes(session, feishu, user)
            await session.commit()
            open_items = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id, FollowUp.status == "open"))).scalars().all()
            assert len(open_items) == 1 and len(calls) == 1  # 纪要只读一次；旧的重复合并掉；新提取的和留下的那件是同一件
            merged = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id, FollowUp.status == "dismissed"))).scalars().all()
            assert [m.resolution for m in merged] == ["和另一件重复（同一份纪要）"]
            rows = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.kind == "meeting"))).scalars().all()
            assert all((r.payload or {}).get("minutes") for r in rows)

            # 会议列表里只显示一条
            listed = await list_meetings(session, user)
            assert len(listed["recent"]) == 1

            # 打开这件事：来源纪要在相关材料里，能读原文；同一个会只列一次
            item = open_items[0]
            refs = await casefile.build(session, user, item, None)
            assert refs[0].ref == f"doc:{url}" and refs[0].title == "智能纪要：需求优先统一 (Nias) 2026年10月28日"
            assert sum(1 for r in refs if r.kind == "meeting") == 1
            opened = await casefile.open_ref(session, feishu, user, item, f"doc:{url}")
            assert "需求汇总整理" in opened["content"]
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
