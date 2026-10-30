"""日历：未来几天的日程，以及待回复的会议邀请。

两种日历，同一套行为：成员接了日历订阅链接（ICS，见 app/sources/ics.py）就用它（只读），否则用飞书日历。
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import cast, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app import connections
from app.feishu.client import FeishuClient, FeishuError
from app.models import Signal, SourceState, User
from app.sources import ics
from app.sources.base import add_signal

WINDOW_DAYS = 3


def _event_time(info: dict | None, timezone: str) -> datetime | None:
    if not info:
        return None
    stamp = info.get("timestamp") or info.get("time_stamp")
    if stamp:
        return datetime.fromtimestamp(int(stamp), UTC)
    if info.get("date"):  # 全天日程
        day = date.fromisoformat(info["date"])
        return datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(timezone)).astimezone(UTC)
    return None


async def primary_calendar_id(feishu: FeishuClient, user: User, state: SourceState) -> str:
    if not state.cursor.get("calendar_id"):
        data = await feishu.user_api(user, "POST", "/calendar/v4/calendars/primary")
        calendar_id = data["calendars"][0]["calendar"]["calendar_id"]
        state.cursor = {**state.cursor, "calendar_id": calendar_id}
    return state.cursor["calendar_id"]


async def list_events(
    feishu: FeishuClient, user: User, state: SourceState, start: datetime, end: datetime
) -> list[dict]:
    if (account := await connections.account(user, "ics")) is not None:
        return await ics.list_events(account, user.timezone, start, end)
    calendar_id = await primary_calendar_id(feishu, user, state)
    data = await feishu.user_api(
        user,
        "GET",
        f"/calendar/v4/calendars/{calendar_id}/events/instance_view",
        params={"start_time": str(int(start.timestamp())), "end_time": str(int(end.timestamp()))},
    )
    events = []
    for item in data.get("items") or []:
        if item.get("status") == "cancelled":
            continue
        events.append(
            {
                "event_id": item["event_id"],
                "summary": item.get("summary") or "（无标题）",
                "description": (item.get("description") or "")[:2000],
                "start": _event_time(item.get("start_time"), user.timezone),
                "end": _event_time(item.get("end_time"), user.timezone),
                "all_day": "date" in (item.get("start_time") or {}),
                "location": (item.get("location") or {}).get("name"),
                "meeting_url": (item.get("vchat") or {}).get("meeting_url"),
                "organizer": (item.get("event_organizer") or {}).get("display_name"),
                "attendees": [
                    a.get("display_name")
                    for a in item.get("attendees") or []
                    if a.get("display_name") and a.get("type") == "user"
                ][:20],
                "rsvp": item.get("self_rsvp_status"),
                "app_link": item.get("app_link"),
                "calendar_id": state.cursor["calendar_id"],
                # 重复日程展开出的实例有自己的 ID；查参会人等要用原始日程的 ID
                "base_event_id": item.get("recurring_event_id") or item["event_id"],
                "organizer_calendar_id": item.get("organizer_calendar_id"),
            }
        )
    return events


async def sync(session: AsyncSession, feishu: FeishuClient, user: User, state: SourceState) -> int:
    now = datetime.now(UTC)
    events = await list_events(feishu, user, state, now - timedelta(hours=1), now + timedelta(days=WINDOW_DAYS))
    created = 0
    current: list[str] = []
    for event in events:
        if not event["start"]:
            continue
        payload = {**event, "start": event["start"].isoformat(), "end": event["end"].isoformat() if event["end"] else None}
        external_id = f"{event['event_id']}@{int(event['start'].timestamp())}"
        current.append(external_id)
        created += await add_signal(
            session, user, "calendar", external_id,
            kind="meeting", title=event["summary"], body=event["description"],
            url=event["app_link"], payload=payload, occurred_at=event["start"],
            status="scheduled",  # 不逐条推送，由会前准备和每日简报使用
        )
        # 已存在的日程也刷新一下内容（时间不变、标题/参会人/回复状态可能变了）
        await session.execute(
            update(Signal)
            .where(Signal.user_id == user.id, Signal.source == "calendar", Signal.external_id == external_id)
            # 合并而不是覆盖：会前准备、纪要等 Relay 记在会上的内容要留着
            .values(title=event["summary"], payload=Signal.payload.op("||")(cast(payload, JSONB)))
        )
        if event["rsvp"] == "needs_action" and event["start"] > now:
            created += await add_signal(
                session, user, "calendar", f"invite:{event['event_id']}",
                kind="invitation", title=event["summary"], body=event["description"],
                url=event["app_link"], payload=payload, occurred_at=event["start"],
                status="notify", importance="normal",
            )
    # 窗口内消失的日程（取消或改期）不再提醒
    await session.execute(
        update(Signal)
        .where(
            Signal.user_id == user.id,
            Signal.source == "calendar",
            Signal.kind == "meeting",
            Signal.status == "scheduled",
            Signal.occurred_at > now,
            Signal.occurred_at < now + timedelta(days=WINDOW_DAYS),
            Signal.external_id.not_in(current or [""]),
        )
        .values(status="ignored", reason="日程已取消或改期")
    )
    return created


async def reply_invitation(feishu: FeishuClient, user: User, calendar_id: str, event_id: str, status: str) -> None:
    _writable(calendar_id)
    await feishu.user_api(
        user, "POST", f"/calendar/v4/calendars/{calendar_id}/events/{event_id}/reply",
        json={"rsvp_status": status},
    )


async def attendees_for(feishu: FeishuClient, user: User, event: dict) -> list[dict]:
    """按日程数据（信号里存的 payload）查参会人；查不到时返回空列表。"""
    try:
        return await event_attendees(
            feishu, user, event["calendar_id"], event.get("base_event_id") or event["event_id"],
            event.get("organizer_calendar_id"),
        )
    except (FeishuError, KeyError):
        return []


def _writable(calendar_id: str) -> None:
    if calendar_id == "ics":
        raise ics.CalendarError("这是订阅的日历（只读），不能在 Relay 里改，请到原来的日历里操作")


RSVP_TEXT = {"accept": "接受", "decline": "拒绝", "tentative": "待定", "needs_action": "还没回复", "removed": "已移除"}


async def event_attendees(
    feishu: FeishuClient, user: User, calendar_id: str, event_id: str, organizer_calendar_id: str | None = None
) -> list[dict]:
    """参会人和各自的回复状态。event_id 用原始日程的 ID；在自己的日历上找不到时，到组织者的日历上找。"""
    try:
        data = await feishu.user_api(
            user, "GET", f"/calendar/v4/calendars/{calendar_id}/events/{event_id}/attendees",
            params={"user_id_type": "open_id", "page_size": 100},
        )
    except FeishuError:
        if not organizer_calendar_id or organizer_calendar_id == calendar_id:
            raise
        data = await feishu.user_api(
            user, "GET", f"/calendar/v4/calendars/{organizer_calendar_id}/events/{event_id}/attendees",
            params={"user_id_type": "open_id", "page_size": 100},
        )
    return [
        {"name": a.get("display_name") or a.get("user_id") or "某人", "open_id": a.get("user_id"),
         "rsvp": a.get("rsvp_status"), "organizer": a.get("is_organizer", False)}
        for a in data.get("items") or [] if a.get("type") == "user"
    ]


async def update_event(
    feishu: FeishuClient, user: User, calendar_id: str, event_id: str, start: datetime, end: datetime
) -> None:
    _writable(calendar_id)
    await feishu.user_api(
        user, "PATCH", f"/calendar/v4/calendars/{calendar_id}/events/{event_id}",
        json={"start_time": {"timestamp": str(int(start.timestamp()))}, "end_time": {"timestamp": str(int(end.timestamp()))},
              "need_notification": True},
    )


async def delete_event(feishu: FeishuClient, user: User, calendar_id: str, event_id: str) -> None:
    _writable(calendar_id)
    await feishu.user_api(
        user, "DELETE", f"/calendar/v4/calendars/{calendar_id}/events/{event_id}", params={"need_notification": "true"}
    )


async def add_attendees(feishu: FeishuClient, user: User, calendar_id: str, event_id: str, open_ids: list[str]) -> None:
    _writable(calendar_id)
    await feishu.user_api(
        user, "POST", f"/calendar/v4/calendars/{calendar_id}/events/{event_id}/attendees",
        params={"user_id_type": "open_id"},
        json={"attendees": [{"type": "user", "user_id": i} for i in open_ids], "need_notification": True},
    )
