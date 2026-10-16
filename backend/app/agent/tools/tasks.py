from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from app.agent.tools.base import ToolContext, ToolError, tool
from app.models import ScheduledTask
from app.scheduler.schedule import ScheduleError, parse_run_at, validate_cron

MAX_TASKS = 20


def _describe(task: ScheduledTask) -> str:
    when = f"cron {task.cron}" if task.cron else "一次性"
    if task.next_run_at:
        local = task.next_run_at.astimezone(ZoneInfo(task.timezone))
        when += f"，下次 {local:%Y-%m-%d %H:%M}"
    status = "" if task.enabled else "（已结束）"
    return f"#{task.id} {task.title} [{when}]{status}"


@tool(
    "create_scheduled_task",
    "创建定时任务。到点后 Relay 会按 prompt 独立执行一轮，并把结果通过飞书私聊发给用户。"
    "周期任务给 cron，一次性提醒给 run_at，二者必须且只能给一个，时间都按用户所在时区理解。"
    "prompt 要写成到时候能独立执行的完整指令，因为执行时看不到当前这段对话。",
    {
        "title": {"type": "string", "description": "简短的任务名"},
        "prompt": {"type": "string", "description": "到点时要执行的完整指令"},
        "cron": {"type": "string", "description": "5 段 cron：分 时 日 月 周，例如 0 9 * * 1-5"},
        "run_at": {"type": "string", "description": "ISO 8601 时间，例如 2026-10-15T09:00"},
    },
    ["title", "prompt"],
)
async def create_scheduled_task(ctx: ToolContext, args: dict) -> str:
    cron, run_at = args.get("cron"), args.get("run_at")
    if bool(cron) == bool(run_at):
        raise ToolError("cron 和 run_at 必须且只能提供一个")
    count = await ctx.session.scalar(
        select(func.count())
        .select_from(ScheduledTask)
        .where(ScheduledTask.user_id == ctx.user.id, ScheduledTask.enabled)
    )
    if count >= MAX_TASKS:
        raise ToolError(f"每人最多 {MAX_TASKS} 个生效中的定时任务，请先删掉一些")
    timezone = ctx.user.timezone
    try:
        next_run = validate_cron(cron, timezone) if cron else parse_run_at(run_at, timezone)
    except ScheduleError as exc:
        raise ToolError(str(exc)) from exc
    task = ScheduledTask(
        user_id=ctx.user.id,
        title=args["title"],
        prompt=args["prompt"],
        cron=cron,
        timezone=timezone,
        next_run_at=next_run,
    )
    ctx.session.add(task)
    await ctx.session.flush()
    return f"已创建：{_describe(task)}"


@tool("list_scheduled_tasks", "列出用户的定时任务。", {})
async def list_scheduled_tasks(ctx: ToolContext, args: dict) -> str:
    result = await ctx.session.execute(
        select(ScheduledTask)
        .where(ScheduledTask.user_id == ctx.user.id)
        .order_by(ScheduledTask.id)
    )
    tasks = list(result.scalars())
    return "\n".join(_describe(task) for task in tasks) if tasks else "还没有定时任务"


@tool(
    "delete_scheduled_task",
    "删除一个定时任务。",
    {"task_id": {"type": "integer", "description": "任务编号，即 #后面的数字"}},
    ["task_id"],
)
async def delete_scheduled_task(ctx: ToolContext, args: dict) -> str:
    result = await ctx.session.execute(
        delete(ScheduledTask).where(
            ScheduledTask.id == args["task_id"], ScheduledTask.user_id == ctx.user.id
        )
    )
    if not result.rowcount:
        raise ToolError(f"没有找到任务 #{args['task_id']}")
    return f"已删除任务 #{args['task_id']}"
