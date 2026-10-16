from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DEFAULT_SETTINGS, User, UserSettings


async def get_settings_row(session: AsyncSession, user: User) -> UserSettings:
    row = await session.get(UserSettings, user.id)
    if row is None:
        row = UserSettings(user_id=user.id, data={})
        session.add(row)
        await session.flush()
    return row


def merged(data: dict) -> dict:
    result = {**DEFAULT_SETTINGS, **(data or {})}
    result["sources"] = {**DEFAULT_SETTINGS["sources"], **(data or {}).get("sources", {})}
    return result


def _parse(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def in_quiet_hours(settings: dict, timezone: str, now: datetime | None = None) -> bool:
    local = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone)).time()
    start, end = _parse(settings["quiet_start"]), _parse(settings["quiet_end"])
    return start <= local or local < end if start > end else start <= local < end


def is_workday(timezone: str, now: datetime | None = None) -> bool:
    return (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone)).weekday() < 5


async def language_of(session: AsyncSession, user: User) -> str:
    """用户习惯的语言（设置里指定的，或从他的消息里识别到的）。"""
    from app.i18n import user_language

    return user_language(merged((await get_settings_row(session, user)).data))
