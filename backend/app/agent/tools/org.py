"""组织架构工具：谁负责哪个部门、部门里有谁、某人的职位和直属上级。"""

from app.agent.tools.base import ToolContext, ToolError, tool
from app.feishu.client import FeishuError
from app.sources import people
from app.sources.org import Org


@tool(
    "search_departments",
    "按名称搜部门，返回部门负责人、人数和所属上级部门。部门名可能是中文或英文（如“网络”和“Network”），"
    "搜不到时换另一种语言或更短的关键词再试。",
    {"query": {"type": "string", "description": "部门名关键词"}},
    ["query"],
)
async def search_departments(ctx: ToolContext, args: dict) -> str:
    org = Org(ctx.feishu, ctx.user)
    try:
        found = await org.search_departments(args["query"])
    except FeishuError as exc:
        raise ToolError(f"查询部门失败：{exc}") from exc
    if not found:
        return f"没有名称包含「{args['query']}」的部门，可以换中文/英文或更短的关键词再试"
    return "\n".join(
        f"- {d['name']}（编号 {d['id']}）：负责人 {('、'.join(d['leaders']) or '未设置')}，{d['members'] or 0} 人"
        + (f"，隶属 {d['path']}" if d["path"] else "")
        for d in found
    )


@tool(
    "list_department_members",
    "列出一个部门的直属成员和职位。department_id 用 search_departments 返回的编号。",
    {"department_id": {"type": "string"}},
    ["department_id"],
)
async def list_department_members(ctx: ToolContext, args: dict) -> str:
    org = Org(ctx.feishu, ctx.user)
    try:
        members = await org.members(args["department_id"])
    except FeishuError as exc:
        raise ToolError(f"查询成员失败：{exc}") from exc
    if not members:
        return "这个部门没有直属成员（成员可能都在下级部门里）"
    await people.remember(ctx.session, ctx.user.tenant_id, [(m["open_id"], m["name"], "contact") for m in members])
    return "\n".join(f"- {m['name']}" + (f"：{m['title']}" if m["title"] else "") for m in members)


@tool(
    "person_profile",
    "查一位同事的资料：职位、所在部门、直属上级、企业邮箱。",
    {"name": {"type": "string"}},
    ["name"],
)
async def person_profile(ctx: ToolContext, args: dict) -> str:
    try:
        found = await people.find(ctx.session, ctx.feishu, args["name"], user=ctx.user)
    except people.Ambiguous as exc:
        return f"有多个同名的人：{'、'.join(c['name'] for c in exc.candidates)}，需要用户说明是哪一位"
    if not found:
        return "在飞书里搜不到这个人"
    profile = await Org(ctx.feishu, ctx.user).profile(found[0]["open_id"])
    lines = [f"{profile['name']}"]
    if profile["title"]:
        lines.append(f"职位：{profile['title']}")
    if profile["departments"]:
        lines.append("部门：" + "；".join(profile["departments"]))
    if profile["manager"]:
        lines.append(f"直属上级：{profile['manager']}")
    if profile["email"]:
        lines.append(f"邮箱：{profile['email']}")
    return "\n".join(lines)
