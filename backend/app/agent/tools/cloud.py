"""云文档工具：每个操作都有独立工具和封闭的参数表，模型不能传任意 API 路径。

只开放两类场景：
- 理解：浏览知识库、云空间，读表格和多维表格，帮 Relay 弄懂背景、回答问题（读文档正文用 read_feishu_doc）；
- 产出：把整理好的内容写成一份新文档、追加到已有文档末尾，或按单元格填别人发来的表格，都要用户确认。
多维表格新增记录见 tools/bitable.py。其余操作（覆盖表格、改记录、建知识库节点、画板、订阅等）在 sources/cloud.py 里保留实现，需要时再加入 EXPOSED。
"""
import json

from app.agent.tools.base import ToolContext, ToolError, tool
from app.feishu.client import FeishuError
from app.models import PendingAction
from app.sources import cloud, sheets

EXPOSED = (
    "list_wiki_spaces", "list_wiki_nodes", "list_drive_files",
    "list_base_tables", "list_base_records",
    "create_doc", "append_doc_text",
)


def _files_text(result: dict) -> str:
    files = result.get("files") or []
    if not files:
        return "这个文件夹是空的"
    lines = [f"- 《{f.get('name')}》（{f.get('type')}）{f.get('url') or ''} token={f.get('token')}" for f in files]
    if result.get("has_more") and result.get("next_page_token"):
        lines.append(f"（还有更多，继续传 page_token=\"{result['next_page_token']}\"）")
    return "\n".join(lines)


def preview(name: str, args: dict, before: dict | None) -> str:
    """给用户看的待确认内容：说清楚要写到哪、写什么，不展示原始参数。"""
    if name == "create_doc":
        return f"新建一份文档《{args['title']}》" + ("，放在指定文件夹" if args.get("folder_token") else "，放在你的云空间根目录")
    if name == "append_doc_text":
        return f"在文档 {args['document_id']} 末尾追加以下内容：\n\n{args['text']}"
    lines = [f"{key}: {value}" for key, value in args.items()]
    if before is not None:
        lines.append("修改前：" + json.dumps(before, ensure_ascii=False)[:2000])
    return "\n".join(lines)


def _register(name, spec):
    async def handler(ctx: ToolContext, args: dict) -> str:
        try:
            cloud.validate(name, args)
            if not spec.write:
                if name == "list_drive_files":
                    args = {"page_size": 20, **args}
                result = await cloud.call(ctx.feishu, ctx.user, name, args)
                if name == "list_drive_files":
                    return _files_text(result)
                text = json.dumps(result, ensure_ascii=False)
                if len(text) > 120000:
                    raise ToolError("响应过大，不能完整展示；请缩小范围或 page_size，不要把此结果视为完整内容")
                return text
            # 覆盖类操作准备前读取原值，让用户看到要修改的对象与原内容。
            before = await cloud.before_write(ctx.feishu, ctx.user, name, args)
            body = preview(name, args, before)
            if len(body.encode("utf-8")) > 24000:
                raise ToolError("待确认内容过长，请缩小修改范围")
            summary = f"新建文档《{args['title']}》" if name == "create_doc" else "追加内容到飞书文档" if name == "append_doc_text" else spec.label
            action = PendingAction(user_id=ctx.user.id, kind="cloud_write", summary=summary,
                payload={"operation": name, "arguments": args, "before": before, "body": body},
                mission_id=getattr(ctx.mission, "id", None))
            ctx.session.add(action)
            await ctx.session.flush()
            ctx.cards.append({"kind": "action", "action_id": action.id})
            return f"已准备操作 #{action.id}：{summary}。待用户确认后执行，当前尚未修改飞书资源。"
        except FeishuError as exc:
            raise ToolError(str(exc)) from exc
    tool("prepare_" + name if spec.write else name,
         ("准备操作，展示内容并等待用户确认：" if spec.write else "以本人权限读取：") + spec.label,
         spec.properties, spec.required)(handler)


for _name in EXPOSED:
    _register(_name, cloud.OPS[_name])


SHEET_TARGET = {
    "spreadsheet": {"type": "string", "description": "电子表格链接（/sheets/…）或 spreadsheet_token"},
    "sheet_id": {"type": "string", "description": "工作表 ID；链接里带 ?sheet= 时可省略"},
}


@tool(
    "list_sheet_tabs",
    "列出电子表格的工作表（名称、sheet_id、行列数），再用 read_sheet_range 读数据。",
    {"spreadsheet": SHEET_TARGET["spreadsheet"]},
    ["spreadsheet"],
)
async def list_sheet_tabs(ctx: ToolContext, args: dict) -> str:
    try:
        token, _ = sheets.parse_target(args["spreadsheet"])
        tabs = await sheets.sheets_of(ctx.feishu, ctx.user, token)
    except sheets.SheetError as exc:
        raise ToolError(str(exc)) from exc
    except FeishuError as exc:
        raise ToolError(sheets.explain(exc)) from exc
    return f"spreadsheet_token {token}\n" + "\n".join(
        f"- 「{s.get('title')}」sheet_id={s['sheet_id']}，{(s.get('grid_properties') or {}).get('row_count')} 行 × "
        f"{(s.get('grid_properties') or {}).get('column_count')} 列{'（隐藏）' if s.get('hidden') else ''}"
        for s in tabs
    )


@tool(
    "read_sheet_range",
    "读取电子表格一个范围的值（纯文本），按 `R行号 | 列字母: 值` 返回，空格子省略，可以直接定位单元格（如 S49）。"
    "一次最多 5000 格；大表请先读表头行确定列，再按需读。",
    {**SHEET_TARGET, "range": {"type": "string", "description": "例如 A1:X60"}},
    ["spreadsheet", "range"],
)
async def read_sheet_range(ctx: ToolContext, args: dict) -> str:
    try:
        token, sheet_id = sheets.parse_target(args["spreadsheet"], args.get("sheet_id"))
        sheet = await sheets.sheet_info(ctx.feishu, ctx.user, token, sheet_id)
        text = await sheets.read_range(ctx.feishu, ctx.user, token, sheet["sheet_id"], args["range"])
    except sheets.SheetError as exc:
        raise ToolError(str(exc)) from exc
    except FeishuError as exc:
        raise ToolError(sheets.explain(exc)) from exc
    spans = [f"{sheets.cell_name(a[0], a[1])}:{sheets.cell_name(a[2], a[3])}" for a in sheets.merges(sheet)]
    merged = f"\n合并单元格：{'、'.join(spans[:40])}{' 等' if len(spans) > 40 else ''}" if spans else ""
    return f"工作表「{sheet.get('title')}」（sheet_id {sheet['sheet_id']}）{args['range'].upper()}{merged}\n{text}"


@tool(
    "prepare_fill_sheet_cells",
    "准备按单元格填写电子表格（例如别人发来让你填的反馈表），展示每格的原值和新值，用户确认后才写入。"
    "会先检查用户对表格有没有编辑权限；合并单元格会改写到左上角。只填用户要求的格子，不改其他内容。",
    {
        **SHEET_TARGET,
        "cells": {
            "type": "array", "minItems": 1, "maxItems": 200,
            "items": {
                "type": "object",
                "properties": {"cell": {"type": "string", "description": "例如 S49"},
                               "value": {"type": ["string", "number"]}},
                "required": ["cell", "value"], "additionalProperties": False,
            },
        },
    },
    ["spreadsheet", "cells"],
)
async def prepare_fill_sheet_cells(ctx: ToolContext, args: dict) -> str:
    try:
        token, sheet_id = sheets.parse_target(args["spreadsheet"], args.get("sheet_id"))
        payload = await sheets.prepare_cells(ctx.feishu, ctx.user, token, sheet_id, args["cells"])
    except sheets.SheetError as exc:
        raise ToolError(str(exc)) from exc
    except FeishuError as exc:
        raise ToolError(sheets.explain(exc)) from exc
    body = sheets.preview(payload)
    summary = f"填写表格「{payload.get('sheet_title') or payload['sheet_id']}」{len(payload['cells'])} 个单元格"
    action = PendingAction(user_id=ctx.user.id, kind="cloud_write", summary=summary,
                           payload={**payload, "arguments": args, "before": None, "body": body},
                           mission_id=getattr(ctx.mission, "id", None))
    ctx.session.add(action)
    await ctx.session.flush()
    ctx.cards.append({"kind": "action", "action_id": action.id})
    overwrite = [c["cell"] for c in payload["cells"] if c["before"].strip()]
    extra = f"其中 {'、'.join(overwrite)} 已有内容，会被覆盖，请在回复里提醒用户。" if overwrite else ""
    notes = ("；".join(payload["notes"]) + "。") if payload["notes"] else ""
    return f"已准备操作 #{action.id}：{summary}。待用户确认后写入，当前尚未修改表格。{extra}{notes}"
