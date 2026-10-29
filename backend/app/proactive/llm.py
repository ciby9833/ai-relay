"""主动流程里用到的单次模型调用：判断、起草、写简报。"""

import jsonschema

from app.config import get_settings
from app.llm import registry
from app.llm.base import Completion, LLMError, TextDelta


def _model():
    return registry.resolve(get_settings().triage_model or None)


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
    parts = []
    async for event in provider.stream(
        model=model, system=system,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}], tools=[],
    ):
        if isinstance(event, TextDelta):
            parts.append(event.text)
    return "".join(parts).strip()


async def complete_structured(system: str, prompt: str, tool: dict) -> dict:
    """让模型调用唯一的工具来给出结构化结果（不依赖各家不同的 JSON 模式）。"""
    provider, model, _ = _model()
    completion: Completion | None = None
    async for event in provider.stream(
        model=model, system=system,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}], tools=[tool],
    ):
        if isinstance(event, Completion):
            completion = event
    for block in (completion.blocks if completion else []):
        if block["type"] == "tool_use" and block["name"] == tool["name"]:
            jsonschema.validate(block["input"], tool["input_schema"])
            return block["input"]
    raise LLMError("模型没有给出结构化结果")
