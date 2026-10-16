"""约会：查参会人的忙闲，找出共同空闲的时间段；建会议并邀请参会人。"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient
from app.models import SourceState, User
from app.sources import calendar

WORK_START, WORK_END = time(9, 0), time(18, 0)
STEP = timedelta(minutes=30)


async def busy_intervals(feishu: FeishuClient, open_ids: list[str], start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    data = await feishu.tenant_api(
        "POST", "/calendar/v4/freebusy/batch", params={"user_id_type": "open_id"},
        json={"time_min": start.isoformat(), "time_max": end.isoformat(), "user_ids": open_ids, "only_busy": True},
    )
    busy = []
    for person in data.get("freebusy_lists") or []:
        for slot in person.get("freebusy_items") or person.get("freebusy_list") or []:
            busy.append((datetime.fromisoformat(slot["start_time"]), datetime.fromisoformat(slot["end_time"])))
    return busy


def free_slots(
    busy: list[tuple[datetime, datetime]], start: datetime, end: datetime, duration: timedelta, timezone: str, limit: int = 5
) -> list[tuple[datetime, datetime]]:
    """工作日 9:00-18:00 内、所有人都空闲的时间段（按半小时对齐）。"""
    tz = ZoneInfo(timezone)
    cursor = start.astimezone(tz).replace(second=0, microsecond=0)
    if cursor.minute % 30:
        cursor += timedelta(minutes=30 - cursor.minute % 30)
    slots = []
    while cursor + duration <= end.astimezone(tz) and len(slots) < limit:
        slot_end = cursor + duration
        in_hours = cursor.weekday() < 5 and cursor.time() >= WORK_START and slot_end.time() <= WORK_END and slot_end.date() == cursor.date()
        if in_hours and not any(b_start < slot_end and b_end > cursor for b_start, b_end in busy):
            slots.append((cursor.astimezone(UTC), slot_end.astimezone(UTC)))
            cursor = slot_end  # 下一个候选不和这个重叠
            continue
        cursor += STEP
    return slots


async def create_meeting(
    session: AsyncSession, feishu: FeishuClient, user: User, title: str, start: datetime, end: datetime,
    attendee_ids: list[str], description: str = "",
) -> dict:
    state = await session.get(SourceState, (user.id, "calendar"))
    if state is None:
        state = SourceState(user_id=user.id, source="calendar", cursor={})
        session.add(state)
        await session.flush()
    calendar_id = await calendar.primary_calendar_id(feishu, user, state)
    data = await feishu.user_api(
        user, "POST", f"/calendar/v4/calendars/{calendar_id}/events",
        json={
            "summary": title, "description": description,
            "start_time": {"timestamp": str(int(start.timestamp()))},
            "end_time": {"timestamp": str(int(end.timestamp()))},
            "vchat": {"vc_type": "vc"}, "attendee_ability": "can_see_others", "need_notification": True,
        },
    )
    event = data.get("event") or {}
    if attendee_ids:
        await feishu.user_api(
            user, "POST", f"/calendar/v4/calendars/{calendar_id}/events/{event['event_id']}/attendees",
            params={"user_id_type": "open_id"},
            json={"attendees": [{"type": "user", "user_id": i} for i in attendee_ids], "need_notification": True},
        )
    return {"event_id": event.get("event_id"), "calendar_id": calendar_id, "app_link": event.get("app_link")}
