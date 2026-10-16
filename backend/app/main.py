import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import assistant, auth, conversations, feishu_events, integrations, missions, proactive
from app.config import get_settings
from app.feishu.client import FeishuClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=30) as http:
        app.state.feishu = FeishuClient(get_settings(), http)
        yield


app = FastAPI(title="Relay", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(assistant.router)
app.include_router(feishu_events.router)
app.include_router(proactive.router)
app.include_router(missions.router)
app.include_router(integrations.router)


@app.get("/api/health")
async def health():
    return {"ok": True}
