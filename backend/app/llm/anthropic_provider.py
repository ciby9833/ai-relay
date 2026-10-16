from collections.abc import AsyncIterator

import anthropic

from app.llm.base import Completion, LLMError, StopReason, TextDelta

# 这些模型的安全分类器可能拒答，开启服务端回退后由 API 自动换模型重跑
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_STOP: dict[str, StopReason] = {
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out = []
    for message in messages:
        if message.get("raw_provider") == "anthropic":
            out.append({"role": "assistant", "content": message["raw"]})
            continue
        content = []
        for block in message["content"]:
            if block["type"] == "text":
                if block["text"]:
                    content.append({"type": "text", "text": block["text"]})
            elif block["type"] == "tool_use":
                content.append(
                    {
                        "type": "tool_use",
                        "id": block["id"],
                        "name": block["name"],
                        "input": block["input"],
                    }
                )
            elif block["type"] == "tool_result":
                result = {
                    "type": "tool_result",
                    "tool_use_id": block["tool_use_id"],
                    "content": block["content"],
                }
                if block.get("is_error"):
                    result["is_error"] = True
                content.append(result)
        if content:
            out.append({"role": message["role"], "content": content})
    return out


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def stream(
        self, *, model: str, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[TextDelta | Completion]:
        params: dict = {
            "model": model,
            "max_tokens": 64000,
            "system": system,
            "messages": to_anthropic_messages(messages),
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            # 开启后工具参数不再由服务端校验，由 agent.tools.execute 用 JSON Schema 校验
            params["tools"] = [{**tool, "eager_input_streaming": True} for tool in tools]
        if model in _FALLBACK_MODELS:
            params["betas"] = [_FALLBACK_BETA]
            params["fallbacks"] = "default"

        try:
            async with self.client.beta.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield TextDelta(event.text)
                final = await stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise LLMError("Claude 触发限流，请稍后再试") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude 接口错误 ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("连接 Claude 失败") from exc
        except ValueError as exc:
            raise LLMError("Claude 返回的工具参数无法解析") from exc

        blocks = []
        for block in final.content:
            if block.type == "text":
                blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                blocks.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
        yield Completion(
            blocks=blocks,
            stop_reason=_STOP.get(final.stop_reason, "end"),
            raw=final.content,
            usage={
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
                "cache_read_input_tokens": final.usage.cache_read_input_tokens,
            },
        )
