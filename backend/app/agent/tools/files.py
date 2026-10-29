"""生成文件：Excel 表格、PPT、Word。生成后重新打开逐项核对，核对结果和下载入口一起给用户；在飞书里对话时同时把文件发给他。

生成的文件只给他本人（机器人私聊和网页下载都校验是他本人），不发给任何别人；要发给别人或存进共享云空间，另外走需要确认的操作。
"""

import logging
import re
import uuid

from app import filejobs, outputs
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


SECTION = {
    "type": "object",
    "properties": {
        "heading": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "table": SLIDE["properties"]["table"],
    },
    "additionalProperties": False,
}
SOURCES = {"sources": {"type": "array", "items": {"type": "string"}, "maxItems": 20,
                       "description": "数据和结论来自哪里（哪封邮件、哪张表、哪个群、哪份纪要，带时间），会写在文件卡片上给他核实"}}
DRIVE = {
    "save_to_drive": {"type": "boolean", "description": "他明确要求存进飞书云空间时为 true（存进他本人的“我的空间”，或 folder_url 指定的文件夹）"},
    "folder_url": {"type": "string", "description": "要存进的飞书文件夹链接（可选）"},
}
FOLDER = re.compile(r"/(?:drive/)?folder/([A-Za-z0-9_-]+)")


def _folder(args: dict) -> dict | None:
    if not args.get("save_to_drive"):
        return None
    match = FOLDER.search(args.get("folder_url") or "")
    if args.get("folder_url") and not match:
        raise ToolError("folder_url 不是飞书文件夹链接（形如 https://xxx.feishu.cn/drive/folder/...）")
    return {"folder_token": match.group(1) if match else None}


async def _make(ctx: ToolContext, kind: str, filename: str, spec: dict, args: dict) -> str:
    try:
        record = await filejobs.start(ctx.session, ctx.feishu, ctx.user, kind, outputs.safe_name(filename, kind), spec, _folder(args))
    except outputs.OutputError as exc:
        raise ToolError(str(exc)) from exc
    if record.status != "done":
        ctx.cards.append(filejobs.card(record))
        where = "并存进他的飞书云空间" if record.save_to_drive is not None else ""
        return (f"《{record.filename}》已开始在后台生成{where}（内容较多或需要上传，可能要一阵子）。生成后会重新打开核对，"
                "做完会在飞书里告诉他，对话里的文件卡片也会显示进度。告诉用户正在做、做完会通知，不要说已经做好。")
    data = record.content
    ctx.cards.append(filejobs.card(record, len(data)))
    sent = ""
    if ctx.conversation.channel == "feishu":
        try:
            await ctx.feishu.send_file(ctx.user.feishu_open_id, data, record.filename, outputs.FEISHU_FILE_TYPE[kind])
            sent = "，已在飞书里发给他"
        except FeishuError as exc:
            logger.warning("发送生成的文件失败：%s", exc)
            sent = f"（飞书发送失败：{exc}，可以在网页下载）"
    verified = record.verified
    check = "核对通过" if verified["ok"] else "⚠️ 核对不一致"
    sources = spec.get("sources") or []
    return (f"已生成《{record.filename}》（{len(data) // 1024 + 1} KB，文件编号 {record.id}）{sent}。{check}：{verified['detail']}。"
            "注意：这个核对只说明文件内容和要写的一致，不说明原始数据和分析结论已经核实。告诉用户时要分开说："
            "文件写对了没有；数据和结论来自哪里" + (f"（{'；'.join(sources)}）" if sources else "（没有注明来源，要提醒他数据未核实）")
            + "、哪些是推断需要他确认。他要存进飞书云空间时用 save_file_to_drive。")


@tool(
    "create_excel_file",
    "生成一个 Excel 文件（.xlsx）给用户：一个或多个工作表，每个有表头和数据行。数据必须来自已经查到的真实内容，不要编造；"
    "数字用数字类型，合计等可以写公式。生成后会重新打开逐格核对，结果会显示给用户。",
    {"filename": {"type": "string", "description": "文件名，不含扩展名"},
     "sheets": {"type": "array", "minItems": 1, "maxItems": 10, "items": SHEET}, **DRIVE, **SOURCES},
    ["filename", "sheets"],
)
async def create_excel_file(ctx: ToolContext, args: dict) -> str:
    return await _make(ctx, "xlsx", args["filename"], {"sheets": args["sheets"], "sources": args.get("sources") or []}, args)


@tool(
    "create_ppt_file",
    "生成一个 PPT 文件（.pptx，16:9）给用户：可选封面标题，每页一个标题加要点，或一张表格。内容必须来自已经查到的真实材料，不要编造；"
    "要点精炼，每页不超过 6 条。生成后会重新打开逐页核对，结果会显示给用户。",
    {"filename": {"type": "string", "description": "文件名，不含扩展名"},
     "title": {"type": "string", "description": "封面标题（可选）"},
     "slides": {"type": "array", "minItems": 1, "maxItems": outputs.MAX_SLIDES, "items": SLIDE}, **DRIVE, **SOURCES},
    ["filename", "slides"],
)
async def create_ppt_file(ctx: ToolContext, args: dict) -> str:
    return await _make(ctx, "pptx", args["filename"], {"title": args.get("title"), "slides": args["slides"],
                                                      "sources": args.get("sources") or []}, args)


@tool(
    "create_word_file",
    "生成一个 Word 文件（.docx）给用户：可选总标题，每节一个小标题，下面是段落、要点或一张表格（纪要、报告、说明、通知……）。"
    "内容必须来自已经查到的真实材料，不要编造；不知道的写【待确认】。生成后会重新打开逐段核对，结果会显示给用户。",
    {"filename": {"type": "string", "description": "文件名，不含扩展名"},
     "title": {"type": "string", "description": "文档标题（可选）"},
     "sections": {"type": "array", "minItems": 1, "maxItems": outputs.MAX_SECTIONS, "items": SECTION}, **DRIVE, **SOURCES},
    ["filename", "sections"],
)
async def create_word_file(ctx: ToolContext, args: dict) -> str:
    return await _make(ctx, "docx", args["filename"], {"title": args.get("title"), "sections": args["sections"],
                                                      "sources": args.get("sources") or []}, args)


@tool(
    "save_file_to_drive",
    "把 Relay 已经生成的文件存进他的飞书云空间（默认“我的空间”，或 folder_url 指定的文件夹）。只在他明确要求时用。"
    "上传后会从云空间下载回来比对；在后台做，完成后在飞书里告诉他链接。",
    {"file_id": {"type": "string", "description": "生成文件时返回的文件编号"}, "folder_url": DRIVE["folder_url"]},
    ["file_id"],
    user_initiated_only=True,
)
async def save_file_to_drive(ctx: ToolContext, args: dict) -> str:
    try:
        record = await ctx.session.get(GeneratedFile, uuid.UUID(args["file_id"]))
    except ValueError:
        record = None
    if record is None or record.user_id != ctx.user.id:
        raise ToolError("没有找到这个文件")
    if record.status != "done":
        raise ToolError("这个文件还在生成中，做完再存")
    record.save_to_drive = _folder({**args, "save_to_drive": True})
    record.status, record.stage, record.notify = "queued", "排队中", True
    await ctx.session.flush()
    filejobs.kick(record.id, ctx.feishu)
    ctx.cards.append(filejobs.card(record))
    return f"已开始把《{record.filename}》存进他的飞书云空间，上传后会下载回来比对，完成后在飞书里告诉他链接。告诉用户正在存，不要说已经存好。"
