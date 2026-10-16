"""主动助手相关接口：动态（信号）、待确认操作、设置、数据源状态。"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import FeishuDep, SessionDep, UserDep
from app.home import post
from app.llm.base import LLMError
from app.models import FollowUp, PendingAction, Signal, SourceState
from app.proactive import actions, cards, items
from app.proactive.engine import morning_brief, sync_sources
from app.proactive.settings import get_settings_row, merged

router = APIRouter(prefix="/api", tags=["proactive"])


@router.get("/signals")
async def list_signals(session: SessionDep, user: UserDep):
    result = await session.execute(
        select(Signal)
        .where(Signal.user_id == user.id, Signal.status.not_in(["scheduled", "watching"]))
        .order_by(Signal.created_at.desc())
        .limit(80)
    )
    return [
        {
            "id": s.id, "source": s.source, "kind": s.kind, "title": s.title,
            "summary": s.summary or (s.body or "")[:160], "url": s.url,
            "status": s.status, "importance": s.importance, "needs_reply": s.needs_reply,
            "from": (s.payload or {}).get("from"),
            "occurred_at": (s.occurred_at or s.created_at).isoformat(),
        }
        for s in result.scalars()
    ]


@router.get("/actions")
async def list_actions(session: SessionDep, user: UserDep):
    result = await session.execute(
        select(PendingAction).where(PendingAction.user_id == user.id)
        .order_by(PendingAction.id.desc()).limit(30)
    )
    return [
        {
            "id": a.id, "kind": a.kind, "summary": a.summary, "status": a.status, "result": a.result,
            "body": a.payload.get("body"), "to": a.payload.get("to"), "created_at": a.created_at.isoformat(),
        }
        for a in result.scalars()
    ]


@router.post("/actions/{action_id}/{decision}")
async def decide_action(
    action_id: int, decision: Literal["confirm", "cancel"], session: SessionDep, user: UserDep, feishu: FeishuDep
):
    try:
        action = await actions.own_action(session, user, action_id)
    except actions.ActionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    message = (
        await actions.execute(session, feishu, user, action) if decision == "confirm" else actions.cancel(action)
    )
    await session.commit()
    if decision == "confirm" and action.status != "done":
        # 没执行成功：让前端把原因显示在卡片上
        raise HTTPException(status_code=400, detail=message)
    return {"message": message, "status": action.status}


@router.post("/signals/{signal_id}/draft-reply")
async def draft_reply(signal_id: int, session: SessionDep, user: UserDep, feishu: FeishuDep):
    try:
        action = await actions.prepare_mail_reply(session, feishu, user, signal_id)
    except (actions.ActionError, LLMError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await items.link_action(session, user, action)
    # 草稿出现在主线里，用户可以直接改、直接发，或者接着用一句话让 Relay 改
    await post(
        session, user, event=f"用户让 Relay 起草对邮件 #{signal_id} 的回复（待确认操作 #{action.id}）",
        text="草稿在这里，可以直接改；也可以告诉我怎么调整。确认后我再发出去。",
        cards=[cards.draft_card(action)],
    )
    await session.commit()
    return {"action_id": action.id}


class DraftBody(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=50_000)
    reply_all: bool | None = None


@router.patch("/actions/{action_id}")
async def edit_draft(action_id: int, data: DraftBody, session: SessionDep, user: UserDep):
    try:
        action = await actions.own_action(session, user, action_id)
        actions.update_draft(action, data.body, data.reply_all)
    except actions.ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"ok": True}


class RsvpBody(BaseModel):
    status: Literal["accept", "tentative", "decline"]


@router.post("/signals/{signal_id}/rsvp")
async def rsvp(signal_id: int, data: RsvpBody, session: SessionDep, user: UserDep, feishu: FeishuDep):
    """在日程卡片上点接受/拒绝：点击本身就是用户的明确指令，直接执行。"""
    try:
        action = await actions.prepare_rsvp(session, user, signal_id, data.status)
    except actions.ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    message = await actions.execute(session, feishu, user, action)
    if action.status != "done":
        await session.rollback()  # 没回复成功就不留这条待确认操作
        raise HTTPException(status_code=400, detail=message)
    await session.commit()
    return {"message": message, "status": action.status}


@router.get("/board")
async def board(session: SessionDep, user: UserDep):
    """跟进看板：等你 / 等别人 / Relay 在办。"""
    result = await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == "open")
        .order_by(FollowUp.importance.desc(), FollowUp.due_at.asc().nulls_last(), FollowUp.updated_at.desc())
    )
    open_items = [await items.item_json(session, i) for i in result.scalars()]
    now = datetime.now(UTC)
    local_now = now.astimezone(ZoneInfo(user.timezone))
    day_end = local_now.replace(hour=23, minute=59).astimezone(UTC)
    settings = merged((await get_settings_row(session, user)).data)
    await session.commit()
    # Relay 在办：它接下来会主动替你做的准备和盯梢
    relay = []
    meetings = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind == "meeting", Signal.status == "scheduled",
                             Signal.occurred_at.between(now, day_end)).order_by(Signal.occurred_at)
    )).scalars().all()
    for meeting in meetings:
        if (meeting.payload or {}).get("rsvp") == "decline" or (meeting.payload or {}).get("all_day"):
            continue
        prep_at = meeting.occurred_at - timedelta(minutes=settings["meeting_brief_minutes"])
        relay.append({"kind": "meeting_prep", "title": f"准备《{meeting.title}》的会前资料",
                      "detail": f"{prep_at.astimezone(ZoneInfo(user.timezone)):%H:%M} 发给你", "at": prep_at.isoformat()})
    watching = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind == "mention", Signal.status == "watching")
    )).scalars().all()
    for signal in watching:
        relay.append({"kind": "watch", "title": f"盯着{signal.payload.get('chat_name') or '群聊'}里@你的消息",
                      "detail": "两小时内没回会提醒你", "at": signal.occurred_at.isoformat() if signal.occurred_at else None})
    for item in open_items:
        if item["owner"] == "others" and item["remind_at"]:
            relay.append({"kind": "watch", "title": f"盯着 {item['waiting_on'] or '对方'} 的回复",
                          "detail": "没回的话会提醒你并起草跟进", "at": item["remind_at"]})
    return {
        "me": [i for i in open_items if i["owner"] == "me"],
        "others": [i for i in open_items if i["owner"] == "others"],
        "relay": relay,
    }


@router.post("/items/{item_id}/{decision}")
async def close_item(item_id: int, decision: Literal["done", "dismiss"], session: SessionDep, user: UserDep):
    item = await session.get(FollowUp, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="事项不存在")
    items.close(item, "done" if decision == "done" else "dismissed", "你标记为已处理" if decision == "done" else "你说不用再跟了")
    if item.action_id:
        action = await session.get(PendingAction, item.action_id)
        if action and action.status == "pending":
            actions.cancel(action)
    await session.commit()
    return {"ok": True}


class ApprovalBody(BaseModel):
    approve: bool
    comment: str = Field(default="", max_length=1000)


@router.post("/items/{item_id}/approval")
async def decide_approval(item_id: int, data: ApprovalBody, session: SessionDep, user: UserDep, feishu: FeishuDep):
    """在审批卡片上点批准/驳回：点击本身就是用户的明确指令，直接执行。"""
    item = await session.get(FollowUp, item_id)
    if item is None or item.user_id != user.id or item.kind != "approval" or not item.signal_ids:
        raise HTTPException(status_code=404, detail="审批事项不存在")
    try:
        action = await actions.prepare_approval(session, user, item.signal_ids[-1], data.approve, data.comment)
    except actions.ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    message = await actions.execute(session, feishu, user, action)
    if action.status != "done":
        await session.rollback()
        raise HTTPException(status_code=400, detail=message)
    await session.commit()
    await items.advance(session, user)
    return {"message": message}


class SettingsBody(BaseModel):
    proactive: bool
    brief_enabled: bool = False
    sources: dict[str, bool]
    quiet_start: str = Field(pattern=r"^\d{2}:\d{2}$")
    quiet_end: str = Field(pattern=r"^\d{2}:\d{2}$")
    brief_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    meeting_brief_minutes: int = Field(ge=0, le=120)
    max_interrupts_per_hour: int = Field(ge=0, le=60)
    language: str = Field(default="auto", pattern="^(auto|zh|en|id)$")


@router.get("/settings")
async def get_settings(session: SessionDep, user: UserDep):
    row = await get_settings_row(session, user)
    await session.commit()
    states = (await session.execute(select(SourceState).where(SourceState.user_id == user.id))).scalars().all()
    return {
        "settings": merged(row.data),
        "detected_language": (row.data or {}).get("detected_language"),
        "sources": {
            s.source: {"last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None, "error": s.last_error}
            for s in states
        },
    }


@router.put("/settings")
async def put_settings(body: SettingsBody, session: SessionDep, user: UserDep):
    row = await get_settings_row(session, user)
    # 合并而不是覆盖：识别到的语言等后台记录的字段要保留
    row.data = {**(row.data or {}), **body.model_dump()}
    await session.commit()
    return {"settings": merged(row.data)}


@router.post("/sync")
async def sync_now(session: SessionDep, user: UserDep, feishu: FeishuDep):
    """立即同步一次所有数据源（不推送），方便刚授权后马上看到效果。"""
    settings = merged((await get_settings_row(session, user)).data)
    await sync_sources(session, feishu, user, settings, force=True)
    return {"ok": True, "at": datetime.now(UTC).isoformat()}


@router.post("/brief")
async def brief_now(session: SessionDep, user: UserDep, feishu: FeishuDep):
    """立即生成并推送一份简报。"""
    settings = merged((await get_settings_row(session, user)).data)
    await morning_brief(session, feishu, user, settings, force=True)
    return {"ok": True}
