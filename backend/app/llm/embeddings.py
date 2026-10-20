"""记忆向量化。Claude 没有 embedding 接口，所以只在 OpenAI / Gemini 里选。"""

import logging
from functools import lru_cache

from app.config import get_settings
from app.llm.google import gemini_configured, genai_client
from app.models import EMBEDDING_DIM

logger = logging.getLogger(__name__)


@lru_cache
def embedding_model() -> str | None:
    """当前使用的 provider:model；没有可用的供应商时返回 None。"""
    settings = get_settings()
    if settings.embedding_model:
        return settings.embedding_model
    if settings.openai_api_key:
        return "openai:text-embedding-3-small"
    if gemini_configured():
        return "gemini:gemini-embedding-001"
    return None


@lru_cache
def _openai_client():
    import openai

    return openai.AsyncOpenAI(api_key=get_settings().openai_api_key)




async def embed(text: str) -> list[float] | None:
    """失败时返回 None，调用方退化为不做语义检索。"""
    model_id = embedding_model()
    if not model_id:
        return None
    if ":" not in model_id:
        logger.warning("EMBEDDING_MODEL 需要写成 provider:model，当前是 %s", model_id)
        return None
    provider, model = model_id.split(":", 1)
    try:
        if provider == "openai":
            response = await _openai_client().embeddings.create(
                model=model, input=text, dimensions=EMBEDDING_DIM
            )
            return response.data[0].embedding
        if provider == "gemini":
            from google.genai import types

            from app.llm.google import ensure_fresh

            await ensure_fresh()
            response = await genai_client().aio.models.embed_content(
                model=model,
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
            )
            return list(response.embeddings[0].values)
        logger.warning("不支持的 embedding 供应商: %s", provider)
    except Exception:
        logger.exception("生成 embedding 失败")
    return None
