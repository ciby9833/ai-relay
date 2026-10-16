"""主动流程里用到的单次模型调用：判断、起草、写简报。"""

import jsonschema

from app.config import get_settings
from app.llm import registry
from app.llm.base import Completion, LLMError, TextDelta


def _model():
    return registry.resolve(get_settings().triage_model or None)


async def complete_text(system: str, prompt: str) -> str:
    provider, model, _ = _model()
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
