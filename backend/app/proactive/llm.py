"""主动流程里用到的单次模型调用：判断、起草、写简报。

worker 里多个用户、多个会话并行跑：同一进程里同时在等模型的调用不超过 MODEL_CONCURRENCY 个；
遇到限流（429 / 配额用完）退避重试几次，而不是直接失败（失败的那一步会被跳过或下一轮重做）。
"""

import asyncio
import random

import jsonschema

from app.config import get_settings
from app.llm import registry
from app.llm.base import Completion, LLMError, TextDelta


def _model():
    return registry.resolve(get_settings().triage_model or None)


MODEL_CONCURRENCY = 4
RETRIES = 3
_gates: dict[int, asyncio.Semaphore] = {}


def _limit() -> asyncio.Semaphore:
    """每个事件循环一个（测试里每个用例是新的事件循环）。"""
    loop = id(asyncio.get_running_loop())
    if loop not in _gates:
        _gates.clear()
        _gates[loop] = asyncio.Semaphore(MODEL_CONCURRENCY)
    return _gates[loop]


def _rate_limited(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "rate limit" in text.lower() or "quota" in text.lower()


async def _with_retry(call):
    for attempt in range(RETRIES + 1):
        try:
            async with _limit():
                return await call()
        except Exception as exc:  # noqa: BLE001 - 只对限流重试，其余原样抛出
            if attempt == RETRIES or not _rate_limited(exc):
                raise
            await asyncio.sleep(2 ** (attempt + 1) + random.random())


def _light():
    """量大但简单的活（附件、文件提取要点）用轻量模型，省时间和额度。"""
    from app.llm.google import gemini_configured

    name = get_settings().light_model or ("gemini-3.5-flash-lite" if gemini_configured() else "")
    if name and gemini_configured():
        from app.llm.gemini_provider import GeminiProvider
        from app.llm.google import genai_client
        from app.telemetry import ObservedProvider

        return ObservedProvider(GeminiProvider(genai_client())), name.split(":")[-1], name
    return _model()


async def complete_text(system: str, prompt: str, light: bool = False) -> str:
    provider, model, _ = _light() if light else _model()

    async def call() -> str:
        parts = []
        async for event in provider.stream(
            model=model, system=system,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}], tools=[],
        ):
            if isinstance(event, TextDelta):
                parts.append(event.text)
        return "".join(parts).strip()

    return await _with_retry(call)


async def complete_structured(system: str, prompt: str, tool: dict) -> dict:
    """让模型调用唯一的工具来给出结构化结果（不依赖各家不同的 JSON 模式）。"""
    provider, model, _ = _model()

    async def call() -> Completion | None:
        completion: Completion | None = None
        async for event in provider.stream(
            model=model, system=system,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}], tools=[tool],
        ):
            if isinstance(event, Completion):
                completion = event
        return completion

    completion = await _with_retry(call)
    for block in (completion.blocks if completion else []):
        if block["type"] == "tool_use" and block["name"] == tool["name"]:
            jsonschema.validate(block["input"], tool["input_schema"])
            return block["input"]
    raise LLMError("模型没有给出结构化结果")
