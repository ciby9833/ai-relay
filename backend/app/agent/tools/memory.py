import re

from app.agent.tools.base import ToolContext, ToolError, tool
from app.memory import service

# 密码、密钥、令牌、证件号码这类敏感信息不进长期记忆（规则在代码里，不靠提示词）
SECRET = re.compile(
    r"(密码|口令|password|passwd|api[ _-]?key|secret|token|私钥|验证码)\s*(是|为|:|：|=)"
    r"|\b(sk|pk|ghp|xox[bp])-[A-Za-z0-9_-]{12,}"
    r"|\b\d{16}\b|\b\d{17}[\dXx]\b",  # 印尼 NIK（16 位）、中国身份证（18 位）
    re.IGNORECASE,
)


@tool(
    "remember",
    "把一条信息存入用户的长期记忆，之后的对话都能用上。"
    "profile 用于关于用户的稳定事实（岗位、偏好、长期在做的事）；"
    "episodic 用于某次发生的具体事情（一个决定、一次讨论的结论）。"
    "每条记忆写成一句独立可读的话，不要依赖当前对话的上下文。",
    {
        "content": {"type": "string", "description": "要记住的内容，一句完整的话"},
        "kind": {"type": "string", "enum": list(service.KINDS)},
    },
    ["content", "kind"],
)
async def remember(ctx: ToolContext, args: dict) -> str:
    if not args["content"].strip():
        raise ToolError("content 不能为空", "invalid_input")
    if SECRET.search(args["content"]):
        raise ToolError("这条内容里有密码、密钥或证件号码，不记进长期记忆", "invalid_input")
    memory = await service.add_memory(
        ctx.session, ctx.user.id, args["kind"], args["content"], ctx.conversation.id
    )
    return f"已记住（记忆 #{memory.id}）"


@tool(
    "forget",
    "删除一条长期记忆。用户要求忘掉某件事，或某条记忆已经过时/有误时使用。",
    {"memory_id": {"type": "integer", "description": "记忆编号，即 #后面的数字"}},
    ["memory_id"],
)
async def forget(ctx: ToolContext, args: dict) -> str:
    if not await service.delete_memory(ctx.session, ctx.user.id, args["memory_id"]):
        raise ToolError(f"没有找到记忆 #{args['memory_id']}")
    return f"已删除记忆 #{args['memory_id']}"


@tool(
    "search_memory",
    "按语义搜索用户的长期记忆。上下文里自动带出的记忆不够用时再调用。",
    {"query": {"type": "string", "description": "要找的内容"}},
    ["query"],
)
async def search_memory(ctx: ToolContext, args: dict) -> str:
    memories = await service.search_memories(ctx.session, ctx.user.id, args["query"], limit=8)
    if not memories:
        return "没有找到相关记忆"
    return "\n".join(f"#{m.id} [{m.kind}] {m.content}" for m in memories)
