"""官方请求契约、授权边界和确认机制；不写入真实飞书资源。"""
import json
from types import SimpleNamespace

import pytest

from app.agent.tools.base import TOOLS, ToolContext, ToolError
from app.feishu.client import FeishuError
from app.sources import approval, cloud, docs


class FakeFeishu:
    def __init__(self, data=None):
        self.calls = []
        self.data = data or {}

    async def user_api(self, user, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.data


USER = SimpleNamespace(id="test", feishu_open_id="ou_me")


@pytest.mark.parametrize("name,args,method,path,body", [
    ("create_doc", {"title": "周报"}, "POST", "/docx/v1/documents", {"title": "周报"}),
    ("append_doc_text", {"document_id": "d", "block_id": "d", "text": "第一段\n第二段"}, "POST", "/docx/v1/documents/d/blocks/d/children", {"children": [{"block_type": 2, "text": {"elements": [{"text_run": {"content": t}}]}} for t in ("第一段", "第二段")], "index": -1}),
    ("replace_doc_block_text", {"document_id": "d", "block_id": "b", "text": "替换"}, "PATCH", "/docx/v1/documents/d/blocks/b", {"update_text_elements": {"elements": [{"text_run": {"content": "替换"}}]}}),
    ("create_wiki_node", {"space_id": "s", "title": "流程", "obj_type": "docx"}, "POST", "/wiki/v2/spaces/s/nodes", {"title": "流程", "obj_type": "docx", "node_type": "origin"}),
    ("update_wiki_title", {"space_id": "s", "node_token": "n", "title": "新标题"}, "POST", "/wiki/v2/spaces/s/nodes/n/update_title", {"title": "新标题"}),
    ("create_base_table", {"app_token": "a", "name": "项目", "fields": [{"field_name": "标题", "type": 1}]}, "POST", "/bitable/v1/apps/a/tables", {"table": {"name": "项目", "fields": [{"field_name": "标题", "type": 1}]}}),
    ("update_base_record", {"app_token": "a", "table_id": "t", "record_id": "r", "fields": {"进度": "完成"}}, "PUT", "/bitable/v1/apps/a/tables/t/records/r", {"fields": {"进度": "完成"}}),
    ("subscribe_doc_comments", {"file_token": "d", "file_type": "docx"}, "POST", "/drive/v1/files/d/subscriptions", {"file_type": "docx", "subscription_type": "comment_update"}),
    ("update_doc_subscription", {"file_token": "d", "subscription_id": "s", "file_type": "docx", "is_subscribe": False}, "PATCH", "/drive/v1/files/d/subscriptions/s", {"file_type": "docx", "is_subscribe": False}),
    ("write_sheet_range", {"spreadsheet_token": "s", "range": "t!A1:B1", "values": [[1, {"type": "formula", "text": "=A1*2"}]]}, "PUT", "/sheets/v2/spreadsheets/s/values", {"valueRange": {"range": "t!A1:B1", "values": [[1, {"type": "formula", "text": "=A1*2"}]]}}),
])
async def test_write_contract_and_gate(name, args, method, path, body):
    f = FakeFeishu()
    with pytest.raises(FeishuError, match="用户确认"):
        await cloud.call(f, USER, name, args)
    assert not f.calls
    await cloud.call(f, USER, name, args, allow_write=True, client_token="stable-token")
    actual_method, actual_path, kwargs = f.calls[0]
    assert (actual_method, actual_path, kwargs["json"]) == (method, path, body)
    if name in ("append_doc_text", "replace_doc_block_text", "update_base_record"):
        assert kwargs["params"]["client_token"] == "stable-token"


async def test_reads_keep_pagination_and_subscription_get_body():
    f = FakeFeishu({"files": [], "has_more": True, "next_page_token": "next"})
    result = await cloud.call(f, USER, "list_drive_files", {"page_token": "cursor"})
    assert result["next_page_token"] == "next" and result["has_more"]
    assert f.calls[0][2]["params"] == {"page_size": 50, "page_token": "cursor"}
    await cloud.call(f, USER, "get_doc_subscription", {"file_token": "d", "subscription_id": "s", "file_type": "docx"})
    assert f.calls[-1] == ("GET", "/drive/v1/files/d/subscriptions/s", {"params": {}, "json": {"file_type": "docx"}})


async def test_board_appends_without_overwriting():
    f = FakeFeishu()
    node = {"type": "text_shape", "x": 10, "y": 20, "width": 200, "height": 60, "text": {"text": "想法"}}
    await cloud.call(f, USER, "create_board_nodes", {"whiteboard_id": "b", "nodes": [node]}, allow_write=True)
    assert f.calls[-1][2]["json"] == {"nodes": [node]}


@pytest.mark.parametrize("name,args", [
    ("list_drive_files", {"folder_token": "../secret"}),
    ("create_doc", {"title": "x", "permissions": "public"}),
    ("read_sheet_range", {"spreadsheet_token": "s", "range": "t!Z5:A1"}),
    ("read_sheet_range", {"spreadsheet_token": "s", "range": "t!A1:Z1000"}),
    ("write_sheet_range", {"spreadsheet_token": "s", "range": "t!A1:B2", "values": [[1, 2]]}),
    ("write_sheet_range", {"spreadsheet_token": "s", "range": "t!A1:A1", "values": [[{"type": "formula", "text": '=IMPORTRANGE("x","t!A1")'}]]}),
    ("list_feishu_calendars", {"page_size": 10}),
    ("read_calendar_events", {"calendar_id": "cal", "start_time": "9", "end_time": "8"}),
    ("create_base_table", {"app_token": "a", "name": "n", "fields": [{"field_name": "数字", "type": 2}]}),
])
def test_reject_invalid_or_unbounded_payload(name, args):
    with pytest.raises(FeishuError):
        cloud.validate(name, args)


async def test_wiki_sheet_resolves_structure_without_claiming_full_content():
    class Wiki(FakeFeishu):
        async def user_api(self, user, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return {"node": {"obj_type": "sheet", "obj_token": "sheet1"}} if path.endswith("get_node") else {"sheets": [{"sheet_id": "tab1"}]}
    f = Wiki()
    data = await cloud.read_url(f, USER, "https://company.feishu.cn/wiki/node1")
    assert "spreadsheet_token=sheet1" in data["content"] and "read_sheet_range" in data["content"]
    assert f.calls[-1][1] == "/sheets/v3/spreadsheets/sheet1/sheets/query"
    with pytest.raises(FeishuError):
        await cloud.read_url(f, USER, "https://feishu.cn.evil.test/docx/d")
    with pytest.raises(FeishuError, match="token"):
        await cloud.read_url(FakeFeishu(), USER, "https://company.feishu.cn/wiki/node1")


async def test_doc_search_exposes_next_page():
    f = FakeFeishu({"res_units": [], "has_more": True, "page_token": "next", "total": 20})
    page = await docs.search_page(f, USER, "项目", page_token="current")
    assert page["has_more"] and page["page_token"] == "next"
    assert f.calls[0][2]["json"]["page_token"] == "current"


async def test_prepare_shows_readable_preview_without_writing():
    class Session:
        def add(self, action):
            self.action = action
            action.id = 123
        async def flush(self):
            pass
    f, session = FakeFeishu(), Session()
    ctx = ToolContext(session, USER, None, f)
    result = await TOOLS["prepare_append_doc_text"].handler(ctx, {"document_id": "doc1", "block_id": "doc1", "text": "会议纪要第一条"})
    assert "尚未修改" in result and f.calls == []
    body = session.action.payload["body"]
    assert "会议纪要第一条" in body and "{" not in body
    assert ctx.cards == [{"kind": "action", "action_id": 123}]


def test_only_understanding_and_doc_output_tools_are_exposed():
    from app.agent.tools.cloud import EXPOSED
    exposed = {name for name in TOOLS if name.removeprefix("prepare_") in cloud.OPS} - {"list_sheet_tabs", "read_sheet_range", "list_base_fields"}
    assert exposed == {n if not cloud.OPS[n].write else f"prepare_{n}" for n in EXPOSED}
    assert "prepare_fill_sheet_cells" in TOOLS and "prepare_add_base_record" in TOOLS
    assert "prepare_write_sheet_range" not in TOOLS and "read_calendar_events" not in TOOLS


def test_cloud_result_is_one_sentence():
    from app.proactive.actions import cloud_result
    text = cloud_result("新建文档《周报》", "create_doc", {"document": {"document_id": "abc", "revision_id": 1}})
    assert text.startswith("已新建文档《周报》") and "abc" in text and "revision" not in text


async def test_permission_error_does_not_become_empty_list():
    class Denied(FakeFeishu):
        async def user_api(self, *args, **kwargs):
            raise FeishuError("required privileges [drive:drive:readonly]", 99991679)
    with pytest.raises(ToolError, match="drive:drive:readonly"):
        await TOOLS["list_drive_files"].handler(ToolContext(None, USER, None, Denied()), {})


async def test_stale_overwrite_is_rejected_before_mutation():
    from app.proactive.actions import execute
    f = FakeFeishu({"valueRange": {"values": [["他人已修改"]]}})
    action = SimpleNamespace(user_id=USER.id, id=1, kind="cloud_write", status="pending", signal_id=None,
        payload={"operation": "write_sheet_range", "arguments": {"spreadsheet_token": "s", "range": "t!A1:A1", "values": [["新值"]]},
                 "before": {"valueRange": {"values": [["旧值"]]}}}, summary="修改表格")
    result = await execute(None, f, USER, action)
    assert "原内容已变化" in result and action.status == "failed"
    assert all(method == "GET" for method, _, _ in f.calls)


async def test_root_and_calendar_default_request():
    f = FakeFeishu()
    await cloud.call(f, USER, "get_drive_root", {})
    assert f.calls[-1] == ("GET", "/drive/explorer/v2/root_folder/meta", {"params": {}})
    await cloud.call(f, USER, "list_feishu_calendars", {})
    assert f.calls[-1][2]["params"] == {"page_size": 50}


async def test_approval_pages_cc_and_numeric_results():
    class Approvals:
        def __init__(self):
            self.calls = []
        async def tenant_api(self, method, path, **kwargs):
            p = kwargs["params"]
            self.calls.append(p)
            assert p["user_id"] == "ou_me" and p["user_id_type"] == "open_id"
            if p["topic"] == "17":
                return {"tasks": [{"task_id": "cc1", "process_code": "I1", "process_status": 2}]}
            if p["topic"] == "18":
                return {"tasks": [{"task_id": "cc1", "process_code": "I1", "process_status": 2}, {"task_id": "cc2", "process_code": "I2", "process_status": 3}]}
            if "page_token" not in p:
                return {"tasks": [{"process_code": "I1", "process_status": 1}], "has_more": True, "page_token": "next"}
            return {"tasks": [{"process_code": "I2", "process_status": 4}], "has_more": False}
    f = Approvals()
    assert len(await approval.query_tasks(f, USER, "initiated")) == 2
    rows = await approval.query_tasks(f, USER, "cc")
    assert len(rows) == 2 and not rows[0]["relay_cc_read"] and rows[1]["relay_cc_read"]
    assert approval.PROCESS_LABELS[str(rows[0]["process_status"])] == "已通过"
    result = json.loads(await TOOLS["query_my_approvals"].handler(ToolContext(None, USER, None, f), {"category": "initiated"}))
    assert [r["result"] for r in result["items"]] == ["审批中", "已撤回"]
    with pytest.raises(ToolError, match="不能读取"):
        await TOOLS["read_my_approval"].handler(ToolContext(None, USER, None, f), {"category": "initiated", "instance_code": "OTHER"})


async def test_incomplete_approval_pages_fail_closed():
    class Broken:
        async def tenant_api(self, *args, **kwargs):
            return {"tasks": [], "has_more": True, "page_token": "same"}
    with pytest.raises(FeishuError, match="分页响应不完整"):
        await approval.query_tasks(Broken(), USER, "pending")


def test_personal_hr_approvals_stay_out_of_briefs():
    assert approval.is_personal({"definition_name": "Formulir Pengunduran Diri"})
    assert approval.is_personal({"definition_name": "Leave Approval (Izin, Cuti, Sakit)"})
    assert approval.is_personal({"definition_name": "Alur kerja pembayaran tunjangan kepada karyawan Tiongkok"})
    assert approval.is_personal({"definition_name": "Clock-in/out Correction——补卡"})
    assert not approval.is_personal({"definition_name": "【ID】Request Pembuatan Fitur Baru Pada Sistem"})
    assert not approval.is_personal({"definition_name": "Payment Application HQ - Testing"})
