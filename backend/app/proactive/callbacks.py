"""飞书卡片按钮回调。按钮里只带 id，操作对象一律按点击者本人校验归属。

执行完后按最新状态重新渲染这张卡片（原地更新），出错时另发一条消息说明原因。
"""

import asyncio
import json
import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.feishu.client import FeishuClient, FeishuError
from app.llm.base import LLMError
from app.models import FeishuCard, FollowUp, User
from app import i18n, insights
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
            elif kind == "confirm":
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


async def deferred_update(feishu: FeishuClient, message_id: str | None, result: dict | None) -> None:
    """回调已经先响应了“处理中”：等一会儿再更新卡片（飞书要求延时更新必须在响应回调之后），失败时另发消息。"""
    if not result:
        return
    await asyncio.sleep(1.5)
    if message_id and result["card"]:
        try:
            await feishu.tenant_api("PATCH", f"/im/v1/messages/{message_id}", json={"content": json.dumps(result["card"], ensure_ascii=False)})
        except FeishuError:
            logger.exception("更新卡片失败")
            result["card"] = None
    if result["message"] and (not result["ok"] or not result["card"]):
        await feishu.send_text(result["open_id"], result["message"])
