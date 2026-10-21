import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import conversation_lock, run_turn
from app.db import SessionLocal
from app.deps import FeishuDep, SessionDep, UserDep
from app.llm import registry
from app.llm.base import LLMError
from app.home import home_conversation, turn_lock
from app.missions import service as mission_service
from app.models import Conversation, FollowUp, Message, Mission, MissionLog, PendingAction, Signal, SourceState, User
from app.proactive import items as follow_ups

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["conversations"])


class SendMessage(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    model: str | None = None


def _conversation_json(conversation: Conversation) -> dict:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "channel": conversation.channel,
        "updated_at": conversation.updated_at.isoformat(),
    }


def _action_json(action: PendingAction) -> dict:
    return follow_ups.actions_json(action)


async def mission_json(session: AsyncSession, mission: Mission, logs: int = 0) -> dict:
    pending = (await session.execute(
        select(PendingAction).where(PendingAction.mission_id == mission.id, PendingAction.status == "pending")
        .order_by(PendingAction.id)
    )).scalars().all()
    data = {
        "id": mission.id, "title": mission.title, "goal": mission.goal, "status": mission.status,
        "instruction": mission.instruction, "due_at": mission.due_at.isoformat() if mission.due_at else None,
        "plan": mission.plan, "criteria": mission.criteria or [], "notes": mission.notes, "grants": mission.grants, "question": mission.question,
        "result": mission.result, "runs": mission.runs,
        "waiting_for": mission_service.describe_wait(mission.wait_for) if mission.status == "waiting" and mission.wait_for else None,
        "next_run_at": mission.next_run_at.isoformat() if mission.next_run_at else None,
        "updated_at": mission.updated_at.isoformat(),
        "pending_actions": [_action_json(a) for a in pending],
    }
    if logs:
        rows = (await session.execute(
            select(MissionLog).where(MissionLog.mission_id == mission.id).order_by(MissionLog.id.desc()).limit(logs)
        )).scalars().all()
        data["logs"] = [{"kind": r.kind, "text": r.text, "at": r.created_at.isoformat()} for r in rows]
    return data


async def serialize_messages(session: AsyncSession, messages: list[Message]) -> list[dict]:
    """转成前端展示用的形状：连续的助手消息（一轮里的多步）合并成一条，
    隐藏工具结果、系统注入的 context 块和后台事件；卡片里的待确认操作附上最新状态。"""
    action_ids = {
        block["card"].get("action_id")
        for m in messages for block in m.content
        if block["type"] == "card" and block["card"].get("action_id")
    }
    actions = {}
    if action_ids:
        result = await session.execute(select(PendingAction).where(PendingAction.id.in_(action_ids)))
        actions = {a.id: _action_json(a) for a in result.scalars()}

    items: list[dict] = []
    for message in messages:
        blocks = message.content
        if message.role == "user":
            if any(b["type"] == "tool_result" for b in blocks):
                continue  # 工具结果属于同一轮，不打断助手消息的合并
            text = "\n\n".join(b["text"] for b in blocks if b["type"] == "text" and not b.get("meta") and b["text"])
            if text:
                items.append({"id": message.id, "role": "user", "text": text, "created_at": message.created_at.isoformat()})
            elif any(b.get("meta") == "event" for b in blocks):
                # 后台事件：结束上一条助手消息的合并，让主动发言单独成条
                items.append({"id": message.id, "role": "event"})
            continue
        if not items or items[-1]["role"] != "assistant":
            items.append({
                "id": message.id, "role": "assistant", "text": "", "steps": [], "cards": [],
                "created_at": message.created_at.isoformat(), "proactive": bool(items) and items[-1]["role"] == "event",
            })
        item = items[-1]
        text = "\n\n".join(b["text"] for b in blocks if b["type"] == "text" and b["text"])
        if text:
            item["text"] = f"{item['text']}\n\n{text}".strip()
        item["steps"] += [b["name"] for b in blocks if b["type"] == "tool_use"]
        for block in blocks:
            if block["type"] == "card":
                card = dict(block["card"])
                if card.get("action_id") in actions:
                    card["action"] = actions[card["action_id"]]
                if card["kind"] == "item":
                    follow_up = await session.get(FollowUp, card["item_id"])
                    if follow_up is None:
                        continue
                    card["item"] = await follow_ups.item_json(session, follow_up)
                if card["kind"] == "mission":
                    mission = await session.get(Mission, card["mission_id"])
                    if mission is None:
                        continue
                    card["mission"] = await mission_json(session, mission)
                if card["kind"] == "action" and "action" not in card:
                    continue
                item["cards"].append(card)
    return [item for item in items if item["role"] != "event" and (item["role"] != "assistant" or item["text"] or item["cards"] or item["steps"])]


async def _ordered_messages(session: AsyncSession, conversation_id: uuid.UUID, limit: int = 200) -> list[Message]:
    result = await session.execute(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
    )
    return list(result.scalars())[::-1]


async def _own_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


@router.get("/models")
async def list_models(user: UserDep):
    models = registry.available_models()
    return {"models": models, "default": registry.default_model() if models else None}


@router.get("/conversations")
async def list_conversations(session: SessionDep, user: UserDep):
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.channel.not_in(["home", "mission"]))
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    return [_conversation_json(c) for c in result.scalars()]


@router.post("/conversations")
async def create_conversation(session: SessionDep, user: UserDep):
    conversation = Conversation(user_id=user.id, channel="web")
    session.add(conversation)
    await session.commit()
    return _conversation_json(conversation)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: uuid.UUID, session: SessionDep, user: UserDep):
    await session.delete(await _own_conversation(session, user, conversation_id))
    await session.commit()
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: uuid.UUID, session: SessionDep, user: UserDep):
    await _own_conversation(session, user, conversation_id)
    return await serialize_messages(session, await _ordered_messages(session, conversation_id))


@router.get("/home")
async def get_home(session: SessionDep, user: UserDep):
    """主线：对话 + Relay 当前在盯着的事的概况。"""
    conversation = await home_conversation(session, user)
    await session.commit()
    now = datetime.now(UTC)
    local_now = now.astimezone(ZoneInfo(user.timezone))
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    counts = dict((await session.execute(
        select(Signal.kind, func.count()).where(
            Signal.user_id == user.id,
            or_(
                and_(Signal.kind == "meeting", Signal.status != "ignored",
                     Signal.occurred_at.between(now, day_start + timedelta(days=1))),
                and_(Signal.kind == "approval_pending", Signal.status.not_in(["done", "ignored"])),
                and_(Signal.kind == "mail", Signal.created_at >= day_start),
            ),
        ).group_by(Signal.kind)
    )).all())
    pending = await session.scalar(
        select(func.count()).select_from(PendingAction)
        .where(PendingAction.user_id == user.id, PendingAction.status == "pending")
    )
    states = (await session.execute(select(SourceState).where(SourceState.user_id == user.id, SourceState.source != "auth"))).scalars().all()
    synced = [s.last_synced_at for s in states if s.last_synced_at and not s.last_error]
    return {
        "conversation": _conversation_json(conversation),
        "messages": await serialize_messages(session, await _ordered_messages(session, conversation.id)),
        "status": {
            "meetings_left_today": counts.get("meeting", 0),
            "approvals_pending": counts.get("approval_pending", 0),
            "mails_today": counts.get("mail", 0),
            "actions_pending": pending,
            "last_synced_at": max(synced).isoformat() if synced else None,
            "source_errors": sum(1 for s in states if s.last_error),
        },
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessage,
    session: SessionDep,
    user: UserDep,
    feishu: FeishuDep,
):
    await _own_conversation(session, user, conversation_id)
    lock = conversation_lock(conversation_id)
    if lock.locked():
        raise HTTPException(status_code=409, detail="上一条消息还在处理中")

    async def stream():
        # 流式响应的生命周期比请求依赖长，这里用自己的数据库会话
        async with lock, turn_lock(conversation_id), SessionLocal() as own_session:
            try:
                own_user = await own_session.get(User, user.id)
                conversation = await own_session.get(Conversation, conversation_id)
                async for event in run_turn(
                    own_session,
                    user=own_user,
                    conversation=conversation,
                    text=body.text,
                    feishu=feishu,
                    model_id=body.model,
                ):
                    yield _sse(event)
            except LLMError as exc:
                yield _sse({"type": "error", "message": str(exc)})
                yield _sse({"type": "done"})
            except Exception:
                logger.exception("处理消息失败")
                yield _sse({"type": "error", "message": "服务器内部错误"})
                yield _sse({"type": "done"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
