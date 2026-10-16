"""定时任务的时间计算。"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

MIN_INTERVAL = timedelta(minutes=15)


class ScheduleError(ValueError):
    pass


def next_cron_run(cron: str, timezone: str, after: datetime | None = None) -> datetime:
    """cron 表达式按用户时区解释，返回下一次触发的 UTC 时间。"""
    if len(cron.split()) != 5 or not croniter.is_valid(cron):
        raise ScheduleError("cron 表达式不合法，需要 5 段：分 时 日 月 周")
    base = (after or datetime.now(UTC)).astimezone(ZoneInfo(timezone))
    return croniter(cron, base).get_next(datetime).astimezone(UTC)


def validate_cron(cron: str, timezone: str) -> datetime:
    first = next_cron_run(cron, timezone)
    second = next_cron_run(cron, timezone, first)
    if second - first < MIN_INTERVAL:
        raise ScheduleError("执行间隔不能小于 15 分钟")
    return first


def parse_run_at(value: str, timezone: str) -> datetime:
    """一次性任务的时间：ISO 8601，不带时区时按用户时区解释。"""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ScheduleError("run_at 需要 ISO 8601 格式，例如 2026-10-15T09:00") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(timezone))
    moment = moment.astimezone(UTC)
    if moment <= datetime.now(UTC):
        raise ScheduleError("run_at 必须是将来的时间")
    return moment
