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
from app import filejobs
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
from app import locks, telemetry

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


USER_TIMEOUT = 15 * 60  # 一个用户的主流程最多跑这么久，超时就放下，不拖住别人
CHAT_SECONDS = 20  # 聊天提取的间隔；有积压时不等，接着处理


async def run_user(feishu: FeishuClient, user_id) -> str:
    """跑一个用户的主流程（同步、分级、跟进、告诉他）。持有这个用户的锁：同一时间只有一处在改他的事项。"""
    async with locks.hold_user(user_id) as got:
        if not got:
            return "busy"  # 上一轮的还没跑完（或聊天提取正在处理他的消息）
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            if user is None:
                return "gone"
            try:
                with telemetry.work("user"):
                    await asyncio.wait_for(run_for_user(session, feishu, user), USER_TIMEOUT)
                return "ok"
            except asyncio.TimeoutError:
                logger.error("用户 %s 的主流程超过 %s 秒，先放下，下一轮再来", user_id, USER_TIMEOUT)
                return "timeout"
            except Exception:
                logger.exception("用户 %s 的主流程失败", user_id)
                return "error"


async def run_users(feishu: FeishuClient, concurrency: int) -> dict:
    """所有用户并行跑（同时最多 concurrency 个），一个慢或卡住的用户不影响别人。返回各种结果的计数。"""
    async with SessionLocal() as session:
        user_ids = list((await session.execute(select(User.id))).scalars())
    gate = asyncio.Semaphore(concurrency)

    async def one(user_id):
        async with gate:
            return await run_user(feishu, user_id)

    outcomes = await asyncio.gather(*(one(u) for u in user_ids))
    return {k: outcomes.count(k) for k in set(outcomes)}


async def users_loop(feishu: FeishuClient) -> None:
    concurrency = max(1, get_settings().worker_concurrency)
    while True:
        started = asyncio.get_running_loop().time()
        try:
            counts = await run_users(feishu, concurrency)
            logger.info("一轮用户主流程完成，用时 %.0f 秒：%s", asyncio.get_running_loop().time() - started, counts)
            telemetry.cycle_completed()
        except Exception:
            logger.exception("用户主流程这一轮失败")
        await asyncio.sleep(POLL_SECONDS)


async def chats_loop(feishu: FeishuClient) -> None:
    """聊天内容提取单独一个循环：不等用户主流程，新消息几十秒内就能处理；有积压时连着处理。"""
    concurrency = max(1, get_settings().chat_concurrency)
    while True:
        handled = 0
        try:
            with telemetry.work("chats"):
                handled = await chats.extract_parallel(feishu, concurrency)
        except Exception:
            logger.exception("提取聊天内容失败")
        await asyncio.sleep(1 if handled else CHAT_SECONDS)


async def tasks_loop(feishu: FeishuClient) -> None:
    """定时任务、生成文件、长期任务：各自独立，不被用户主流程拖住。"""
    while True:
        try:
            for task_id in await claim_due_tasks():
                try:
                    with telemetry.work("scheduled"):
                        await run_task(task_id, feishu)
                    logger.info("任务 #%s 执行完成", task_id)
                except Exception:
                    logger.exception("任务 #%s 执行失败", task_id)
        except Exception:
            logger.exception("检查定时任务失败")
        try:
            await filejobs.run_pending(feishu)  # 没做完的生成文件 / 存云空间任务（含重启前中断的）
        except Exception:
            logger.exception("处理文件任务失败")
        try:
            async with SessionLocal() as session:
                await mission_service.run_due(session, feishu)
        except Exception:
            logger.exception("推进长期任务失败")
        await asyncio.sleep(POLL_SECONDS)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=50)) as http:
        feishu = FeishuClient(get_settings(), http)
        logger.info("worker 已启动：用户并行 %s 个，聊天提取并行 %s 个", get_settings().worker_concurrency, get_settings().chat_concurrency)
        telemetry.start()
        refresher = asyncio.create_task(keep_fresh())  # Google 访问令牌后台提前刷新  # noqa: F841
        # 三个循环各自独立：一个慢不会拖住另外两个；任何一个意外退出都让进程退出，由容器重启
        await asyncio.gather(users_loop(feishu), chats_loop(feishu), tasks_loop(feishu))


if __name__ == "__main__":
    asyncio.run(main())
