"""对话里内嵌的卡片数据。前端按 kind 渲染；飞书推送时转成飞书卡片。"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FollowUp, PendingAction, Signal


def iso(moment) -> str | None:
    return moment.isoformat() if moment else None


def mail_card(signal: Signal) -> dict:
    p = signal.payload or {}
    return {
        "kind": "mail", "signal_id": signal.id, "from": p.get("from_name") or p.get("from_address"),
        "from_address": p.get("from_address"), "subject": signal.title,
        "summary": signal.summary or (signal.body or "")[:160], "importance": signal.importance,
        "needs_reply": signal.needs_reply, "time": iso(signal.occurred_at),
    }


def draft_card(action: PendingAction) -> dict:
    return {"kind": "draft", "action_id": action.id}


def event_card(signal: Signal, conflicts: list[str] | None = None, action_id: int | None = None) -> dict:
    p = signal.payload or {}
    return {
        "kind": "event", "signal_id": signal.id, "title": signal.title, "start": p.get("start"),
        "end": p.get("end"), "all_day": p.get("all_day"), "location": p.get("location"),
        "organizer": p.get("organizer"), "attendees": p.get("attendees") or [],
        "meeting_url": p.get("meeting_url"), "app_link": p.get("app_link"),
        "rsvp": p.get("rsvp"), "conflicts": conflicts or [], "action_id": action_id,
    }


def approval_card(signal: Signal) -> dict:
    return {"kind": "approval", "title": signal.title, "detail": signal.body, "url": signal.url}


def alert_card(signal: Signal) -> dict:
    p = signal.payload or {}
    return {
        "kind": "alert", "source": signal.source, "title": signal.title,
        "detail": signal.body, "context": p.get("chat_name"), "url": signal.url,
        "level": "urgent" if signal.importance == "urgent" else "normal",
    }


def signal_card(signal: Signal) -> dict:
    if signal.kind == "mail":
        return mail_card(signal)
    if signal.kind in ("meeting", "invitation"):
        return event_card(signal)
    if signal.kind == "approval_pending":
        return approval_card(signal)
    return alert_card(signal)


async def conflicts_for(session: AsyncSession, signal: Signal) -> list[str]:
    """同一时段里用户已有的其他日程。"""
    p = signal.payload or {}
    if not signal.occurred_at or p.get("all_day"):
        return []
    end = signal.occurred_at + timedelta(minutes=30)
    if p.get("end"):
        end = datetime.fromisoformat(p["end"])
    result = await session.execute(
        select(Signal.title, Signal.payload).where(
            Signal.user_id == signal.user_id, Signal.kind == "meeting", Signal.status != "ignored",
            Signal.occurred_at < end, Signal.occurred_at >= signal.occurred_at - timedelta(hours=12),
            Signal.payload["event_id"].astext != p.get("event_id"),
        )
    )
    titles = []
    for title, payload in result:
        other_end = payload.get("end")
        if payload.get("all_day") or payload.get("rsvp") == "decline":
            continue
        if other_end and other_end <= signal.occurred_at.isoformat():
            continue
        titles.append(title)
    return titles


RSVP_WORD = {"accept": "接受", "tentative": "待定", "decline": "拒绝"}


def ask_ui(item: FollowUp, action: PendingAction | None) -> dict | None:
    """Structured Web UI copy, translated at render time without rewriting user content."""
    if item.status != "open":
        return None
    if action and action.status == "pending":
        if action.kind == "send_mail":
            key = "ask.followup" if action.summary.startswith("跟进") else "ask.draft"
            return {"key": key}
        if action.kind == "calendar_rsvp" and action.payload.get("status") in RSVP_WORD:
            return {"key": f"ask.rsvp.{action.payload['status']}"}
        if action.kind == "approval_decision":
            return {"key": "ask.confirm", "values": {"summary": action.summary}}
    if item.owner == "others":
        return {"key": "ask.waiting", "values": {"person": item.waiting_on}} if item.waiting_on else {"key": "ask.waitingUnknown"}
    if item.next_step:
        return None
    return {"key": "ask.approval" if item.kind == "approval" else "ask.handle"}


def ask(item: FollowUp, action: PendingAction | None) -> str:
    """一句话说清楚：这件事要他做什么（或者不用他做）。"""
    if item.status != "open":
        return item.resolution or "已结束"
    if action and action.status == "pending":
        if action.kind == "send_mail":
            return "确认发送跟进邮件" if action.summary.startswith("跟进") else "看一眼 Relay 起草的回复，确认发送"
        if action.kind == "calendar_rsvp":
            return f"回复邀请（建议{RSVP_WORD[action.payload['status']]}）"
        if action.kind == "approval_decision":
            return f"确认：{action.summary}"
    if item.owner == "others":
        return f"不用你做，Relay 在等 {item.waiting_on or '对方'}"
    if item.kind == "approval":
        return item.next_step or "去飞书审批"
    return item.next_step or "处理这件事"
