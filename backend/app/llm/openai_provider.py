import json
from collections.abc import AsyncIterator

import openai

from app.llm.base import Completion, LLMError, StopReason, TextDelta


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for message in messages:
        blocks = message["content"]
        text = "\n\n".join(b["text"] for b in blocks if b["type"] == "text" and b["text"])
        if message["role"] == "assistant":
            entry: dict = {"role": "assistant", "content": text or None}
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {
                        "name": b["name"],
                        "arguments": json.dumps(b["input"], ensure_ascii=False),
                    },
                }
                for b in blocks
                if b["type"] == "tool_use"
            ]
            if calls:
                entry["tool_calls"] = calls
            if text or calls:
                out.append(entry)
            continue
        # 工具结果必须紧跟在发起调用的助手消息之后
        for block in blocks:
            if block["type"] == "tool_result":
                out.append(
                    {"role": "tool", "tool_call_id": block["tool_use_id"], "content": block["content"]}
                )
        if text:
            out.append({"role": "user", "content": text})
    return out


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def stream(
        self, *, model: str, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[TextDelta | Completion]:
        params: dict = {
            "model": model,
            "messages": to_openai_messages(system, messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
                for tool in tools
            ]

        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        finish = None
        usage: dict = {}
        try:
            stream = await self.client.chat.completions.create(**params)
            async for chunk in stream:
                if chunk.usage:
                    usage = {
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                    }
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    text_parts.append(delta.content)
                    yield TextDelta(delta.content)
                for call in (delta.tool_calls or []) if delta else []:
                    slot = calls.setdefault(call.index, {"id": "", "name": "", "arguments": ""})
                    if call.id:
                        slot["id"] = call.id
                    if call.function and call.function.name:
                        slot["name"] = call.function.name
                    if call.function and call.function.arguments:
                        slot["arguments"] += call.function.arguments
                if choice.finish_reason:
                    finish = choice.finish_reason
        except openai.RateLimitError as exc:
            raise LLMError("OpenAI 触发限流，请稍后再试") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"OpenAI 接口错误 ({exc.status_code}): {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("连接 OpenAI 失败") from exc

        stop_reason: StopReason = "end"
        if finish == "length":
            stop_reason = "max_tokens"
        elif finish == "content_filter":
            stop_reason = "refusal"
        elif calls:
            stop_reason = "tool_use"

        blocks: list[dict] = []
        if text_parts:
            blocks.append({"type": "text", "text": "".join(text_parts)})
        for index in sorted(calls):
            call = calls[index]
            try:
                arguments = json.loads(call["arguments"] or "{}")
            except ValueError:
                # 交给工具层的 schema 校验报错，让模型自己修正
                arguments = {"_invalid_json": call["arguments"]}
            blocks.append(
                {"type": "tool_use", "id": call["id"], "name": call["name"], "input": arguments}
            )
        yield Completion(blocks=blocks, stop_reason=stop_reason, usage=usage)
