"""工作区：会议（会前准备、会后行动项）和进展（已经有结果的事、汇总和简报）。

“待处理”沿用 /api/board。对话只用来解释、追问和委托，不再承载所有通知。
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import FeishuDep, SessionDep, UserDep
from app.home import home_conversation
from app.i18n import user_language
from app.models import FollowUp, Message, Signal
from app.proactive import items, meetings
from app.proactive.settings import get_settings_row, merged

router = APIRouter(prefix="/api", tags=["workspace"])

PROGRESS_DAYS = 7


async def _meeting_json(session, user, meeting: Signal) -> dict:
    payload = meeting.payload or {}
    series = payload.get("base_event_id") or payload.get("event_id")
    actions = []
    if series:
        rows = (await session.execute(select(FollowUp).where(
            FollowUp.user_id == user.id, FollowUp.facets["meeting"].astext == series,
            FollowUp.status.notin_(items.HIDDEN), FollowUp.created_at > datetime.now(UTC) - timedelta(days=45),
        ).order_by(FollowUp.id))).scalars().all()
        actions = [{"id": a.id, "title": a.title, "owner": a.owner, "status": a.status, "resolution": a.resolution} for a in rows]
    invitation = (await session.execute(select(FollowUp).where(
        FollowUp.user_id == user.id, FollowUp.key == f"invite:{payload.get('event_id')}", FollowUp.status == items.OPEN,
    ))).scalars().first() if payload.get("event_id") else None
    return {
        "id": meeting.id, "title": meeting.title, "start": meeting.occurred_at.isoformat() if meeting.occurred_at else None,
        "end": payload.get("end"), "all_day": bool(payload.get("all_day")), "location": payload.get("location"),
        "meeting_url": payload.get("meeting_url"), "url": meeting.url, "rsvp": payload.get("rsvp"),
        "organizer": payload.get("organizer"), "attendees": (payload.get("attendees") or [])[:12],
        "prep": payload.get("prep"), "minutes": payload.get("minutes"), "minutes_missing": bool(payload.get("minutes_missing")),
        "actions": actions, "invitation_item_id": invitation.id if invitation else None,
    }


@router.get("/meetings")
async def list_meetings(session: SessionDep, user: UserDep):
    """接下来 3 天的会（含会前准备），以及过去一天开过的会（含纪要和行动项）。"""
    now = datetime.now(UTC)
    rows = (await session.execute(select(Signal).where(
        Signal.user_id == user.id, Signal.kind == "meeting", Signal.status != "ignored",
        Signal.occurred_at > now - timedelta(days=1), Signal.occurred_at < now + timedelta(days=3),
    ).order_by(Signal.occurred_at))).scalars().all()
    upcoming, recent = [], []
    for meeting in rows:
        if (meeting.payload or {}).get("rsvp") == "decline":
            continue
        end = (meeting.payload or {}).get("end")
        over = datetime.fromisoformat(end) < now if end else meeting.occurred_at < now - timedelta(hours=1)
        (recent if over else upcoming).append(await _meeting_json(session, user, meeting))
    return {"upcoming": upcoming, "recent": recent[::-1]}


@router.post("/meetings/{meeting_id}/prep")
async def prepare_meeting(meeting_id: int, session: SessionDep, user: UserDep, feishu: FeishuDep):
    """现在就整理会前准备（只用此刻已经存在的材料）。"""
    meeting = await session.get(Signal, meeting_id)
    if meeting is None or meeting.user_id != user.id or meeting.kind != "meeting":
        raise HTTPException(status_code=404, detail="会议不存在")
    settings = merged((await get_settings_row(session, user)).data)
    await meetings.prepare(session, feishu, user, meeting, user_language(settings))
    await session.commit()
    return await _meeting_json(session, user, meeting)


@router.get("/progress")
async def progress(session: SessionDep, user: UserDep):
    """进展：最近 7 天有了结果的事（按天），以及 Relay 发过的汇总和简报。"""
    since = datetime.now(UTC) - timedelta(days=PROGRESS_DAYS)
    tz = ZoneInfo(user.timezone)
    closed = (await session.execute(select(FollowUp).where(
        FollowUp.user_id == user.id, FollowUp.status.in_(("done", "dismissed")), FollowUp.closed_at > since,
    ).order_by(FollowUp.closed_at.desc()).limit(200))).scalars().all()
    days: dict[str, list] = {}
    for item in closed:
        days.setdefault(item.closed_at.astimezone(tz).date().isoformat(), []).append({
            "id": item.id, "title": item.title, "kind": item.kind, "owner": item.owner, "status": item.status,
            "resolution": item.resolution, "closed_at": item.closed_at.isoformat(),
        })
    conversation = await home_conversation(session, user)
    await session.commit()
    rows = (await session.execute(select(Message).where(
        Message.conversation_id == conversation.id, Message.created_at > since).order_by(Message.id))).scalars().all()
    notes, kind = [], None
    for message in rows:
        if message.role == "user":
            event = next((b for b in message.content if b.get("meta") == "event"), None)
            kind = event.get("notice") if event else None
            continue
        text = "\n\n".join(b["text"] for b in message.content if b["type"] == "text" and b.get("text"))
        if kind in ("digest", "brief") and text:
            notes.append({"kind": kind, "text": text, "created_at": message.created_at.isoformat()})
            kind = None
    return {"days": [{"date": d, "items": v} for d, v in days.items()], "notes": notes[::-1][:20]}
