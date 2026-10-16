"""模型供应商的统一接口。

消息用与供应商无关的内容块表示，各适配器负责互转：
    {"type": "text", "text": ...}
    {"type": "tool_use", "id": ..., "name": ..., "input": {...}}
    {"type": "tool_result", "tool_use_id": ..., "name": ..., "content": str, "is_error": bool}

同一轮工具循环内，助手消息还会带上 raw（供应商原始输出）和 raw_provider。
原始输出里有思考块/签名，回传给同一家供应商时必须原样带上；它不入库，
跨轮次的历史只保留上面三种中立内容块。
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

StopReason = Literal["end", "tool_use", "max_tokens", "refusal"]


@dataclass
class TextDelta:
    text: str


@dataclass
class Completion:
    blocks: list[dict]
    stop_reason: StopReason
    raw: Any = None
    usage: dict = field(default_factory=dict)


class LLMError(Exception):
    pass


class Provider(Protocol):
    name: str

    def stream(
        self, *, model: str, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[TextDelta | Completion]:
        """流式生成：先产出若干 TextDelta，最后产出一个 Completion。

        tools 的每一项是 {"name", "description", "input_schema"}。
        """
        ...
