"""Gemini 客户端：配置了服务账号就走 Vertex AI，否则用 Gemini API key。"""

import json
import os
from functools import lru_cache

from google import genai

from app.config import get_settings


def _credentials_file() -> str | None:
    path = get_settings().google_application_credentials
    return path if path and os.path.isfile(path) and os.path.getsize(path) > 0 else None


def gemini_configured() -> bool:
    return bool(_credentials_file() or get_settings().gemini_api_key)


@lru_cache
def genai_client() -> genai.Client:
    settings = get_settings()
    path = _credentials_file()
    if path:
        # google-auth 会自己读 GOOGLE_APPLICATION_CREDENTIALS 指向的文件
        with open(path) as f:
            project = settings.google_cloud_project or json.load(f)["project_id"]
        return genai.Client(vertexai=True, project=project, location=settings.google_cloud_location)
    return genai.Client(api_key=settings.gemini_api_key)
