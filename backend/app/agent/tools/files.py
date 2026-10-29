"""生成文件：Excel 表格、PPT。生成后重新打开逐项核对，核对结果和下载入口一起给用户；在飞书里对话时同时把文件发给他。

生成的文件只给他本人（机器人私聊和网页下载都校验是他本人），不发给任何别人；要发给别人或存进共享云空间，另外走需要确认的操作。
"""

import logging

from app import outputs
from app.agent.tools.base import ToolContext, ToolError, tool
from app.feishu.client import FeishuError
from app.models import GeneratedFile

logger = logging.getLogger("relay.files")

CELL = {"anyOf": [{"type": "string"}, {"type": "number"}]}
SHEET = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "工作表名（最多 31 字）"},
        "columns": {"type": "array", "items": {"type": "string"}, "description": "表头"},
        "rows": {"type": "array", "items": {"type": "array", "items": CELL}, "description": "数据行；以 = 开头的字符串写成公式，如 =SUM(B2:B10)"},
    },
    "required": ["name", "columns", "rows"],
    "additionalProperties": False,
}
SLIDE = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}, "description": "要点，每条一句话"},
        "table": {"type": "object", "properties": {
            "columns": {"type": "array", "items": {"type": "string"}},
            "rows": {"type": "array", "items": {"type": "array", "items": CELL}}},
            "required": ["columns", "rows"], "additionalProperties": False},
        "notes": {"type": "string", "description": "演讲者备注"},
    },
    "required": ["title"],
    "additionalProperties": False,
}


async def _deliver(ctx: ToolContext, kind: str, filename: str, data: bytes, spec: dict, verified: dict) -> str:
    record = GeneratedFile(user_id=ctx.user.id, kind=kind, filename=filename, content=data, spec=spec, verified=verified)
    ctx.session.add(record)
    await ctx.session.flush()
    card = {"kind": "file", "file_id": str(record.id), "filename": filename, "file_kind": kind, "size": len(data), "verified": verified}
    ctx.cards.append(card)
    sent = ""
    if ctx.conversation.channel == "feishu":
        try:
            await ctx.feishu.send_file(ctx.user.feishu_open_id, data, filename, "xls" if kind == "xlsx" else "ppt")
            sent = "，已在飞书里发给他"
        except FeishuError as exc:
            logger.warning("发送生成的文件失败：%s", exc)
            sent = f"（飞书发送失败：{exc}，可以在网页下载）"
    check = "核对通过" if verified["ok"] else "⚠️ 核对不一致"
    return f"已生成《{filename}》（{len(data) // 1024 + 1} KB）{sent}。{check}：{verified['detail']}。告诉用户文件已生成、核对结果；不一致时说明哪里不对。"


@tool(
    "create_excel_file",
    "生成一个 Excel 文件（.xlsx）给用户：一个或多个工作表，每个有表头和数据行。数据必须来自已经查到的真实内容，不要编造；"
    "数字用数字类型，合计等可以写公式。生成后会重新打开逐格核对，结果会显示给用户。",
    {"filename": {"type": "string", "description": "文件名，不含扩展名"},
     "sheets": {"type": "array", "minItems": 1, "maxItems": 10, "items": SHEET}},
    ["filename", "sheets"],
)
async def create_excel_file(ctx: ToolContext, args: dict) -> str:
    try:
        data = outputs.build_xlsx(args["sheets"])
    except outputs.OutputError as exc:
        raise ToolError(str(exc)) from exc
    verified = outputs.check_xlsx(data, args["sheets"])
    return await _deliver(ctx, "xlsx", outputs.safe_name(args["filename"], "xlsx"), data, {"sheets": args["sheets"]}, verified)


@tool(
    "create_ppt_file",
    "生成一个 PPT 文件（.pptx，16:9）给用户：可选封面标题，每页一个标题加要点，或一张表格。内容必须来自已经查到的真实材料，不要编造；"
    "要点精炼，每页不超过 6 条。生成后会重新打开逐页核对，结果会显示给用户。",
    {"filename": {"type": "string", "description": "文件名，不含扩展名"},
     "title": {"type": "string", "description": "封面标题（可选）"},
     "slides": {"type": "array", "minItems": 1, "maxItems": outputs.MAX_SLIDES, "items": SLIDE}},
    ["filename", "slides"],
)
async def create_ppt_file(ctx: ToolContext, args: dict) -> str:
    try:
        data = outputs.build_pptx(args["slides"], args.get("title"))
    except outputs.OutputError as exc:
        raise ToolError(str(exc)) from exc
    verified = outputs.check_pptx(data, args["slides"], args.get("title"))
    return await _deliver(ctx, "pptx", outputs.safe_name(args["filename"], "pptx"), data,
                          {"title": args.get("title"), "slides": args["slides"]}, verified)
