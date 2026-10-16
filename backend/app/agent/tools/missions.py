"""长期任务相关的工具。

对话里（主线、网页、飞书）：交给 Relay 一个长期任务、查看、回答它的问题、取消。
任务内部（Relay 在后台执行时）：更新计划和笔记、汇报、提问、决定下次什么时候醒/等什么、结束任务。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.agent.tools.base import ToolContext, ToolError, tool
from app.missions import service
from app.models import Mission, Signal

CHAT = {"home", "web", "feishu"}
MISSION = {"mission"}


async def _own(ctx: ToolContext, mission_id: int) -> Mission:
    mission = await ctx.session.get(Mission, mission_id)
    if mission is None or mission.user_id != ctx.user.id:
        raise ToolError(f"没有找到任务 #{mission_id}")
    return mission


def _current(ctx: ToolContext) -> Mission:
    if ctx.mission is None:
        raise ToolError("只能在长期任务里使用")
    return ctx.mission


# ---------- 对话里 ----------


@tool(
    "start_mission",
    "把一件需要持续推进、跨越几小时到几周的事交给 Relay 在后台办，例如“盯着客户A的报价直到他确认”"
    "“约张三李四下周开会并跟到都接受”“每天下班前看看这几个需求有没有进展”。"
    "一次就能办完的事不要用这个，直接做。goal 要写清楚做到什么程度算完成、有什么约束。",
    {
        "title": {"type": "string", "description": "简短的任务名"},
        "goal": {"type": "string", "description": "目标、完成标准和约束"},
    },
    ["title", "goal"],
    channels=CHAT,
)
async def start_mission(ctx: ToolContext, args: dict) -> str:
    mission = await service.create(ctx.session, ctx.user, args["title"], args["goal"])
    ctx.cards.append(service.card(mission))
    return (
        f"已接下长期任务 #{mission.id}，Relay 会在后台开始推进（半分钟内第一次行动），进展会在主线里汇报。"
        "对外的操作默认都会先请用户确认；用户可以在任务卡片上授权某几类操作自动执行。"
    )


@tool("list_missions", "列出 Relay 正在办的长期任务和它们的进展。", {}, channels=CHAT)
async def list_missions(ctx: ToolContext, args: dict) -> str:
    missions = (await ctx.session.execute(
        select(Mission).where(Mission.user_id == ctx.user.id, Mission.status.in_(service.OPEN)).order_by(Mission.id)
    )).scalars().all()
    if not missions:
        return "现在没有在办的长期任务"
    ctx.cards.extend(service.card(m) for m in missions[:6])
    lines = []
    for m in missions:
        done = sum(1 for s in m.plan if s.get("status") == "done")
        state = {"active": "推进中", "waiting": "在等对方", "asking": f"在等你回答：{m.question}"}[m.status]
        lines.append(f"#{m.id} {m.title}（{state}，计划 {done}/{len(m.plan)}）")
    return "\n".join(lines)


@tool(
    "answer_mission",
    "把用户对某个长期任务提问的回答转给它，任务会马上继续。",
    {"mission_id": {"type": "integer"}, "answer": {"type": "string"}},
    ["mission_id", "answer"],
    channels=CHAT,
)
async def answer_mission(ctx: ToolContext, args: dict) -> str:
    mission = await _own(ctx, args["mission_id"])
    if mission.status not in service.OPEN:
        raise ToolError("这个任务已经结束了")
    await service.answer(ctx.session, mission, args["answer"])
    return f"已转告任务 #{mission.id}，它会马上继续"


@tool(
    "cancel_mission",
    "停止一个长期任务（用户说不用办了）。",
    {"mission_id": {"type": "integer"}, "reason": {"type": "string"}},
    ["mission_id"],
    channels=CHAT,
)
async def cancel_mission(ctx: ToolContext, args: dict) -> str:
    mission = await _own(ctx, args["mission_id"])
    mission.status, mission.result = "cancelled", args.get("reason") or "用户取消"
    mission.updated_at = datetime.now(UTC)
    await service.log(ctx.session, mission, "done", f"已取消：{mission.result}")
    return f"已停止任务 #{mission.id}"


# ---------- 任务内部 ----------


@tool(
    "update_plan",
    "写下或更新这个任务的计划（完整列表，会覆盖旧的）。第一次醒来先列计划，之后每做完一步更新状态。",
    {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"step": {"type": "string"}, "done": {"type": "boolean"}},
                "required": ["step", "done"],
                "additionalProperties": False,
            },
        }
    },
    ["steps"],
    channels=MISSION,
)
async def update_plan(ctx: ToolContext, args: dict) -> str:
    mission = _current(ctx)
    mission.plan = [{"step": s["step"], "status": "done" if s["done"] else "todo"} for s in args["steps"]]
    return "计划已更新"


@tool(
    "save_notes",
    "保存这个任务的工作笔记（会覆盖旧的）：关键事实、已经联系过谁、对方怎么说、还差什么。下次醒来会看到。",
    {"notes": {"type": "string"}},
    ["notes"],
    channels=MISSION,
)
async def save_notes(ctx: ToolContext, args: dict) -> str:
    _current(ctx).notes = args["notes"][:4000]
    return "笔记已保存"


@tool(
    "report_progress",
    "在主线里向用户汇报进展。important=true 时同时推到飞书（有实质进展、需要他知道的变化时才用）。"
    "不要每次醒来都汇报，没有新东西就不说。",
    {"text": {"type": "string"}, "important": {"type": "boolean"}},
    ["text", "important"],
    channels=MISSION,
)
async def report_progress(ctx: ToolContext, args: dict) -> str:
    mission = _current(ctx)
    pending = await service.prepared_this_run(ctx.session, mission)
    # 有待确认的操作时一定推到飞书，用户才能及时点确认
    await service.notify(
        ctx.session, ctx.feishu, mission, args["text"], args["important"] or bool(pending),
        cards=[{"kind": "action", "action_id": a.id} for a in pending],
    )
    return "已汇报" + (f"，并附上了 {len(pending)} 个待确认操作" if pending else "")


@tool(
    "ask_user",
    "遇到只有用户能决定的事（缺信息、要他拿主意）时提问。任务会暂停，直到他回答。",
    {"question": {"type": "string"}},
    ["question"],
    channels=MISSION,
)
async def ask_user(ctx: ToolContext, args: dict) -> str:
    mission = _current(ctx)
    mission.status, mission.question = "asking", args["question"]
    ctx.stop_turn = True
    await service.log(ctx.session, mission, "ask", args["question"])
    await service.notify(ctx.session, ctx.feishu, mission, f"关于《{mission.title}》，需要你回答：{args['question']}", important=True)
    return "已提问，任务暂停，等用户回答后会再叫醒你。这一轮到此为止。"


@tool(
    "wait_until",
    "这一轮先到这里，过一段时间再醒来看看（例如明早再查一次）。",
    {
        "hours": {"type": "number", "minimum": 0.25, "maximum": 168, "description": "多少小时后醒"},
        "why": {"type": "string"},
    },
    ["hours"],
    channels=MISSION,
)
async def wait_until(ctx: ToolContext, args: dict) -> str:
    mission = _current(ctx)
    mission.status, mission.wait_for = "active", None
    mission.next_run_at = datetime.now(UTC) + timedelta(hours=args["hours"])
    ctx.stop_turn = True
    await service.log(ctx.session, mission, "step", f"{args['hours']:g} 小时后再看" + (f"：{args['why']}" if args.get("why") else ""))
    return "好的，到时候会叫醒你。这一轮到此为止。"


@tool(
    "wait_for_reply",
    "等对方回复再继续：mail 等某封邮件线程有新回信；chat 等某个群里（某人）发言。超时没等到也会叫醒你。"
    "你准备的待确认操作被用户处理后，也会自动叫醒你，不需要专门等。",
    {
        "kind": {"type": "string", "enum": ["mail", "chat"]},
        "mail_id": {"type": "integer", "description": "kind=mail 时：那封邮件的编号"},
        "chat_id": {"type": "string", "description": "kind=chat 时：群的 chat_id"},
        "from_name": {"type": "string", "description": "kind=chat 时可选：只等这个人发言"},
        "timeout_hours": {"type": "number", "minimum": 1, "maximum": 336},
    },
    ["kind"],
    channels=MISSION,
)
async def wait_for_reply(ctx: ToolContext, args: dict) -> str:
    mission = _current(ctx)
    if args["kind"] == "mail":
        signal = await ctx.session.get(Signal, args.get("mail_id") or 0)
        if signal is None or signal.user_id != ctx.user.id or signal.kind != "mail":
            raise ToolError("需要一封已同步邮件的编号")
        wait = {"type": "mail_reply", "thread_id": signal.payload.get("thread_id") or signal.external_id}
    else:
        if not args.get("chat_id"):
            raise ToolError("需要 chat_id")
        wait = {"type": "chat_message", "chat_id": args["chat_id"]}
        if args.get("from_name"):
            from app.sources import people

            try:
                found = await people.find(ctx.session, ctx.feishu, args["from_name"], limit=1, user=ctx.user)
            except people.Ambiguous:
                found = []
            if found:
                wait |= {"from_open_id": found[0]["open_id"], "from_name": found[0]["name"]}
    mission.status, mission.wait_for = "waiting", wait
    mission.next_run_at = datetime.now(UTC) + timedelta(hours=args.get("timeout_hours", 24))
    ctx.stop_turn = True
    await service.log(ctx.session, mission, "step", f"等{service.describe_wait(wait)}")
    return "好的，等到了会叫醒你。这一轮到此为止。"


@tool(
    "complete_mission",
    "任务完成（或确定办不成）时结束它，并给用户一个结论。",
    {"result": {"type": "string", "description": "给用户的结论"}, "success": {"type": "boolean"}},
    ["result", "success"],
    channels=MISSION,
)
async def complete_mission(ctx: ToolContext, args: dict) -> str:
    mission = _current(ctx)
    mission.status = "done" if args["success"] else "failed"
    mission.result, mission.next_run_at, mission.wait_for = args["result"], None, None
    ctx.stop_turn = True
    await service.log(ctx.session, mission, "done", args["result"])
    await service.notify(
        ctx.session, ctx.feishu, mission,
        f"{'✅ 完成' if args['success'] else '⚠️ 没办成'}：{args['result']}", important=True,
    )
    return "任务已结束"
