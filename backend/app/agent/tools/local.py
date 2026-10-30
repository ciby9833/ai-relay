"""他 Mac 上的文件：只能用他在 Relay 客户端里授权的文件夹（读、写分开授权）。

列文件、读文件、把 Relay 生成的文件存进去（只新建，同名时自动换名，不覆盖）。Mac 不在线时明确说，不假装做了。
"""

import hashlib
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
    version = f"（{_size(result.get('size'))}，修改于 {(result.get('modified') or '')[:16]}，sha256 {(result.get('sha256') or '')[:12]}）"
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
