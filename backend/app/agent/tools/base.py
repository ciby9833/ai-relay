"""工具注册与执行。新增工具：在本包里写一个带 @tool 的函数，并在 __init__.py 里导入。"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import jsonschema
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient
from app.models import Conversation, User

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    session: AsyncSession
    user: User
    conversation: Conversation
    feishu: FeishuClient
    # 工具可以往这里放卡片，随回复一起展示（日程、邮件、草稿……）
    cards: list[dict] = field(default_factory=list)
    # 在长期任务里运行时，当前任务（工具据此关联操作、判断是否已获授权）
    mission: object | None = None
    # 工具要求这一轮到此结束（长期任务决定了接下来等什么）
    stop_turn: bool = False


class ToolError(Exception):
    """可以原样告诉模型的失败原因。"""


Handler = Callable[[ToolContext, dict], Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Handler
    # 只在用户本人发起的对话轮次里提供（例如确认发送）；定时任务等无人值守的轮次里不出现
    user_initiated_only: bool = False
    # 只在这些对话渠道里提供；None 表示所有渠道
    channels: frozenset[str] | None = None


TOOLS: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    properties: dict,
    required: list[str] | None = None,
    *,
    user_initiated_only: bool = False,
    channels: set[str] | None = None,
):
    def register(handler: Handler) -> Handler:
        TOOLS[name] = Tool(
            name=name,
            description=description,
            input_schema={
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
            handler=handler,
            user_initiated_only=user_initiated_only,
            channels=frozenset(channels) if channels else None,
        )
        return handler

    return register


def _available(t: Tool, user_initiated: bool, channel: str | None) -> bool:
    return (user_initiated or not t.user_initiated_only) and (t.channels is None or channel in t.channels)


def tool_specs(user_initiated: bool = True, channel: str | None = None) -> list[dict]:
    # 按名称排序，保证同一渠道每次请求的工具列表字节一致（利于提示词缓存）
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in sorted(TOOLS.values(), key=lambda t: t.name)
        if _available(t, user_initiated, channel)
    ]


async def execute(
    ctx: ToolContext, name: str, arguments: dict, user_initiated: bool = True
) -> tuple[str, bool]:
    """执行一次工具调用，返回 (结果文本, 是否出错)。失败不会污染外层事务。"""
    spec = TOOLS.get(name)
    if spec is None or not _available(spec, user_initiated, ctx.conversation.channel):
        return f"没有名为 {name} 的工具", True
    try:
        jsonschema.validate(arguments, spec.input_schema)
    except jsonschema.ValidationError as exc:
        return f"参数不合法: {exc.message}", True
    try:
        async with ctx.session.begin_nested():
            return await spec.handler(ctx, arguments), False
    except ToolError as exc:
        return str(exc), True
    except Exception:
        logger.exception("工具 %s 执行失败", name)
        return "工具执行时发生内部错误", True
