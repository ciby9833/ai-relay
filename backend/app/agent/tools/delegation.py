"""工作区内的协作：助理替用户请同事做事、查看和回应协作。

- 只能请同一个工作区的成员；对方看到的只有委托里写明的内容和共享的材料，助理不要把用户的私人对话、记忆原样塞进去。
- 发出请求、接受、拒绝、提交、验收……都只“准备”成待确认操作，用户本人确认后才生效：助理不能替人承诺。
- 没约定期限就不填期限，不编日期。
"""

from app import collab
from app.agent.tools.base import ToolContext, ToolError, tool
from app.proactive import actions

MATERIAL = {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string", "description": "https 链接"},
                                              "text": {"type": "string", "description": "或者直接贴内容"}}}


async def _card(ctx: ToolContext, summary: str, payload: dict) -> str:
    action = actions._new(ctx.session, ctx.user, "collab", summary, payload, getattr(ctx.mission, "id", None))
    await ctx.session.flush()
    ctx.cards.append({"kind": "action", "action_id": action.id})
    return f"已准备好（待确认操作 #{action.id}）：{summary}。用户确认后才会生效。"


@tool(
    "list_collaborations",
    "列出用户和同事之间还没结束的协作（他请别人的、别人请他的），以及每份现在轮到谁、能做什么。",
    {"include_closed": {"type": "boolean", "description": "也列出已结束的，默认不列"}},
)
async def list_collaborations(ctx: ToolContext, args: dict) -> str:
    rows = await collab.mine(ctx.session, ctx.user, include_closed=bool(args.get("include_closed")))
    if not rows:
        return "没有进行中的协作。"
    out = []
    for d in rows:
        data = await collab.describe(ctx.session, ctx.user, d, with_log=False)
        other = data["assignee"]["name"] if data["role"] == "requester" else data["requester"]["name"]
        direction = f"你请 {other}" if data["role"] == "requester" else f"{other} 请你"
        out.append(f"- #{d.id}《{d.title}》{direction} · {data['status_text']} · 期限 {data['due_at'] or '未约定'}"
                   f" · 你能做：{'、'.join(collab.ACTION_TEXT[a] for a in data['actions']) or '等对方'}")
    return "\n".join(out)


@tool(
    "get_collaboration",
    "看一份协作的完整内容：要求、交付、验收、共享材料、对方提的修改、提交的结果、变更记录。只有双方本人能看。",
    {"id": {"type": "integer"}},
    ["id"],
)
async def get_collaboration(ctx: ToolContext, args: dict) -> str:
    try:
        d = await collab.get_for(ctx.session, ctx.user, int(args["id"]))
    except collab.CollabError as exc:
        raise ToolError(str(exc)) from exc
    return collab.as_text(await collab.describe(ctx.session, ctx.user, d))


@tool(
    "request_colleague",
    "请同一个工作区的同事做一件事（发出协作请求）。要写清楚要做什么、交付什么；期限、验收标准只有用户说了才填。"
    "只放用户同意给对方看的内容和材料，不要把用户的私人对话或记忆原样放进去。准备好后需要用户确认才会发出。",
    {
        "colleague": {"type": "string", "description": "同事的名字或邮箱（必须是本工作区成员）"},
        "title": {"type": "string"},
        "brief": {"type": "string", "description": "要做什么、为什么、背景"},
        "deliverable": {"type": "string", "description": "交付什么"},
        "acceptance": {"type": "string", "description": "怎样算完成（用户说了才填）"},
        "due_at": {"type": "string", "description": "ISO 8601，用户明确说了期限才填"},
        "materials": {"type": "array", "items": MATERIAL, "description": "共享给对方的材料（链接或内容）"},
    },
    ["colleague", "title", "brief", "deliverable"],
)
async def request_colleague(ctx: ToolContext, args: dict) -> str:
    try:
        assignee = await collab.find_member(ctx.session, ctx.user, args["colleague"])
        materials = collab._clean_materials(args.get("materials"))
        due = collab._due(args.get("due_at"))
    except collab.CollabError as exc:
        raise ToolError(str(exc)) from exc
    payload = {"op": "create", "assignee_id": str(assignee.id), "assignee": assignee.name, "title": args["title"],
               "brief": args["brief"], "deliverable": args["deliverable"], "acceptance": args.get("acceptance"),
               "due_at": due.isoformat() if due else None, "materials": materials}
    when = f"，期限 {due:%m-%d %H:%M}" if due else "，期限未约定"
    return await _card(ctx, f"请 {assignee.name}：{args['title']}（交付：{args['deliverable']}{when}）", payload)


@tool(
    "respond_collaboration",
    "回应或推进一份协作。承接方：accept 接受 / decline 拒绝（要理由）/ counter 提出修改（要理由，可改 deliverable、acceptance、due_at）/ "
    "submit 提交结果（要写明交付了什么，可附材料）。请求方：agree 同意对方的修改 / revise 修改要求（对方要重新接受）/ "
    "approve 验收通过 / return 退回（要说明哪里要改）/ cancel 取消。准备好后需要用户确认才会生效。",
    {
        "id": {"type": "integer"},
        "action": {"type": "string", "enum": list(collab.ACTION_TEXT)},
        "note": {"type": "string"},
        "changes": {"type": "object", "description": "counter / revise 时要改的字段：brief、deliverable、acceptance、due_at、title"},
        "materials": {"type": "array", "items": MATERIAL},
    },
    ["id", "action"],
)
async def respond_collaboration(ctx: ToolContext, args: dict) -> str:
    try:
        d = await collab.get_for(ctx.session, ctx.user, int(args["id"]))
        data = await collab.describe(ctx.session, ctx.user, d, with_log=False)
        if args["action"] not in data["actions"]:
            raise collab.CollabError(f"现在不能「{collab.ACTION_TEXT[args['action']]}」，能做的：{'、'.join(collab.ACTION_TEXT[a] for a in data['actions']) or '没有，等对方'}")
        if args["action"] in collab.NOTE_REQUIRED and not (args.get("note") or "").strip():
            raise collab.CollabError(collab.NOTE_REQUIRED[args["action"]])
        materials = collab._clean_materials(args.get("materials")) if args.get("materials") is not None else None
    except collab.CollabError as exc:
        raise ToolError(str(exc)) from exc
    payload = {"op": "act", "delegation_id": d.id, "action": args["action"], "version": d.version, "note": args.get("note"),
               "changes": args.get("changes"), "materials": materials}
    other = data["assignee"]["name"] if data["role"] == "requester" else data["requester"]["name"]
    return await _card(ctx, f"协作《{d.title}》：{collab.ACTION_TEXT[args['action']]}（对方：{other}）", payload)
