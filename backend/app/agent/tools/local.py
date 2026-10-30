"""他 Mac 上的文件：只能用他在 Relay 客户端里授权的文件夹（读、写分开授权）。

列文件、读文件、把 Relay 生成的文件存进去（只新建，同名时自动换名，不覆盖）。Mac 不在线时明确说，不假装做了。
"""

import hashlib
import json
import uuid

from app import devices
from app.agent.tools.base import ToolContext, ToolError, tool
from app.models import GeneratedFile


def _code(exc: devices.DeviceError) -> str:
    """设备相关的失败归到统一错误码。"""
    text = str(exc)
    if "还没有安装" in text:
        return "not_connected"
    if "不在线" in text or "没有及时响应" in text:
        return "offline"
    if "没有授权" in text:
        return "no_access"
    if "找不到" in text or "不存在" in text:
        return "not_found"
    if "结果未知" in text:
        return "conflict"
    return "precondition"


def _size(n: int | None) -> str:
    if not n:
        return ""
    return f"{n / 1024 / 1024:.1f}MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)}KB"


@tool(
    "local_folders",
    "看用户在 Mac 客户端里授权了哪些文件夹（读 / 写），以及 Mac 现在在不在线。",
    {},
)
async def local_folders(ctx: ToolContext, args: dict) -> str:
    found = await devices.mine(ctx.session, ctx.user)
    if not found:
        return "用户还没有安装或登录 Relay 的 Mac 客户端。"
    lines = []
    for device in found:
        state = "在线" if devices.online(device) else "不在线"
        folders = "、".join(f"「{f['label']}」（{'读写' if f.get('write') and f.get('read') else '只写' if f.get('write') else '只读'}）"
                            for f in device.folders or []) or "还没有授权文件夹"
        lines.append(f"- {device.name}（{state}）：{folders}")
    return "\n".join(lines)


@tool(
    "list_local_files",
    "列出用户 Mac 上某个授权文件夹里的文件（可以进子文件夹，可以按文件名关键字找）。",
    {
        "folder": {"type": "string", "description": "授权文件夹的名字"},
        "path": {"type": "string", "description": "文件夹里的子路径，默认根目录"},
        "query": {"type": "string", "description": "文件名包含的关键字（会在子文件夹里一起找）"},
    },
    ["folder"],
)
async def list_local_files(ctx: ToolContext, args: dict) -> str:
    try:
        result = await devices.request(ctx.session, ctx.user, "list", {"folder": args["folder"], "path": args.get("path") or "",
                                                                       "query": args.get("query") or "", "limit": 200})
    except devices.DeviceError as exc:
        raise ToolError(str(exc), _code(exc)) from exc
    entries = result.get("entries") or []
    if not entries:
        return "没有找到文件。"
    lines = [f"- {'📁 ' if e.get('dir') else ''}{e['path']}" + (f"（{_size(e.get('size'))}，修改于 {e.get('modified', '')[:16]}）" if not e.get("dir") else "")
             for e in entries]
    more = "（只列出前 200 个）" if result.get("truncated") else ""
    return "\n".join(lines) + more


@tool(
    "read_local_file",
    "读取用户 Mac 上授权文件夹里的一个文件（xlsx、docx、pdf、csv、txt 等），返回文字内容和文件版本。",
    {"folder": {"type": "string"}, "path": {"type": "string", "description": "文件夹里的相对路径"}},
    ["folder", "path"],
)
async def read_local_file(ctx: ToolContext, args: dict) -> str:
    try:
        result = await devices.request(ctx.session, ctx.user, "read", {"folder": args["folder"], "path": args["path"]}, timeout=60)
    except devices.DeviceError as exc:
        raise ToolError(str(exc), _code(exc)) from exc
    where = "，在他的 Mac 上解析" if result.get("parsed_on") == "device" else ""
    version = f"（{_size(result.get('size'))}，修改于 {(result.get('modified') or '')[:16]}，sha256 {(result.get('sha256') or '')[:12]}{where}）"
    note = "\n\n（内容较长，只读到前一部分）" if result.get("truncated") else ""
    return f"《{args['folder']}/{args['path']}》{version}\n\n{result.get('text', '')}{note}"


@tool(
    "save_file_to_mac",
    "把 Relay 生成的文件（Excel、Word、PPT）存进用户 Mac 上授权写入的文件夹。只新建文件，同名时自动换名，不覆盖原有文件；"
    "存完会重新读回核对。用户说要存到电脑上时才用。",
    {
        "file_id": {"type": "string", "description": "生成文件时返回的文件编号"},
        "folder": {"type": "string", "description": "授权写入的文件夹名字"},
        "path": {"type": "string", "description": "文件夹里的相对路径（含文件名），默认用生成时的文件名"},
    },
    ["file_id", "folder"],
)
async def save_file_to_mac(ctx: ToolContext, args: dict) -> str:
    try:
        record = await ctx.session.get(GeneratedFile, uuid.UUID(args["file_id"]))
    except ValueError:
        record = None
    if record is None or record.user_id != ctx.user.id or record.status != "done" or not record.content:
        raise ToolError("找不到这个文件，或者还没生成好")
    path = args.get("path") or record.filename
    try:
        result = await devices.request(ctx.session, ctx.user, "write", {
            "folder": args["folder"], "path": path, "file_id": str(record.id),
            "sha256": hashlib.sha256(record.content).hexdigest(), "size": len(record.content)}, timeout=90)
    except devices.DeviceError as exc:
        raise ToolError(str(exc), _code(exc)) from exc
    renamed = "（同名文件已存在，换了个名字，没有覆盖）" if result.get("path") != path else ""
    checked = "存完读回核对一致" if result.get("verified") else "⚠️ 读回核对不一致，请打开看一下"
    return f"已存到 Mac：{args['folder']}/{result.get('path')}{renamed}，{checked}。"


# ---------- 本机项目和本机技能 ----------

PROJECT_FILE = "RELAY.md"
FILE_REF = {"type": "object", "properties": {"folder": {"type": "string", "description": "授权文件夹的名字"},
                                             "path": {"type": "string", "description": "文件夹里的相对路径"},
                                             "sheet": {"type": "string", "description": "工作表名，默认第一张"}},
            "required": ["folder", "path"], "additionalProperties": False}
OUTPUT_REF = {"type": "object", "properties": {"folder": {"type": "string", "description": "授权写入的文件夹名字"},
                                               "path": {"type": "string", "description": "新文件的相对路径（.xlsx）"}},
              "required": ["folder", "path"], "additionalProperties": False}


@tool(
    "open_local_project",
    "打开他 Mac 上的一个授权文件夹（一个项目）：读项目说明 RELAY.md（他写的：这个项目是什么、数据在哪些文件、产出放哪），"
    "列出最上层的文件。处理这个文件夹里的事之前先看这个。",
    {"folder": {"type": "string", "description": "授权文件夹的名字"}},
    ["folder"],
)
async def open_local_project(ctx: ToolContext, args: dict) -> str:
    try:
        listing = await devices.request(ctx.session, ctx.user, "list", {"folder": args["folder"], "path": "", "query": "", "limit": 100})
    except devices.DeviceError as exc:
        raise ToolError(str(exc), _code(exc)) from exc
    entries = listing.get("entries") or []
    notes = "这个文件夹里没有 RELAY.md（项目说明）。"
    if any(e.get("path") == PROJECT_FILE for e in entries):
        try:
            read = await devices.request(ctx.session, ctx.user, "read", {"folder": args["folder"], "path": PROJECT_FILE}, timeout=60)
            notes = f"项目说明（{PROJECT_FILE}，他本人写的）：\n{read.get('text', '')}"
        except devices.DeviceError as exc:
            notes = f"读 {PROJECT_FILE} 失败：{exc}"
    files = "\n".join(f"- {'📁 ' if e.get('dir') else ''}{e['path']}" for e in entries) or "（空）"
    return f"{notes}\n\n最上层的文件：\n{files}"


@tool(
    "compare_local_tables",
    "在他的 Mac 上对比两张表（Excel / CSV），按关键列找出新增、删除和变化的格子，结果写成一个新的 Excel 文件（不改原文件）。"
    "整张表不离开他的电脑，回来的只有数量和最多 10 条示例。",
    {"left": FILE_REF, "right": FILE_REF, "key": {"type": "string", "description": "关键列的列名（例如“单号”）"}, "output": OUTPUT_REF},
    ["left", "right", "key", "output"],
)
async def compare_local_tables(ctx: ToolContext, args: dict) -> str:
    try:
        result = await devices.request_skill(ctx.session, ctx.user, "compare_tables", args)
    except devices.DeviceError as exc:
        raise ToolError(str(exc), "unsupported" if "版本太旧" in str(exc) else _code(exc)) from exc
    return json.dumps(result, ensure_ascii=False)


@tool(
    "summarize_local_table",
    "在他的 Mac 上汇总一张表（Excel / CSV）：按某几列分组，计行数，对数值列求和，结果写成一个新的 Excel 文件（不改原文件）。",
    {"source": FILE_REF, "group_by": {"type": "array", "items": {"type": "string"}, "maxItems": 5, "description": "分组的列名"},
     "sum": {"type": "array", "items": {"type": "string"}, "maxItems": 10, "description": "要求和的数值列名"}, "output": OUTPUT_REF},
    ["source", "output"],
)
async def summarize_local_table(ctx: ToolContext, args: dict) -> str:
    try:
        result = await devices.request_skill(ctx.session, ctx.user, "summarize_table", args)
    except devices.DeviceError as exc:
        raise ToolError(str(exc), "unsupported" if "版本太旧" in str(exc) else _code(exc)) from exc
    return json.dumps(result, ensure_ascii=False)


# ---------- 修改已有的 Excel、按模板生成 ----------

def _skill_error(exc: devices.DeviceError) -> ToolError:
    return ToolError(str(exc), "unsupported" if "版本太旧" in str(exc) else "conflict" if "被改过" in str(exc) else _code(exc))


@tool(
    "prepare_local_edit",
    "准备修改他 Mac 上的一个 Excel 文件里的格子：先读出这些格子现在的值和文件版本，做成卡片给他看（原值 → 新值），他确认后才写。"
    "默认另存为新文件（原文件不动）；只有他明确说要覆盖原文件时用 mode=overwrite（覆盖前自动备份；文件里有图表、透视表、图片、宏时不能覆盖）。",
    {"file": FILE_REF,
     "cells": {"type": "array", "minItems": 1, "maxItems": 500, "items": {"type": "object", "properties": {
         "cell": {"type": "string", "description": "格子编号，例如 C2"}, "value": {"type": ["string", "number"]}},
         "required": ["cell", "value"], "additionalProperties": False}},
     "mode": {"type": "string", "enum": ["save_as", "overwrite"], "description": "默认 save_as"},
     "output_path": {"type": "string", "description": "另存时的新文件名（可选）"}},
    ["file", "cells"],
)
async def prepare_local_edit(ctx: ToolContext, args: dict) -> str:
    from app.proactive import actions

    mode = args.get("mode") or "save_as"
    try:
        preview = await devices.request_skill(ctx.session, ctx.user, "preview_edit", {"file": args["file"], "cells": args["cells"]}, timeout=60)
    except devices.DeviceError as exc:
        raise _skill_error(exc) from exc
    if mode == "overwrite" and not preview.get("overwrite_allowed"):
        raise ToolError(f"文件里有{'、'.join(preview.get('risks') or [])}，重写可能丢失，不能覆盖；请改为另存", "precondition")
    name = args["file"]["path"]
    notes = ([f"覆盖原文件《{name}》（会先在同一个文件夹里备份原文件）"] if mode == "overwrite"
             else [f"另存为新文件{('《' + args['output_path'] + '》') if args.get('output_path') else '（原文件不动）'}"])
    if preview.get("risks"):
        notes.append(f"文件里有{'、'.join(preview['risks'])}，所以只能另存")
    action = actions._new(ctx.session, ctx.user, "local_edit", f"修改 Mac 上的《{name}》（{len(args['cells'])} 个格子，工作表「{preview.get('sheet')}」）", {
        "file": {**args["file"], "sheet": preview.get("sheet")}, "cells": preview.get("cells") or [], "expected_sha256": preview.get("sha256"),
        "mode": mode, "output_path": args.get("output_path"), "notes": notes}, getattr(ctx.mission, "id", None))
    await ctx.session.flush()
    ctx.cards.append({"kind": "action", "action_id": action.id})
    return f"已准备好（待确认操作 #{action.id}）：{action.summary}。他确认后才会写。"


@tool(
    "inspect_local_template",
    "看他 Mac 上一个模板（Word / Excel）里有哪些占位符（写成 {{名称}}）。按模板生成文件前先看这个，确定要准备哪些内容。",
    {"template": FILE_REF},
    ["template"],
)
async def inspect_local_template(ctx: ToolContext, args: dict) -> str:
    try:
        result = await devices.request_skill(ctx.session, ctx.user, "template_fields", {"template": args["template"]}, timeout=60)
    except devices.DeviceError as exc:
        raise _skill_error(exc) from exc
    return json.dumps(result, ensure_ascii=False)


@tool(
    "fill_local_template",
    "按他 Mac 上的模板生成一个新文件（例如周报）：values 里给每个占位符的内容（列表会写成一行一条）。模板本身不改；生成后核对没有留下占位符。",
    {"template": FILE_REF,
     "values": {"type": "object", "additionalProperties": {"type": ["string", "number", "array"], "items": {"type": "string"}},
                "description": "占位符 → 内容"},
     "output": OUTPUT_REF},
    ["template", "values", "output"],
)
async def fill_local_template(ctx: ToolContext, args: dict) -> str:
    try:
        result = await devices.request_skill(ctx.session, ctx.user, "fill_template", args)
    except devices.DeviceError as exc:
        raise _skill_error(exc) from exc
    return json.dumps(result, ensure_ascii=False)
