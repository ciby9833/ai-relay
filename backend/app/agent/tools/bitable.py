"""多维表格：看字段、按字段名新增一条记录（提交工作餐、登记需求……）。写入要用户确认，或在他授权的定时任务里直接办。"""

from app.agent.tools.base import ToolContext, ToolError, tool
from app.agent.tools.collab import _finish
from app.feishu.client import FeishuError
from app.models import PendingAction
from app.sources import bitable

TARGET = {
    "base": {"type": "string", "description": "多维表格链接（/base/…）或 app_token"},
    "table_id": {"type": "string", "description": "数据表 ID；链接里带 ?table= 时可省略"},
}


@tool(
    "list_base_fields",
    "看多维表格一张数据表有哪些字段、什么类型、单选/多选有哪些选项。往表里提交记录前先看这个。",
    TARGET,
    ["base"],
)
async def list_base_fields(ctx: ToolContext, args: dict) -> str:
    try:
        app_token, table_id = bitable.parse_target(args["base"], args.get("table_id"))
        table = await bitable.table_of(ctx.feishu, ctx.user, app_token, table_id)
        fields = await bitable.fields_of(ctx.feishu, ctx.user, app_token, table["table_id"])
    except bitable.BaseError as exc:
        raise ToolError(str(exc)) from exc
    except FeishuError as exc:
        raise ToolError(bitable.explain(exc)) from exc
    return f"《{table['name']}》（app_token {app_token}，table_id {table['table_id']}）的字段：\n{bitable.describe_fields(fields)}"


@tool(
    "prepare_add_base_record",
    "准备往多维表格新增一条记录（例如提交每天的工作餐、登记一条需求），以用户本人身份提交。"
    "fields 用“字段名: 值”，单选/多选填选项名，人员填人名（“我”表示用户本人），日期用 ISO 格式；"
    "创建人、创建时间这类系统字段不用填。会展示给用户确认后才提交；在用户授权过的定时任务里会直接提交。",
    {
        **TARGET,
        "fields": {"type": "object", "minProperties": 1, "maxProperties": 50, "description": "字段名 → 值"},
    },
    ["base", "fields"],
)
async def prepare_add_base_record(ctx: ToolContext, args: dict) -> str:
    try:
        app_token, table_id = bitable.parse_target(args["base"], args.get("table_id"))
        table = await bitable.table_of(ctx.feishu, ctx.user, app_token, table_id)
        fields = await bitable.fields_of(ctx.feishu, ctx.user, app_token, table["table_id"])
        values, shown = await bitable.convert(ctx.feishu, ctx.user, fields, args["fields"], session=ctx.session)
        latest = await bitable.my_latest(ctx.feishu, ctx.user, app_token, table["table_id"], fields)
    except bitable.BaseError as exc:
        raise ToolError(str(exc)) from exc
    except FeishuError as exc:
        raise ToolError(bitable.explain(exc)) from exc
    previous = None
    if latest and latest.get("created_time"):
        from datetime import UTC, datetime
        from zoneinfo import ZoneInfo

        at = datetime.fromtimestamp(int(latest["created_time"]) / 1000, UTC).astimezone(ZoneInfo(ctx.user.timezone))
        previous = f"你上一次在这张表提交是 {at:%m-%d %H:%M}"
    action = PendingAction(
        user_id=ctx.user.id, kind="base_record", summary=f"往《{table['name']}》提交一条记录",
        payload={"app_token": app_token, "table_id": table["table_id"], "table_name": table["name"],
                 "fields": values, "shown": shown, "previous": previous},
    )
    ctx.session.add(action)
    await ctx.session.flush()
    note = f"（{previous}，注意别重复提交）" if previous else ""
    return await _finish(ctx, action) + note
