"""按 .env 里配置的 API key 启用模型供应商。模型统一写成 provider:model。"""

from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMError, Provider
from app.llm.google import gemini_configured, genai_client


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def _providers() -> dict[str, tuple[Provider, list[str]]]:
    settings = get_settings()
    providers: dict[str, tuple[Provider, list[str]]] = {}
    if settings.anthropic_api_key:
        from app.llm.anthropic_provider import AnthropicProvider

        providers["anthropic"] = (
            AnthropicProvider(settings.anthropic_api_key),
            _split(settings.anthropic_models),
        )
    if settings.openai_api_key:
        from app.llm.openai_provider import OpenAIProvider

        providers["openai"] = (OpenAIProvider(settings.openai_api_key), _split(settings.openai_models))
    if gemini_configured():
        from app.llm.gemini_provider import GeminiProvider

        providers["gemini"] = (GeminiProvider(genai_client()), _split(settings.gemini_models))
    from app.telemetry import ObservedProvider

    return {name: (ObservedProvider(provider), models) for name, (provider, models) in providers.items()}


def available_models() -> list[str]:
    return [f"{name}:{model}" for name, (_, models) in _providers().items() for model in models]


def default_model() -> str:
    models = available_models()
    if not models:
        raise LLMError("还没有配置任何模型的 API key")
    configured = get_settings().default_model
    # 也接受不带 provider 前缀的写法，例如 DEFAULT_MODEL=gemini-4-argon
    matches = [m for m in models if configured in (m, m.split(":", 1)[1])]
    return matches[0] if configured and matches else models[0]


def resolve(model_id: str | None) -> tuple[Provider, str, str]:
    """返回 (供应商, 模型名, 规范化的 provider:model)。不在白名单里的一律回落到默认模型。"""
    model_id = model_id if model_id in available_models() else default_model()
    provider_name, model = model_id.split(":", 1)
    return _providers()[provider_name][0], model, model_id
