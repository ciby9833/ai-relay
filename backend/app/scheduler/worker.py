"""定时任务执行进程：python -m app.scheduler.worker

到点的任务以“系统发起的一轮对话”进入同一个 Agent 循环，结果通过飞书私聊推给用户，
同时在网页端留下一条 task 渠道的会话。
"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.agent.loop import run_turn_text
from app.config import get_settings
from app.db import SessionLocal
from app.feishu.client import FeishuClient, FeishuError
from app.llm.base import LLMError
from app.llm.google import keep_fresh
from app.models import Conversation, PendingAction, ScheduledTask, User
from app.missions import service as mission_service
from app.proactive import chats
from app.proactive.engine import run_for_user
from app.proactive.push import push
from app.scheduler.schedule import next_cron_run

logger = logging.getLogger("relay.worker")

POLL_SECONDS = 30
BATCH = 10


async def claim_due_tasks() -> list[int]:
    """取出到点的任务并立刻推进下次执行时间。

    先推进再执行：进程中途崩溃时最多漏掉一次，不会重复推送。
    """
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        result = await session.execute(
            select(ScheduledTask)
            .where(ScheduledTask.enabled, ScheduledTask.next_run_at <= now)
            .order_by(ScheduledTask.next_run_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
        tasks = list(result.scalars())
        for task in tasks:
            task.last_run_at = now
            if task.cron:
                task.next_run_at = next_cron_run(task.cron, task.timezone, now)
            else:
                task.enabled = False
                task.next_run_at = None
        await session.commit()
        return [task.id for task in tasks]


async def run_task(task_id: int, feishu: FeishuClient) -> None:
    async with SessionLocal() as session:
        task = await session.get(ScheduledTask, task_id)
        if task is None:
            return
        user = await session.get(User, task.user_id)
        result = await session.execute(
            select(Conversation).where(
                Conversation.user_id == user.id,
                Conversation.channel == "task",
                Conversation.external_id == str(task.id),
            )
        )
        conversation = result.scalars().first()
        if conversation is None:
            conversation = Conversation(
                user_id=user.id, channel="task", external_id=str(task.id), title=task.title
            )
            session.add(conversation)
        await session.commit()

        started = datetime.now(UTC)
        try:
            reply = await run_turn_text(
                session,
                user=user,
                conversation=conversation,
                text=f"[定时任务：{task.title}]\n{task.prompt}",
                feishu=feishu,
                task=task,
            )
        except LLMError as exc:
            reply = f"执行失败：{exc}"
        title, open_id = task.title, user.feishu_open_id
        # 这次准备的（等他确认，可以顺带授权以后直接办）和按授权直接办的（可以撤销）都要让他看到
        prepared = (await session.execute(
            select(PendingAction).where(PendingAction.scheduled_task_id == task.id, PendingAction.created_at >= started)
            .order_by(PendingAction.id)
        )).scalars().all()
        if prepared:
            try:
                await push(session, feishu, user, f"⏰ {title}", reply or "", [{"kind": "action", "action_id": a.id} for a in prepared])
                await session.commit()
                return
            except FeishuError:
                logger.exception("定时任务推送卡片失败")

    if reply:
        await feishu.send_text(open_id, f"**⏰ {title}**\n\n{reply}")


async def run_proactive(feishu: FeishuClient) -> None:
    """先从群聊里提取待办，再对每个用户跑一遍：同步数据源、分级、跟进、告诉用户。"""
    try:
        async with SessionLocal() as session:
            await chats.extract(session, feishu)
    except Exception:
        logger.exception("提取群聊待办失败")
    try:
        async with SessionLocal() as session:
            await mission_service.run_due(session, feishu)
    except Exception:
        logger.exception("推进长期任务失败")
    async with SessionLocal() as session:
        user_ids = list((await session.execute(select(User.id))).scalars())
    for user_id in user_ids:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            try:
                await run_for_user(session, feishu, user)
            except Exception:
                logger.exception("用户 %s 的主动流程失败", user_id)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    async with httpx.AsyncClient(timeout=30) as http:
        feishu = FeishuClient(get_settings(), http)
        logger.info("worker 已启动，每 %s 秒检查一次", POLL_SECONDS)
        refresher = asyncio.create_task(keep_fresh())  # Google 访问令牌后台提前刷新  # noqa: F841
        while True:
            try:
                for task_id in await claim_due_tasks():
                    try:
                        await run_task(task_id, feishu)
                        logger.info("任务 #%s 执行完成", task_id)
                    except Exception:
                        logger.exception("任务 #%s 执行失败", task_id)
            except Exception:
                logger.exception("检查定时任务失败")
            await run_proactive(feishu)
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
