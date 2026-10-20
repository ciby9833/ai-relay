"""飞书卡片按钮回调。按钮里只带 id，操作对象一律按点击者本人校验归属。

执行完后按最新状态重新渲染这张卡片（原地更新），出错时另发一条消息说明原因。
"""

import asyncio
import time
import json
import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.feishu.client import FeishuClient, FeishuError
from app.llm.base import LLMError
from app.models import FeishuCard, FollowUp, User, ScheduledTask
from app import automation, i18n, insights
from app.proactive.settings import language_of
from app.proactive import actions, items
from app.proactive.push import render

logger = logging.getLogger("relay.callbacks")


async def handle_card_action(
    feishu: FeishuClient, operator_open_id: str, value: dict, message_id: str | None = None
) -> dict | None:
    """执行按钮对应的操作，返回 {"ok", "message", "card"}；card 是按最新状态重新渲染的卡片。

    调用方（长连接）若能在 3 秒内拿到结果，就把新卡片直接放进回调响应；否则再调 deferred_update。
    """
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.feishu_open_id == operator_open_id))
        ).scalars().first()
        if user is None:
            return None
        user_id, open_id = user.id, user.feishu_open_id
        i18n.current.set(await language_of(session, user))
        insights.via.set("feishu_card")
        kind = value.get("relay")
        message, ok = None, True
        try:
            if kind == "draft_reply":
                action = await actions.prepare_mail_reply(session, feishu, user, int(value["signal_id"]))
                await items.link_action(session, user, action)
            elif kind == "rsvp":
                # 在卡片上点“接受/拒绝”本身就是明确的指令，直接执行
                action = await actions.prepare_rsvp(session, user, int(value["signal_id"]), value["status"])
                message = await actions.execute(session, feishu, user, action)
                ok = action.status == "done"
            elif kind == "approval":
                action = await actions.prepare_approval(session, user, int(value["signal_id"]), bool(value["approve"]))
                message = await actions.execute(session, feishu, user, action)
                ok = action.status == "done"
            elif kind == "confirm":
                action = await actions.own_action(session, user, int(value["action_id"]))
                message = await actions.execute(session, feishu, user, action)
                ok = action.status == "done"
            elif kind == "grant":
                # 确认这次，并授权这个定时任务以后直接办同一件事（同一张表 / 同一个人）
                action = await actions.own_action(session, user, int(value["action_id"]))
                message = await actions.execute(session, feishu, user, action)
                ok = action.status == "done"
                if ok and action.scheduled_task_id:
                    task = await session.get(ScheduledTask, action.scheduled_task_id)
                    if task is not None and task.user_id == user.id:
                        label = automation.grant_task(task, action)
                        message = f"{message}。以后《{task.title}》会直接{label}，在网页“自动办的事”里可以随时收回"
                        await insights.record(session, user, "grant", action=action)
            elif kind == "undo":
                action = await actions.own_action(session, user, int(value["action_id"]))
                message = await automation.undo(session, feishu, user, action)
            elif kind == "cancel":
                action = await actions.own_action(session, user, int(value["action_id"]))
                message = actions.cancel(action)
                await insights.record(session, user, "cancel", action=action)
            elif kind == "item_done":
                item = await session.get(FollowUp, int(value["item_id"]))
                if item is None or item.user_id != user.id:
                    raise actions.ActionError("找不到这件事")
                items.close(item, "done", "你标记为已处理")
                await insights.record(session, user, "done", item=item)
            elif kind == "mute":
                message = await actions.mute(session, user, int(value["signal_id"]))
                await insights.record(session, user, "mute", detail={"signal_id": int(value["signal_id"])})
            else:
                return None
            if ok:
                await session.commit()
                await items.advance(session, user)  # 让对应的事项立即反映结果（关闭、转为等对方回复……）
            elif kind in ("confirm", "grant"):
                # 失败/结果未知也必须保存，不能让下一次点击重复外部写入。
                await session.commit()
            else:
                await session.rollback()
        except actions.ActionError as exc:
            message, ok = str(exc), False
            await session.rollback()
        except LLMError as exc:
            message, ok = f"模型调用失败：{exc}", False
            await session.rollback()
        # 回滚后 ORM 对象已失效，重新读取
        user = await session.get(User, user_id)

        card = None
        if message_id:
            record = await session.get(FeishuCard, message_id)
            if record and record.user_id == user.id:
                card, _ = await render(session, user, record.title, record.text, record.sections)
        return {"ok": ok, "message": message, "card": card, "open_id": open_id}


async def deferred_update(feishu: FeishuClient, message_id: str | None, result: dict | None, update_token: str | None = None) -> None:
    """回调已经先响应了“处理中”：再更新卡片，失败时另发消息。

    按飞书文档：更新必须在回调响应之后（不能并行或提前），优先用回调里的 event.token 调延时更新接口
    （30 分钟内有效、最多 2 次），不行再用消息 PATCH。
    """
    if not result:
        return
    await asyncio.sleep(1.0)
    updated = False
    if result["card"] and update_token:
        try:
            await feishu.tenant_api("POST", "/interactive/v1/card/update", json={"token": update_token, "card": result["card"]})
            updated = True
        except FeishuError:
            logger.exception("延时更新卡片失败，改用消息 PATCH")
    if result["card"] and not updated and message_id:
        try:
            await feishu.tenant_api("PATCH", f"/im/v1/messages/{message_id}", json={"content": json.dumps(result["card"], ensure_ascii=False)})
            updated = True
        except FeishuError:
            logger.exception("更新卡片失败")
    if result["message"] and (not result["ok"] or not updated):
        await feishu.send_text(result["open_id"], result["message"])


CALLBACK_WAIT_SECONDS = 2.2  # 不知道路上用了多久时（长连接）最多等这么久
CALLBACK_DEADLINE = 3.0  # 飞书要求从发出回调起 3 秒内响应
SAFETY = 0.6  # 留给回程网络的余量
CARD_LIMIT = 28 * 1024  # 回调响应里的卡片上限约 30KB
_pending: set[asyncio.Task] = set()


async def respond(
    feishu: FeishuClient, operator: str, value: dict, message_id: str | None,
    created_us: int | str | None = None, update_token: str | None = None,
) -> dict:
    """处理一次卡片按钮点击，返回给飞书的回调响应（长连接和 HTTP 回调共用）。

    2.2 秒内做完就把新卡片放进响应；来不及（例如要调模型起草）先回“正在处理”，做完再单独更新卡片。
    """
    started = time.monotonic()
    # 飞书从发出回调起算 3 秒：卡片回调走的是飞书海外节点，到这里路上可能已经用掉 2 秒。
    # 按发出时间（header.create_time，微秒）算还剩多少，留出余量；来不及就先回“正在处理”，做完再更新卡片。
    lag = None
    if created_us:
        try:
            lag = max(0.0, time.time() - int(created_us) / 1_000_000)
        except (TypeError, ValueError):
            lag = None
    wait = CALLBACK_WAIT_SECONDS if lag is None else max(0.0, min(CALLBACK_WAIT_SECONDS, CALLBACK_DEADLINE - SAFETY - lag))
    logger.info("收到卡片回调 operator=%s relay=%s message=%s 路上用时=%s 可等=%.1fs", operator, value.get("relay"), message_id,
                f"{lag:.1f}s" if lag is not None else "未知", wait)
    task = asyncio.ensure_future(handle_card_action(feishu, operator, value, message_id))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    try:
        result = await asyncio.wait_for(asyncio.shield(task), wait)
    except TimeoutError:
        logger.info("卡片回调 %.1fs 内没处理完，先回 toast，处理完再更新卡片", time.monotonic() - started)
        token = update_token

        def later(done: asyncio.Task) -> None:
            if done.cancelled() or done.exception():
                logger.error("卡片按钮处理失败", exc_info=done.exception())
                return
            follow = asyncio.ensure_future(deferred_update(feishu, message_id, done.result(), token))
            _pending.add(follow)
            follow.add_done_callback(_pending.discard)

        task.add_done_callback(later)
        return {"toast": {"type": "info", "content": "收到，正在处理…"}}
    except Exception:
        logger.exception("处理卡片按钮失败")
        return {"toast": {"type": "error", "content": "处理失败，请稍后再试"}}
    if result is None:
        logger.warning("卡片回调没有对应的用户或操作 operator=%s relay=%s", operator, value.get("relay"))
        return {}
    response: dict = {"toast": {"type": "success" if result["ok"] else "error", "content": (result["message"] or "已处理")[:60]}}
    if result["card"]:
        if len(json.dumps(result["card"], ensure_ascii=False).encode()) <= CARD_LIMIT:
            response["card"] = {"type": "raw", "data": result["card"]}
        else:
            # 卡片太大放不进回调响应（飞书会报 200671）：只回 toast，再单独更新卡片
            follow = asyncio.ensure_future(deferred_update(feishu, message_id, result, update_token))
            _pending.add(follow)
            follow.add_done_callback(_pending.discard)
    if not result["ok"] and result["message"] and len(result["message"]) > 60:
        follow = asyncio.ensure_future(feishu.send_text(result["open_id"], result["message"]))  # 原因较长时另发完整说明
        _pending.add(follow)
        follow.add_done_callback(_pending.discard)
    logger.info("卡片回调处理完 %.1fs ok=%s card=%s", time.monotonic() - started, result["ok"], "card" in response)
    return response
