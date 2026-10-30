"""工具注册与执行。新增工具：在本包里写一个带 @tool 的函数，并在 __init__.py 里导入。"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import jsonschema
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
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
    # 在定时任务里运行时，当前定时任务（判断这类操作是否已获授权直接办）
    task: object | None = None
    # 工具要求这一轮到此结束（长期任务决定了接下来等什么）
    stop_turn: bool = False
    # 这一轮里查找类工具调用过的参数（超过次数返回 limit）、最近一次出错的错误码（给界面显示）
    searches: dict = field(default_factory=dict)
    last_error: str | None = None


class ToolError(Exception):
    """可以原样告诉模型的失败原因。code 是统一错误码（见 app/connectors/errors.py）；不给时按根因判断。"""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code


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


def envelope(name: str, effect: str, output, cards: list[dict]) -> dict:
    """成功时的统一结果：哪个工具、副作用等级、结果（工具返回 JSON 时是结构化数据，否则是文字），
    以及这一步准备了哪些待确认操作、产出了哪些文件（从卡片里取，不靠模型从文字里读）。"""
    result = output
    if isinstance(output, str) and output[:1] in "[{":
        try:
            result = json.loads(output)
        except ValueError:
            result = output
    out = {"ok": True, "tool": name, "effect": effect, "result": result}
    pending = [c["action_id"] for c in cards if c.get("kind") == "action" and c.get("action_id")]
    items = [c["item_id"] for c in cards if c.get("kind") == "item" and c.get("item_id")]
    files = [c["file_id"] for c in cards if c.get("kind") == "file" and c.get("file_id")]
    if effect == "prepare":
        out["needs_confirmation"] = True  # 只准备了，本人确认后才执行
    if pending:
        out["pending_action_ids"] = pending
    if items:
        out["item_ids"] = items
    if files:
        out["file_ids"] = files
    return out


def _description(t: Tool) -> str:
    """工具说明 + 连接器清单里的使用约定和副作用（准备的操作要本人确认才执行）。"""
    from app.connectors import catalog

    contract = catalog.CONTRACTS.get(t.name)
    if contract is None:
        return t.description
    extra = [contract.usage] if contract.usage else []
    if contract.effect == "prepare":
        extra.append("只准备，本人确认后才执行；没执行不能说已经做了。")
    return " ".join([t.description, *extra])


def tool_specs(user_initiated: bool = True, channel: str | None = None) -> list[dict]:
    # 按名称排序，保证同一渠道每次请求的工具列表字节一致（利于提示词缓存）
    return [
        {"name": t.name, "description": _description(t), "input_schema": t.input_schema}
        for t in sorted(TOOLS.values(), key=lambda t: t.name)
        if _available(t, user_initiated, channel)
    ]


async def execute(
    ctx: ToolContext, name: str, arguments: dict, user_initiated: bool = True
) -> tuple[str, bool]:
    """执行一次工具调用，返回 (结果文本, 是否出错)。失败不会污染外层事务。

    按连接器清单（app/connectors/catalog.py）检查：没有登记的工具不执行；write（执行已确认的操作）只在本人发起的轮次里；
    查找类工具每轮有次数上限。出错时返回统一错误码和“该谁处理”。
    """
    from app.connectors import catalog, errors

    ctx.last_error = None

    def fail(code: str, message: str) -> tuple[str, bool]:
        ctx.last_error = code
        return json.dumps(errors.error_result(name, code, message), ensure_ascii=False), True

    spec = TOOLS.get(name)
    contract = catalog.CONTRACTS.get(name)
    if spec is None or contract is None or not _available(spec, user_initiated, getattr(ctx.conversation, "channel", None)):
        return fail("unsupported", f"没有名为 {name} 的工具")
    if contract.effect == "write" and not user_initiated:
        return fail("precondition", "执行已准备的操作只能由本人在对话里确认")
    try:
        jsonschema.validate(arguments, spec.input_schema)
    except jsonschema.ValidationError as exc:
        return fail("invalid_input", f"参数不合法: {exc.message}")
    if name in catalog.SEARCH_TOOLS:
        done = ctx.searches.setdefault(name, [])
        if len(done) >= catalog.SEARCH_LIMIT:
            tried = "；".join(str(a.get("query") or a.get("keyword") or a) for a in done)
            return fail("limit", f"这一轮已经用 {name} 查了 {len(done)} 次（{tried}）")
        done.append(arguments)
    cards_before = len(ctx.cards)
    try:
        async with ctx.session.begin_nested():
            output = await spec.handler(ctx, arguments)
        return json.dumps(envelope(name, contract.effect, output, ctx.cards[cards_before:]), ensure_ascii=False), False
    except ToolError as exc:
        return fail(errors.classify(exc), str(exc))
    except FeishuError as exc:  # 工具没有自己处理的飞书错误：按根因归类，不再一律当作内部错误
        return fail(errors.classify(exc), str(exc))
    except Exception:
        logger.exception("工具 %s 执行失败", name)
        return fail("internal", "工具执行时发生内部错误")
