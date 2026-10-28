"""ledger 服务：python -m app.ledger.runner

为参加评估的用户持续增量计算承诺账本。独立进程：模型慢或出错都不会拖慢现有的提醒（worker）。
"""

import asyncio
import logging

from app.db import SessionLocal
from app.ledger import engine
from app.llm.gemini_provider import GeminiProvider
from app.llm.google import genai_client, keep_fresh
from app.telemetry import ObservedProvider

logger = logging.getLogger("relay.ledger")
POLL_SECONDS = 180


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    refresher = asyncio.create_task(keep_fresh())  # noqa: F841
    provider = ObservedProvider(GeminiProvider(genai_client()))
    logger.info("ledger 服务已启动，每 %s 秒处理一次", POLL_SECONDS)
    while True:
        async with SessionLocal() as session:
            user_ids = [u.id for u in await engine.enrolled_users(session)]
        for user_id in user_ids:
            async with SessionLocal() as session:
                from app.models import User

                user = await session.get(User, user_id)
                try:
                    meter = await engine.advance(session, provider, user)
                    if meter.calls["attach"]:
                        logger.info("%s：归事 %s 次、对账 %s 次、出错 %s 次", user.name, meter.calls["attach"], meter.calls["reconcile"], meter.errors)
                except Exception:
                    logger.exception("计算 %s 的承诺账本失败", user.name)
                    await session.rollback()
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
