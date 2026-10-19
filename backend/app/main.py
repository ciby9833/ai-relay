import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import assistant, auth, conversations, feishu_events, integrations, missions, proactive
from app import insights
from app.config import get_settings
from app.feishu.client import FeishuClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _upgrade_database() -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not get_settings().is_production:
        # 开发环境热重载只重启 uvicorn，不会重跑容器启动命令里的迁移：拉了新代码后在这里补上
        # （生产环境由容器启动命令执行迁移）。迁移脚本里有 asyncio.run，放到线程里执行。
        await asyncio.to_thread(_upgrade_database)
    async with httpx.AsyncClient(timeout=30) as http:
        app.state.feishu = FeishuClient(get_settings(), http)
        yield


app = FastAPI(title="Relay", lifespan=lifespan)


@app.middleware("http")
async def decision_source(request, call_next):
    # 网页上点按钮做的决定记为 web（对话里说“发吧”由 run_turn 改记为 chat）
    insights.via.set("web")
    return await call_next(request)

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
