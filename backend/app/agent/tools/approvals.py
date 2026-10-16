"""本人审批列表：不接受模型传入他人的 user_id。"""
import json

from app.agent.tools.base import ToolContext, ToolError, tool
from app.feishu.client import FeishuError
from app.sources import approval


@tool("query_my_approvals", "查本人的审批历史，用于回答“我发起的那个审批到哪了”“上周批过什么”之类的问题：done 我已审批、initiated 我发起的（含结果）、cc 抄送我的。待我审批用 list_pending_approvals。返回分页片段，offset 继续。", {
    "category": {"type": "string", "enum": ["done", "initiated", "cc"]},
    "offset": {"type": "integer", "minimum": 0},
}, ["category"])
async def query_my_approvals(ctx: ToolContext, args: dict) -> str:
    try:
        rows = await approval.query_tasks(ctx.feishu, ctx.user, args["category"])
    except FeishuError as exc:
        raise ToolError(str(exc)) from exc
    offset = args.get("offset", 0)
    return json.dumps({"total": len(rows), "next_offset": offset + 30 if offset + 30 < len(rows) else None,
        "items": [{"instance_code": r.get("process_code"), "title": r.get("title"),
            "result": approval.PROCESS_LABELS.get(str(r.get("process_status")), str(r.get("process_status"))),
            "initiators": r.get("initiator_names"), "url": (r.get("urls") or {}).get("pc")}
            for r in rows[offset:offset + 30]]}, ensure_ascii=False)


@tool("read_my_approval", "读取本人发起、已办或抄送的审批详情（表单、流程进度、意见）。先用 query_my_approvals 获取 instance_code；待我审批的详情用 get_approval_detail。", {
    "category": {"type": "string", "enum": ["done", "initiated", "cc"]},
    "instance_code": {"type": "string", "minLength": 1},
}, ["category", "instance_code"])
async def read_my_approval(ctx: ToolContext, args: dict) -> str:
    try:
        rows = await approval.query_tasks(ctx.feishu, ctx.user, args["category"])
        if not any(r.get("process_code") == args["instance_code"] for r in rows):
            raise ToolError("该审批不在你的这个分类里，不能读取")
        return json.dumps(await approval.instance_detail(ctx.feishu, args["instance_code"], ctx.user.feishu_open_id), ensure_ascii=False)
    except FeishuError as exc:
        raise ToolError(str(exc)) from exc
