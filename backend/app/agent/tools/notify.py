"""提醒规则：他说过哪类事要不要提醒、什么时候提醒。规则由系统在推送前直接执行（见 proactive.attention）。"""

from sqlalchemy import select

from app.agent.tools.base import ToolContext, ToolError, tool
from app.models import AttentionRule
from app.proactive import attention

LEVEL_HELP = "now=立刻告诉他；batch=攒到汇总时间一起说；brief=只放进早上的简报；mute=不提醒，只在网页看板里跟踪"


@tool(
    "set_notify_rule",
    "按用户的明确要求设置一类事的提醒方式。条件之间是“并且”：例如 group=approval + approval=请假 表示请假审批；"
    "person=Budi 表示 Budi 相关的所有事。条件写用户说的原词（人名、群名、审批类型），不要自己扩大范围。"
    "同样的条件再设一次就是修改。" + LEVEL_HELP,
    {
        "group": {"type": "string", "enum": list(attention.GROUPS),
                  "description": "哪类事：approval 审批 | mail 邮件 | chat 群聊/私聊里让他做的事和@他 | invitation 会议邀请 | "
                                 "waiting 他在等别人的事 | biz 业务系统通知 | attendance 考勤 | task 飞书任务"},
        "person": {"type": "string", "description": "相关的人（发起人、发件人、提出要求的人、组织者），人名或邮箱"},
        "approval": {"type": "string", "description": "审批类型，例如 请假、报销、采购"},
        "chat": {"type": "string", "description": "群名"},
        "system": {"type": "string", "description": "业务系统名"},
        "level": {"type": "string", "enum": list(attention.LEVELS), "description": LEVEL_HELP},
    },
    ["level"],
    user_initiated_only=True,  # 只有他本人说了才改；定时任务、长期任务不能替他改偏好
)
async def set_notify_rule(ctx: ToolContext, args: dict) -> str:
    match = {k: args[k] for k in attention.MATCH_KEYS if args.get(k)}
    try:
        rule = await attention.set_rule(ctx.session, ctx.user, match, args["level"], "chat")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return f"已设置规则 #{rule.id}：{rule.label}（之后新来的事按这条处理；网页“提醒设置”里能看到和修改）"


@tool("list_notify_rules", "列出用户设过的提醒规则（每条命中过多少件事），以及从他以前的话里整理出、还在等他确认的候选规则。", {}, [])
async def list_notify_rules(ctx: ToolContext, args: dict) -> str:
    rules = await attention.rules_for(ctx.session, ctx.user, status=None)
    active = [r for r in rules if r.status == "active"]
    proposed = [r for r in rules if r.status == "proposed"]
    lines = [f"#{r.id} {r.label}（命中 {r.hits} 件）" for r in active] or [
        "没有生效的提醒规则。默认：紧急的、上级的事立刻说（不受次数限制），今天要处理的立刻说（每小时有上限），其余的攒到汇总时间一起说。"]
    if proposed:
        lines.append("等他确认的候选（确认前不生效；他同意时用 set_notify_rule 按同样条件设置即可）：")
        lines += [f"#{r.id} {r.label}（依据：{r.evidence}）" for r in proposed]
    lines.append("紧急的事即使命中“少提醒”的规则也会照样告诉他。")
    return "\n".join(lines)


@tool("delete_notify_rule", "删除一条提醒规则（用户说那类事又要正常提醒了）。", {"rule_id": {"type": "integer"}}, ["rule_id"],
      user_initiated_only=True)
async def delete_notify_rule(ctx: ToolContext, args: dict) -> str:
    rule = (await ctx.session.execute(
        select(AttentionRule).where(AttentionRule.id == args["rule_id"], AttentionRule.user_id == ctx.user.id)
    )).scalars().first()
    if rule is None:
        raise ToolError(f"没有找到规则 #{args['rule_id']}")
    await ctx.session.delete(rule)
    return f"已删除规则 #{rule.id}：{rule.label}"
