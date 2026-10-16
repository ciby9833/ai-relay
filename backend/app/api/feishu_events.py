"""飞书事件：机器人收到消息后交给 Agent 处理并回复。

默认通过长连接接收（app.feishu.longconn）；这里的 HTTP 回调供以后改用公网回调地址时使用。
"""

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import conversation_lock, run_turn_text
from app.config import get_settings
from app.db import SessionLocal
from app.feishu.client import FeishuClient
from app.feishu.events import decrypt_event, extract_text, mentioned_people, text_with_names
from app.home import home_conversation, turn_lock
from app.llm.base import LLMError
from app.models import ChatMessage, Conversation, FeishuCard, FeishuEvent, FollowUp, Signal, User
from app.sources import people
from app.sources.base import add_signal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feishu", tags=["feishu"])

# 同一个聊天里隔这么久没说话，就另起一段对话
IDLE_RESET = timedelta(hours=6)

_background: set[asyncio.Task] = set()


@router.post("/events")
async def feishu_events(request: Request):
    settings = get_settings()
    if not settings.feishu_verification_token:
        raise HTTPException(status_code=503, detail="未配置 FEISHU_VERIFICATION_TOKEN")

    body = await request.json()
    if "encrypt" in body:
        if not settings.feishu_encrypt_key:
            raise HTTPException(status_code=400, detail="收到加密事件但未配置 FEISHU_ENCRYPT_KEY")
        try:
            body = decrypt_event(settings.feishu_encrypt_key, body["encrypt"])
        except Exception:
            raise HTTPException(status_code=400, detail="事件解密失败") from None

    header = body.get("header") or {}
    token = body.get("token") or header.get("token") or ""
    if not secrets.compare_digest(token, settings.feishu_verification_token):
        raise HTTPException(status_code=403, detail="verification token 不匹配")

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    await dispatch_event(request.app.state.feishu, body)
    return {}


async def dispatch_event(feishu: FeishuClient, body: dict) -> None:
    """处理一条已验证来源的事件（HTTP 回调和长连接共用）。"""
    header = body.get("header") or {}
    if header.get("tenant_key") != get_settings().feishu_tenant_key:
        return
    event_id = header.get("event_id")
    if not event_id:
        return

    # 飞书会重推没有及时确认的事件，按 event_id 去重
    async with SessionLocal() as session:
        result = await session.execute(
            insert(FeishuEvent).values(event_id=event_id).on_conflict_do_nothing()
        )
        await session.commit()
        if not result.rowcount:
            return

    if header.get("event_type") == "im.message.receive_v1":
        # 飞书要求 3 秒内确认，实际处理放到后台
        task = asyncio.create_task(_handle_message(feishu, body.get("event") or {}))
        _background.add(task)
        task.add_done_callback(_background.discard)


async def _get_or_create_user(session: AsyncSession, open_id: str, tenant_key: str) -> User:
    result = await session.execute(select(User).where(User.feishu_open_id == open_id))
    user = result.scalars().first()
    if user is None:
        # 还没在网页端登录过的同事：先建档，登录后会补全姓名等信息
        user = User(
            feishu_open_id=open_id,
            tenant_key=tenant_key,
            name="飞书用户",
            timezone=get_settings().default_timezone,
        )
        session.add(user)
        await session.flush()
    return user


async def _get_conversation(session: AsyncSession, user: User, chat_id: str) -> Conversation:
    result = await session.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user.id,
            Conversation.channel == "feishu",
            Conversation.external_id == chat_id,
            Conversation.updated_at > datetime.now(UTC) - IDLE_RESET,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    conversation = result.scalars().first()
    if conversation is None:
        conversation = Conversation(user_id=user.id, channel="feishu", external_id=chat_id)
        session.add(conversation)
        await session.flush()
    return conversation


async def _handle_message(feishu: FeishuClient, event: dict) -> None:
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    message_id = message.get("message_id")
    open_id = (sender.get("sender_id") or {}).get("open_id")
    if sender.get("sender_type") != "user" or not open_id or not message_id:
        return
    if message.get("chat_type") != "p2p":
        mentioned = [((m.get("id") or {}).get("open_id")) for m in message.get("mentions") or []]
        try:
            await _watch_group_message(feishu, message, open_id, mentioned)
        except Exception:
            logger.exception("记录群消息失败")
        # 群聊里只响应 @ 机器人的消息
        if await feishu.bot_open_id() not in mentioned:
            return

    try:
        bot = await feishu.bot_open_id()
        # 保留被@的同事名字（例如“帮我约 @Andrew @Nikki”），去掉对机器人自己的@
        text = text_with_names(message, {bot})
        if text is None:
            await feishu.reply_text(message_id, "目前只能处理文字消息。")
            return
        if not text:
            return
        async with SessionLocal() as session:
            user = await _get_or_create_user(session, open_id, sender.get("tenant_key") or "")
            await people.remember(session, [p for p in mentioned_people(message) if p[0] != bot])
            text = await _with_quote_context(session, user, message, text)
            if message.get("chat_type") == "p2p":
                # 私聊机器人就是在主线里和 Relay 说话，和网页首页是同一条
                conversation = await home_conversation(session, user)
            else:
                conversation = await _get_conversation(session, user, message.get("chat_id") or open_id)
            await session.commit()
            async with conversation_lock(conversation.id), turn_lock(conversation.id):
                try:
                    reply = await run_turn_text(
                        session, user=user, conversation=conversation, text=text, feishu=feishu
                    )
                except LLMError as exc:
                    reply = f"模型调用失败：{exc}"
        if reply:
            await feishu.reply_text(message_id, reply)
    except Exception:
        logger.exception("处理飞书消息失败")
        try:
            await feishu.reply_text(message_id, "处理这条消息时出错了，请稍后再试。")
        except Exception:
            logger.exception("发送出错提示失败")


async def _watch_group_message(
    feishu: FeishuClient, message: dict, sender_open_id: str, mentioned: list[str]
) -> None:
    """群里@了某位 Relay 用户就开始盯着；他之后在这个群里说话就算回复了。

    需要机器人在群里，并开通“获取群组中所有消息”权限，否则只能收到@机器人的消息。
    """
    chat_id = message.get("chat_id")
    async with SessionLocal() as session:
        sender = (await session.execute(select(User).where(User.feishu_open_id == sender_open_id))).scalars().first()
        text = text_with_names(message)
        sender_name = sender.name if sender else await feishu.user_name(sender_open_id)
        await people.remember(session, mentioned_people(message) + [(sender_open_id, sender_name, "sender")])
        if text:
            # 群消息只用来理解要处理的事（提取待办、起草时作背景），不推送
            await session.execute(
                insert(ChatMessage).values(
                    message_id=message["message_id"], chat_id=chat_id, sender_open_id=sender_open_id,
                    sender_name=sender_name,
                    text=text[:4000],
                    mentions=[{"open_id": (m.get("id") or {}).get("open_id"), "name": m.get("name")} for m in message.get("mentions") or []],
                ).on_conflict_do_nothing(index_elements=["message_id"])
            )
        if sender:
            await session.execute(
                update(Signal)
                .where(Signal.user_id == sender.id, Signal.kind == "mention",
                       Signal.status.in_(["watching", "notify", "tracked"]), Signal.payload["chat_id"].astext == chat_id)
                .values(status="done")
            )
        bot = await feishu.bot_open_id()
        targets = [o for o in mentioned if o and o not in (bot, sender_open_id)]
        if targets:
            users = (await session.execute(select(User).where(User.feishu_open_id.in_(targets)))).scalars().all()
            chat_name = None
            for user in users:
                if chat_name is None:
                    try:
                        chat_name = (await feishu.tenant_api("GET", f"/im/v1/chats/{chat_id}")).get("name") or ""
                    except Exception:
                        chat_name = ""
                await add_signal(
                    session, user, "message", message["message_id"],
                    kind="mention", title=f"{chat_name or '群聊'}里有人@你",
                    body=(extract_text(message) or "")[:1000], payload={"chat_id": chat_id, "chat_name": chat_name},
                    occurred_at=datetime.now(UTC), status="watching",
                )
        await session.commit()


async def _with_quote_context(session: AsyncSession, user: User, message: dict, text: str) -> str:
    """用户引用 Relay 的某张卡片回复时，告诉模型他指的是哪几件事。"""
    parent = message.get("parent_id")
    record = await session.get(FeishuCard, parent) if parent else None
    if record is None or record.user_id != user.id:
        return text
    item_ids = [c["item_id"] for _, group in record.sections for c in group if c.get("kind") == "item"]
    refs = []
    for item_id in item_ids[:10]:
        item = await session.get(FollowUp, item_id)
        if item:
            refs.append(f"#{item.id} {item.title}")
    note = f"（我在引用回复你发的《{record.title}》" + (f"，里面的事项：{'；'.join(refs)}" if refs else "") + "）"
    return f"{note}\n{text}"
