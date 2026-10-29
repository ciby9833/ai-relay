"""生成 Excel / PPT：生成后重新打开逐项核对；被改过的文件核对得出来；只有本人能下载；飞书里对话时把文件发给他。"""
import io
import os
import uuid

import pytest
from openpyxl import load_workbook

from app import outputs

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")

SHEETS = [{"name": "网点延误", "columns": ["网点", "延误单数", "占比"], "rows": [["Medan", 12, "40%"], ["Batam", 18, "60%"], ["合计", "=SUM(B2:B3)", ""]]}]
SLIDES = [
    {"title": "本周延误概况", "bullets": ["Medan 延误 12 单", "Batam 延误 18 单"], "notes": "先讲结论"},
    {"title": "明细", "table": {"columns": ["网点", "延误单数"], "rows": [["Medan", 12], ["Batam", 18]]}},
]


def test_excel_is_built_and_checked_cell_by_cell():
    data = outputs.build_xlsx(SHEETS)
    result = outputs.check_xlsx(data, SHEETS)
    assert result["ok"] and "12 个单元格" in result["detail"]
    wb = load_workbook(io.BytesIO(data))
    assert wb["网点延误"]["B4"].value == "=SUM(B2:B3)" and wb["网点延误"].freeze_panes == "A2"
    # 文件被改过（或生成出了问题）：核对得出来，指出哪一格
    wb["网点延误"]["B2"] = 21
    buffer = io.BytesIO()
    wb.save(buffer)
    bad = outputs.check_xlsx(buffer.getvalue(), SHEETS)
    assert not bad["ok"] and "B2 应为“12”，实际“21”" in bad["detail"]
    with pytest.raises(outputs.OutputError):
        outputs.build_xlsx([{"name": "x", "columns": ["a"], "rows": [[1, 2]]}])


def test_ppt_is_built_and_checked_page_by_page():
    from pptx import Presentation

    data = outputs.build_pptx(SLIDES, "延误复盘")
    result = outputs.check_pptx(data, SLIDES, "延误复盘")
    assert result["ok"] and "3 页" in result["detail"]
    prs = Presentation(io.BytesIO(data))
    prs.slides[1].shapes.title.text = "别的标题"
    buffer = io.BytesIO()
    prs.save(buffer)
    bad = outputs.check_pptx(buffer.getvalue(), SLIDES, "延误复盘")
    assert not bad["ok"] and "第 2 页标题不一致" in bad["detail"]
    assert outputs.safe_name("周报/延误:复盘", "pptx") == "周报_延误_复盘.pptx"


SECTIONS = [
    {"heading": "结论", "paragraphs": ["本周延误 30 单，Batam 占 60%。"], "bullets": ["Medan 12 单", "Batam 18 单"]},
    {"heading": "明细", "table": {"columns": ["网点", "延误单数"], "rows": [["Medan", 12], ["Batam", 18]]}},
]


def test_word_is_built_and_checked_paragraph_by_paragraph():
    from docx import Document

    data = outputs.build_docx("延误复盘", SECTIONS)
    result = outputs.check_docx(data, "延误复盘", SECTIONS)
    assert result["ok"] and "1 张表" in result["detail"]
    doc = Document(io.BytesIO(data))
    doc.tables[0].cell(1, 1).text = "21"
    buffer = io.BytesIO()
    doc.save(buffer)
    bad = outputs.check_docx(buffer.getvalue(), "延误复盘", SECTIONS)
    assert not bad["ok"] and "第 1 张表第 2 行第 2 列不一致" in bad["detail"]


@db
async def test_saving_to_drive_runs_as_a_job_and_is_read_back(monkeypatch):
    """要存进云空间的：交给后台做——生成、核对、上传、从云空间下载回来比对、在飞书里告诉他。失败会重试，最多 3 次。"""
    from sqlalchemy import delete

    from app import filejobs
    from app.agent.tools.base import ToolContext, execute
    from app.db import SessionLocal, engine
    from app.models import Conversation, GeneratedFile, User

    monkeypatch.setattr(filejobs, "kick", lambda file_id, feishu: None)  # 测试里不起后台任务，直接调 process

    class Drive:
        def __init__(self, broken=0):
            self.stored, self.broken, self.texts, self.files = {}, broken, [], []

        async def user_api(self, user, method, path, **kwargs):
            if path == "/drive/explorer/v2/root_folder/meta":
                return {"token": "root"}
            if path == "/drive/v1/files/upload_all":
                if self.broken:
                    self.broken -= 1
                    raise filejobs.FeishuError("上传超时")
                assert kwargs["data"]["parent_node"] == "fold1" and kwargs["data"]["file_name"] == "延误复盘.docx"
                self.stored["tok"] = kwargs["files"]["file"][1]
                return {"file_token": "tok"}
            if path == "/drive/v1/metas/batch_query":
                return {"metas": [{"url": "https://x.feishu.cn/file/tok"}]}
            raise AssertionError(path)

        async def download(self, url, user=None):
            return self.stored["tok"], None

        async def send_text(self, open_id, text):
            self.texts.append(text)

        async def send_file(self, *args):
            self.files.append(args)

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(me)
        await session.flush()
        user_id = me.id
        conversation = Conversation(user_id=me.id, channel="web")
        session.add(conversation)
        await session.flush()
        drive = Drive(broken=1)
        ctx = ToolContext(session=session, user=me, conversation=conversation, feishu=drive)
        try:
            text, failed = await execute(ctx, "create_word_file", {"filename": "延误复盘", "title": "延误复盘", "sections": SECTIONS,
                                                                    "save_to_drive": True, "folder_url": "https://x.feishu.cn/drive/folder/fold1"})
            assert not failed and "后台" in text and "不要说已经做好" in text
            assert ctx.cards[-1]["status"] == "queued"
            file_id = uuid.UUID(ctx.cards[-1]["file_id"])
            await session.commit()
            async with SessionLocal() as s2:
                record = await filejobs.process(s2, drive, file_id)  # 第一次上传失败：留着重试
                assert (record.status, record.attempts, record.error) == ("queued", 1, "上传超时") and record.content
            async with SessionLocal() as s3:
                record = await filejobs.process(s3, drive, file_id)
                assert record.status == "done" and record.verified["ok"]
                assert record.drive["url"] == "https://x.feishu.cn/file/tok" and record.drive["verified"]["ok"]
            assert "已存进你的飞书云空间：https://x.feishu.cn/file/tok" in drive.texts[-1]
            async with SessionLocal() as s4:
                assert await filejobs.process(s4, drive, file_id) is None  # 做完的不会再做
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_generated_files_reach_only_the_owner():
    import httpx
    from sqlalchemy import delete

    from app import deps
    from app.agent.tools.base import ToolContext, execute
    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import Conversation, User

    class Feishu:
        def __init__(self):
            self.files = []

        async def send_file(self, open_id, data, filename, file_type):
            self.files.append((open_id, filename, file_type, len(data)))
            return "om_file"

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        other = User(feishu_open_id=f"ou_o_{tag}", name="Kange", timezone="Asia/Jakarta")
        session.add_all([me, other])
        await session.flush()
        ids = [me.id, other.id]
        conversation = Conversation(user_id=me.id, channel="feishu")
        session.add(conversation)
        await session.flush()
        feishu = Feishu()
        ctx = ToolContext(session=session, user=me, conversation=conversation, feishu=feishu)
        try:
            text, failed = await execute(ctx, "create_excel_file", {"filename": "延误/明细", "sheets": SHEETS})
            assert not failed and "核对通过" in text and feishu.files == [(me.feishu_open_id, "延误_明细.xlsx", "xls", feishu.files[0][3])]
            card = ctx.cards[-1]
            assert card["kind"] == "file" and card["verified"]["ok"]
            text, failed = await execute(ctx, "create_ppt_file", {"filename": "延误复盘", "title": "延误复盘", "slides": SLIDES})
            assert not failed and "核对通过" in text and feishu.files[-1][2] == "ppt"
            await session.commit()
            users = {u.id: u for u in [await session.get(User, i) for i in ids]}
            app.dependency_overrides[deps.get_current_user] = lambda: users[ids[0]]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
                response = await client.get(f"/api/files/{card['file_id']}")
                assert response.status_code == 200 and response.headers["content-type"] == outputs.XLSX
                assert outputs.check_xlsx(response.content, SHEETS)["ok"]
                app.dependency_overrides[deps.get_current_user] = lambda: users[ids[1]]
                assert (await client.get(f"/api/files/{card['file_id']}")).status_code == 404  # 别人下载不了
        finally:
            app.dependency_overrides.pop(deps.get_current_user, None)
            await session.rollback()
            await session.execute(delete(User).where(User.id.in_(ids)))
            await session.commit()
            await engine.dispose()
