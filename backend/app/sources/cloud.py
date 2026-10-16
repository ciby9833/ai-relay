"""飞书云文档常用 API 白名单。所有资源以用户身份访问，写入只能由 PendingAction 执行。

接口依据与边界见 docs/FEISHU_API.md。分页保留官方 page_token/has_more，不把第一页当全集。
"""
from dataclasses import dataclass
from urllib.parse import quote, urlparse
import json
import re

import jsonschema

from app.feishu.client import FeishuClient, FeishuError
from app.models import User

ID = {"type": "string", "pattern": "^[A-Za-z0-9_-]+$", "maxLength": 256}
TEXT = {"type": "string", "minLength": 1, "maxLength": 2000}
PAGE = {"page_token": {"type": "string", "maxLength": 4096}, "page_size": {"type": "integer", "minimum": 1, "maximum": 50}}
FILE_TYPE = {"type": "string", "enum": ["doc", "docx", "sheet", "bitable", "file"]}


@dataclass
class Operation:
    label: str
    method: str
    path: str
    properties: dict
    required: list[str]
    query: tuple = ()
    body: tuple = ()
    write: bool = False

    @property
    def schema(self):
        return {"type": "object", "properties": self.properties, "required": self.required, "additionalProperties": False}


OPS = {}


def op(name, label, method, path, props, required=(), query=(), body=(), write=False):
    OPS[name] = Operation(label, method, path, props, list(required), tuple(query), tuple(body), write)


op("list_drive_files", "浏览云空间文件夹；返回 files 和下一页 next_page_token", "GET", "/drive/v1/files", {"folder_token": ID, **PAGE}, query=("folder_token", "page_size", "page_token"))
op("get_drive_root", "获取本人云空间根文件夹 token，用于在根目录创建文件夹", "GET", "/drive/explorer/v2/root_folder/meta", {})
op("list_wiki_spaces", "列出本人可访问的知识空间", "GET", "/wiki/v2/spaces", PAGE, query=PAGE)
op("list_wiki_nodes", "列出知识库子节点；不传 parent_node_token 时列出根节点", "GET", "/wiki/v2/spaces/{space_id}/nodes", {"space_id": ID, "parent_node_token": ID, **PAGE}, ["space_id"], query=("parent_node_token", *PAGE))
op("list_doc_blocks", "列出文档内容块，包含图片、画板 token；page_token 继续读取", "GET", "/docx/v1/documents/{document_id}/blocks/{block_id}/children", {"document_id": ID, "block_id": ID, **PAGE}, ["document_id", "block_id"], query=PAGE)
op("list_sheet_tabs", "列出电子表格工作表，先取 sheet_id 再读取范围", "GET", "/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query", {"spreadsheet_token": ID}, ["spreadsheet_token"])
RANGE = {"type": "string", "pattern": "^[A-Za-z0-9_-]+![A-Z]+[1-9][0-9]*:[A-Z]+[1-9][0-9]*$", "maxLength": 100}
op("read_sheet_range", "读取电子表格指定单元格范围，range 形如 sheet_id!A1:D50，单次最多 5000 格", "GET", "/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range}", {"spreadsheet_token": ID, "range": RANGE}, ["spreadsheet_token", "range"])
op("list_base_tables", "列出多维表格的数据表", "GET", "/bitable/v1/apps/{app_token}/tables", {"app_token": ID, **PAGE}, ["app_token"], query=PAGE)
op("list_base_fields", "列出字段及类型；新增/修改记录前先查看字段结构", "GET", "/bitable/v1/apps/{app_token}/tables/{table_id}/fields", {"app_token": ID, "table_id": ID, **PAGE}, ["app_token", "table_id"], query=PAGE)
op("list_base_records", "读取多维表格记录，可指定 view_id；page_token 继续", "GET", "/bitable/v1/apps/{app_token}/tables/{table_id}/records", {"app_token": ID, "table_id": ID, "view_id": ID, **PAGE}, ["app_token", "table_id"], query=("view_id", *PAGE))
op("read_board_nodes", "读取画板节点；whiteboard_id 来自文档 block_type=43 的 board.token", "GET", "/board/v1/whiteboards/{whiteboard_id}/nodes", {"whiteboard_id": ID}, ["whiteboard_id"])
SUB_TYPE = {"type": "string", "enum": ["doc", "docx", "wiki"]}
op("get_doc_subscription", "读取云文档助手评论订阅状态；subscription_id 来自创建订阅返回值", "GET", "/drive/v1/files/{file_token}/subscriptions/{subscription_id}", {"file_token": ID, "subscription_id": ID, "file_type": SUB_TYPE}, ["file_token", "subscription_id", "file_type"], body=("file_type",))
CAL_ID = {"type": "string", "minLength": 1, "maxLength": 256, "pattern": "^[A-Za-z0-9_.@-]+$"}
CAL_PAGE = {**PAGE, "page_size": {"type": "integer", "minimum": 50, "maximum": 100}}
op("list_feishu_calendars", "列出本人可访问的日历，返回 calendar_id 与访问角色；每页至少 50 条", "GET", "/calendar/v4/calendars", CAL_PAGE, query=CAL_PAGE)
op("read_calendar_events", "读取指定日历时间窗口内日程（含重复日程实例）；时间为 Unix 秒字符串，窗口最多 31 天", "GET", "/calendar/v4/calendars/{calendar_id}/events/instance_view", {"calendar_id": CAL_ID, "start_time": {"type": "string", "pattern": "^[0-9]{1,12}$"}, "end_time": {"type": "string", "pattern": "^[0-9]{1,12}$"}}, ["calendar_id", "start_time", "end_time"], query=("start_time", "end_time"))

op("create_drive_folder", "创建云空间文件夹", "POST", "/drive/v1/files/create_folder", {"name": TEXT, "folder_token": ID}, ["name", "folder_token"], body=("name", "folder_token"), write=True)
op("create_feishu_calendar", "创建共享日历（默认私密）", "POST", "/calendar/v4/calendars", {"summary": TEXT, "description": TEXT}, ["summary"], body=("summary", "description"), write=True)
op("copy_drive_file", "复制文件到指定文件夹", "POST", "/drive/v1/files/{file_token}/copy", {"file_token": ID, "name": TEXT, "folder_token": ID, "type": FILE_TYPE}, ["file_token", "name", "folder_token", "type"], body=("name", "folder_token", "type"), write=True)
op("create_doc", "创建空白新版文档；创建成功后可另行确认追加正文", "POST", "/docx/v1/documents", {"title": TEXT, "folder_token": ID}, ["title"], body=("title", "folder_token"), write=True)
LONG_TEXT = {"type": "string", "minLength": 1, "maxLength": 20000}
op("append_doc_text", "在指定文档内容块末尾追加纯文本段落（不解析 Markdown），block_id 通常等于 document_id", "POST", "/docx/v1/documents/{document_id}/blocks/{block_id}/children", {"document_id": ID, "block_id": ID, "text": LONG_TEXT}, ["document_id", "block_id", "text"], write=True)
op("replace_doc_block_text", "替换指定文本块的全部文字，原文字格式会被替换；请先读取原块", "PATCH", "/docx/v1/documents/{document_id}/blocks/{block_id}", {"document_id": ID, "block_id": ID, "text": LONG_TEXT}, ["document_id", "block_id", "text"], write=True)
op("create_wiki_node", "在指定知识空间创建节点", "POST", "/wiki/v2/spaces/{space_id}/nodes", {"space_id": ID, "parent_node_token": ID, "title": TEXT, "obj_type": {"type": "string", "enum": ["docx", "sheet", "bitable"]}}, ["space_id", "title", "obj_type"], body=("parent_node_token", "title", "obj_type"), write=True)
op("update_wiki_title", "修改知识库节点标题", "POST", "/wiki/v2/spaces/{space_id}/nodes/{node_token}/update_title", {"space_id": ID, "node_token": ID, "title": TEXT}, ["space_id", "node_token", "title"], body=("title",), write=True)
op("create_sheet", "创建电子表格", "POST", "/sheets/v3/spreadsheets", {"title": TEXT, "folder_token": ID}, ["title"], body=("title", "folder_token"), write=True)
CELL = {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "object", "properties": {"type": {"type": "string", "enum": ["formula"]}, "text": {"type": "string", "pattern": "^=", "maxLength": 2000}}, "required": ["type", "text"], "additionalProperties": False}]}
VALUES = {"type": "array", "minItems": 1, "maxItems": 1000, "items": {"type": "array", "minItems": 1, "maxItems": 100, "items": CELL}}
op("write_sheet_range", '覆盖电子表格指定范围；values 为矩形二维数组。公式必须使用 {"type":"formula","text":"=A1"}，不支持 IMPORTRANGE；必须先读取原范围', "PUT", "/sheets/v2/spreadsheets/{spreadsheet_token}/values", {"spreadsheet_token": ID, "range": RANGE, "values": VALUES}, ["spreadsheet_token", "range", "values"], write=True)
op("create_base", "创建多维表格应用", "POST", "/bitable/v1/apps", {"name": TEXT, "folder_token": ID}, ["name"], body=("name", "folder_token"), write=True)
TABLE_FIELD = {"type": "object", "properties": {"field_name": TEXT, "type": {"type": "integer", "enum": [1, 2]}}, "required": ["field_name", "type"], "additionalProperties": False}
op("create_base_table", "在多维表格创建数据表；可指定文本(type=1)和数字(type=2)字段，首字段须为文本", "POST", "/bitable/v1/apps/{app_token}/tables", {"app_token": ID, "name": TEXT, "fields": {"type": "array", "minItems": 1, "maxItems": 30, "items": TABLE_FIELD}}, ["app_token", "name"], write=True)
FIELDS = {"type": "object", "minProperties": 1, "maxProperties": 100, "description": "字段名到值的映射；须按 list_base_fields 返回的字段类型填写"}
op("create_base_record", "新增多维表格一条记录", "POST", "/bitable/v1/apps/{app_token}/tables/{table_id}/records", {"app_token": ID, "table_id": ID, "fields": FIELDS}, ["app_token", "table_id", "fields"], body=("fields",), write=True)
op("update_base_record", "更新多维表格一条记录的指定字段；必须先读取原记录", "PUT", "/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}", {"app_token": ID, "table_id": ID, "record_id": ID, "fields": FIELDS}, ["app_token", "table_id", "record_id", "fields"], body=("fields",), write=True)
BOARD_TEXT = {"type": "object", "properties": {"type": {"type": "string", "enum": ["text_shape"]}, "x": {"type": "number"}, "y": {"type": "number"}, "width": {"type": "number", "exclusiveMinimum": 0}, "height": {"type": "number", "exclusiveMinimum": 0}, "text": {"type": "object", "properties": {"text": LONG_TEXT}, "required": ["text"], "additionalProperties": False}}, "required": ["type", "x", "y", "width", "height", "text"], "additionalProperties": False}
op("create_board_nodes", "在现有画板追加文字节点（type=text_shape）；禁止覆盖已有画板", "POST", "/board/v1/whiteboards/{whiteboard_id}/nodes", {"whiteboard_id": ID, "nodes": {"type": "array", "minItems": 1, "maxItems": 20, "items": BOARD_TEXT}}, ["whiteboard_id", "nodes"], body=("nodes",), write=True)
op("subscribe_doc_comments", "创建云文档助手评论更新订阅", "POST", "/drive/v1/files/{file_token}/subscriptions", {"file_token": ID, "file_type": SUB_TYPE}, ["file_token", "file_type"], body=("file_type",), write=True)
op("update_doc_subscription", "开启或关闭已有云文档助手评论订阅", "PATCH", "/drive/v1/files/{file_token}/subscriptions/{subscription_id}", {"file_token": ID, "subscription_id": ID, "file_type": SUB_TYPE, "is_subscribe": {"type": "boolean"}}, ["file_token", "subscription_id", "file_type", "is_subscribe"], body=("file_type", "is_subscribe"), write=True)


def validate(name: str, args: dict) -> Operation:
    if name not in OPS:
        raise FeishuError("不支持的云文档操作")
    spec = OPS[name]
    try:
        jsonschema.validate(args, spec.schema)
    except jsonschema.ValidationError as exc:
        raise FeishuError(f"参数不合法：{exc.message}") from None
    if len(json.dumps(args, ensure_ascii=False)) > 60000:
        raise FeishuError("操作内容过长，请拆分")
    if name == "read_calendar_events" and not 0 < int(args["end_time"]) - int(args["start_time"]) <= 31 * 86400:
        raise FeishuError("日程查询窗口需大于 0 且不超过 31 天")
    if "range" in args:
        start_col, start_row, end_col, end_row = re.fullmatch(r"[^!]+!([A-Z]+)(\d+):([A-Z]+)(\d+)", args["range"]).groups()
        def col(s):
            result = 0
            for char in s:
                result = result * 26 + ord(char) - 64
            return result
        rows, cols = int(end_row) - int(start_row) + 1, col(end_col) - col(start_col) + 1
        if min(rows, cols) < 1 or rows * cols > 5000:
            raise FeishuError("范围必须正向且不超过 5000 个单元格")
        if "values" in args and (len(args["values"]) != rows or any(len(row) != cols for row in args["values"])):
            raise FeishuError("values 的行列数必须与覆盖范围完全一致")
    if name == "append_doc_text" and len(args["text"].splitlines()) > 50:
        raise FeishuError("一次最多追加 50 段，请拆分")
    if name == "create_base_table" and args.get("fields"):
        fields = args["fields"]
        if fields[0]["type"] != 1 or len({f["field_name"] for f in fields}) != len(fields):
            raise FeishuError("首字段须为文本，字段名不能重复")
    if name == "write_sheet_range" and any(
        isinstance(cell, dict) and re.search(r"\bIMPORTRANGE\s*\(", cell["text"], re.I)
        for row in args["values"] for cell in row
    ):
        raise FeishuError("飞书此接口不支持写入 IMPORTRANGE 公式")
    return spec


async def call(feishu: FeishuClient, user: User, name: str, args: dict, *, allow_write=False, client_token=None) -> dict:
    spec = validate(name, args)
    if spec.write and not allow_write:
        raise FeishuError("写操作必须先准备并由用户确认")
    path = spec.path.format(**{k: quote(str(v), safe="") for k, v in args.items()})
    params = {k: args[k] for k in spec.query if k in args}
    body = {k: args[k] for k in spec.body if k in args}
    if "page_size" in spec.query:
        params.setdefault("page_size", 50)
    if name in ("append_doc_text", "replace_doc_block_text"):
        elements = lambda text: [{"text_run": {"content": text or " "}}]
        if name == "append_doc_text":
            body = {"children": [{"block_type": 2, "text": {"elements": elements(line)}} for line in args["text"].splitlines()], "index": -1}
        else:
            body = {"update_text_elements": {"elements": elements(args["text"])}}
    if name == "write_sheet_range":
        body = {"valueRange": {"range": args["range"], "values": args["values"]}}
    if name == "create_base_table":
        body = {"table": {k: args[k] for k in ("name", "fields") if k in args}}
    if name == "create_wiki_node":
        body["node_type"] = "origin"
    if name == "create_feishu_calendar":
        body["permissions"] = "private"
    if name == "subscribe_doc_comments":
        body["subscription_type"] = "comment_update"
    if client_token and name in ("append_doc_text", "replace_doc_block_text", "create_base_record", "update_base_record", "create_board_nodes"):
        params["client_token"] = client_token
    kwargs = {"params": params}
    if body:
        kwargs["json"] = body
    return await feishu.user_api(user, spec.method, path, **kwargs)


async def before_write(feishu: FeishuClient, user: User, name: str, args: dict) -> dict | None:
    """覆盖操作的预览快照。确认时再次检查，避免覆盖确认期间他人已修改的内容。"""
    validate(name, args)
    if name == "write_sheet_range":
        data = await call(feishu, user, "read_sheet_range", {k: args[k] for k in ("spreadsheet_token", "range")})
        # revision 会因工作簿其它范围的编辑变化；只比较目标值。
        return {"valueRange": data.get("valueRange")}
    if name == "replace_doc_block_text":
        data = await feishu.user_api(user, "GET", f"/docx/v1/documents/{args['document_id']}/blocks/{args['block_id']}")
        return {"block": data.get("block")}
    if name == "update_base_record":
        data = await feishu.user_api(user, "GET", f"/bitable/v1/apps/{args['app_token']}/tables/{args['table_id']}/records/{args['record_id']}")
        return {"record": data.get("record")}
    if name == "update_wiki_title":
        data = await feishu.user_api(user, "GET", "/wiki/v2/spaces/get_node", params={"token": args["node_token"]})
        return {"node": data.get("node")}
    return None


async def read_drive_file(feishu: FeishuClient, user: User, token: str, host: str = "") -> dict:
    """云空间里上传的原始文件（Excel、Word、PDF 原件）：下载后解析成文字。"""
    from app.sources import files

    key = ("drive", user.id, token)
    if (cached := files.cache.get(key)) is not None:
        return cached
    metas = (await feishu.user_api(user, "POST", "/drive/v1/metas/batch_query",
                                   json={"request_docs": [{"doc_token": token, "doc_type": "file"}]})).get("metas") or []
    title = (metas[0].get("title") if metas else None) or token
    if files.kind_of(title) is None:
        raise FeishuError(f"暂不支持读取这种文件：{title}（支持 xlsx、docx、pdf、csv、txt）")
    try:
        data, content_type = await feishu.download(f"/drive/v1/files/{quote(token, safe='')}/download", user=user)
    except FeishuError as exc:
        if ".sg." in host and exc.code == 404:
            raise FeishuError(
                f"《{title}》存放在飞书新加坡数据区（{host}），开放接口跨区域取不到原件。"
                "可以改读邮件里的同名附件，或请用户在飞书里把它另存为在线表格/文档后发链接"
            ) from exc
        raise
    try:
        result = {"title": title, "content": files.to_text(data, title, content_type)}
    except files.FileError as exc:
        raise FeishuError(str(exc)) from exc
    files.cache.put(key, result)
    return result


async def read_url(feishu: FeishuClient, user: User, url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not any(parsed.hostname.endswith('.' + h) or parsed.hostname == h for h in ('feishu.cn', 'larksuite.com', 'larkoffice.com')):
        raise FeishuError("请提供飞书官方域名的 HTTPS 文档链接")
    match = re.fullmatch(r"/(docx|wiki|sheets|base|board|file)/([A-Za-z0-9_-]+)/?", parsed.path)
    if not match:
        raise FeishuError("暂支持 docx/wiki/sheets/base/board/file 链接；旧版 doc 请转为新版文档")
    kind, token = match.groups()
    if kind == "file":
        return await read_drive_file(feishu, user, token, parsed.hostname)
    if kind == "wiki":
        node = (await feishu.user_api(user, "GET", "/wiki/v2/spaces/get_node", params={"token": token})).get("node") or {}
        kind, token = node.get("obj_type"), node.get("obj_token")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise FeishuError("知识库没有返回可读取的资源 token，请核对链接和访问权限")
    if kind == "docx":
        return await feishu.user_api(user, "GET", f"/docx/v1/documents/{quote(token, safe='')}/raw_content")
    if kind in ("sheet", "sheets"):
        from app.sources import sheets

        tabs = await sheets.sheets_of(feishu, user, token)
        lines = [f"电子表格 spreadsheet_token={token}，工作表："] + [
            f"- 「{s.get('title')}」sheet_id={s['sheet_id']}，{(s.get('grid_properties') or {}).get('row_count')} 行 × "
            f"{(s.get('grid_properties') or {}).get('column_count')} 列{'（隐藏）' if s.get('hidden') else ''}" for s in tabs
        ]
        lines.append("这里只有结构。用 read_sheet_range 读数据：先读前两行看表头和列，再按需读。")
        return {"content": "\n".join(lines)}
    target = {"sheet": ("list_sheet_tabs", "spreadsheet_token"), "sheets": ("list_sheet_tabs", "spreadsheet_token"), "base": ("list_base_tables", "app_token"), "bitable": ("list_base_tables", "app_token"), "board": ("read_board_nodes", "whiteboard_id")}.get(kind)
    if not target:
        raise FeishuError(f"尚不支持的资源类型：{kind}")
    name, key = target
    return {"resource_type": kind, key: token, "data": await call(feishu, user, name, {key: token}),
            "next_step": "表格需继续调用 read_sheet_range；多维表格需继续调用 list_base_records。当前仅返回结构，不代表已读取全部内容。"}
