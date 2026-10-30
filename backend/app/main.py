import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import assistant, auth, blog, conversations, feishu_events, integrations, missions, proactive
from app import insights
from app.api import collab, connections as connections_api, devices as devices_api, quality, performance, evaluation, workspace, tenant
from app import telemetry
from app.config import get_settings
from app.feishu.client import FeishuClient
from app.llm.google import keep_fresh

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
    # Production's container command migrates first; both environments import the same bundle.
    from app.blog_import import import_bundle
    try:
        await import_bundle()
    except Exception:
        # 文章包有问题不能拖垮助手本身：保留数据库里上一版文章，记日志后照常启动
        logging.getLogger("relay.blog").exception("博客文章导入失败，继续使用数据库中的上一版")
    refresher = asyncio.create_task(keep_fresh())  # Google 访问令牌后台提前刷新
    monitoring = telemetry.start()
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            app.state.feishu = FeishuClient(get_settings(), http)  # 默认工作区（服务器配置的飞书应用）
            app.state.http = http
            try:
                from app import tenancy
                from app.db import SessionLocal

                async with SessionLocal() as session:
                    await tenancy.ensure_default_connection(session)
            except Exception:
                logging.getLogger("relay.tenancy").exception("登记默认工作区的飞书连接失败")
            yield
    finally:
        refresher.cancel()
        await telemetry.stop(monitoring)


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
app.include_router(workspace.router)
app.include_router(tenant.router)
app.include_router(collab.router)
app.include_router(connections_api.router)
app.include_router(devices_api.router)
app.include_router(missions.router)
app.include_router(integrations.router)
app.include_router(blog.router)
app.include_router(quality.router)
app.include_router(performance.router)
app.include_router(evaluation.router)


@app.get("/api/health")
async def health():
    return {"ok": True}
