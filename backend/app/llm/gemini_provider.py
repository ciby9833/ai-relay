import asyncio
import base64
import uuid
from collections.abc import AsyncIterator

from google import genai
from google.genai import errors, types

from app.llm.base import Completion, LLMError, StopReason, TextDelta


SKIP_SIGNATURE = b"skip_thought_signature_validator"
STREAM_TIMEOUT = 120  # 秒


def to_gemini_contents(messages: list[dict]) -> list[types.Content]:
    out = []
    for message in messages:
        if message.get("raw_provider") == "gemini":
            out.append(message["raw"])
            continue
        parts = []
        for block in message["content"]:
            if block["type"] == "text":
                if block["text"]:
                    parts.append(types.Part(text=block["text"]))
            elif block["type"] == "tool_use":
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(name=block["name"], args=block["input"]),
                        # Gemini 3 校验历史里函数调用的思考签名：存了就原样带回；没有（旧记录、换过模型）
                        # 用官方给的占位签名，否则整段历史会被 400 拒绝（长期任务跨多次醒来时必然遇到）
                        thought_signature=base64.b64decode(block["signature"]) if block.get("signature") else SKIP_SIGNATURE,
                    )
                )
            elif block["type"] == "tool_result":
                key = "error" if block.get("is_error") else "result"
                parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=block["name"], response={key: block["content"]}
                        )
                    )
                )
        if parts:
            role = "model" if message["role"] == "assistant" else "user"
            out.append(types.Content(role=role, parts=parts))
    return out


class GeminiProvider:
    name = "gemini"

    def __init__(self, client: genai.Client):
        self.client = client

    async def stream(
        self, *, model: str, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[TextDelta | Completion]:
        config = types.GenerateContentConfig(system_instruction=system)
        if tools:
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool["name"],
                            description=tool["description"],
                            parameters_json_schema=tool["input_schema"],
                        )
                        for tool in tools
                    ]
                )
            ]

        # 原始 parts 里带思考签名，同一轮内回传时必须原样带上
        raw_parts: list[types.Part] = []
        blocks: list[dict] = []
        text_parts: list[str] = []
        finish = None
        usage: dict = {}
        from app.llm.google import ensure_fresh

        await ensure_fresh()  # 令牌快过期才当场换（正常由后台提前换好）
        try:
            # 请求偶尔会卡住不返回（鉴权、网络）：设上限，超时按模型错误处理，调用方会重试或告诉用户
            async with asyncio.timeout(STREAM_TIMEOUT):
                stream = await self.client.aio.models.generate_content_stream(
                    model=model, contents=to_gemini_contents(messages), config=config
                )
                async for chunk in stream:
                    if chunk.usage_metadata:
                        usage = {
                            "input_tokens": chunk.usage_metadata.prompt_token_count,
                            "output_tokens": chunk.usage_metadata.candidates_token_count,
                        }
                    if not chunk.candidates:
                        continue
                    candidate = chunk.candidates[0]
                    if candidate.finish_reason:
                        finish = candidate.finish_reason
                    for part in (candidate.content.parts or []) if candidate.content else []:
                        raw_parts.append(part)
                        if part.function_call:
                            call = part.function_call
                            blocks.append(
                                {
                                    "type": "tool_use",
                                    "id": call.id or f"call_{uuid.uuid4().hex[:24]}",
                                    "name": call.name,
                                    "input": dict(call.args or {}),
                                    **({"signature": base64.b64encode(part.thought_signature).decode()} if part.thought_signature else {}),
                                }
                            )
                        elif part.text and not part.thought:
                            text_parts.append(part.text)
                            yield TextDelta(part.text)
        except TimeoutError as exc:
            raise LLMError(f"Gemini 响应超时（{STREAM_TIMEOUT} 秒）") from exc
        except errors.APIError as exc:
            raise LLMError(f"Gemini 接口错误 ({exc.code}): {exc.message}") from exc

        if text_parts:
            blocks.insert(0, {"type": "text", "text": "".join(text_parts)})

        stop_reason: StopReason = "end"
        if any(block["type"] == "tool_use" for block in blocks):
            stop_reason = "tool_use"
        elif finish == types.FinishReason.MAX_TOKENS:
            stop_reason = "max_tokens"
        elif finish not in (None, types.FinishReason.STOP):
            stop_reason = "refusal"

        yield Completion(
            blocks=blocks,
            stop_reason=stop_reason,
            raw=types.Content(role="model", parts=raw_parts),
            usage=usage,
        )
