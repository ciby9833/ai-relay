"""日历订阅链接（ICS）：Google 日历“私密地址”、Outlook“发布的日历”、企业日历的订阅链接。只读。

产出和飞书日历一样的日程结构（app/sources/calendar.py 的 list_events），会前准备、简报、会后纪要照常用。
只读的订阅不能替他回复邀请，所以不产生“待回复邀请”。重复日程（RRULE）按窗口展开。
"""

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from dateutil.rrule import rrulestr

from app.feishu.client import FeishuError

MAX_BYTES = 5 * 1024 * 1024
# Outlook / Exchange 常用 Windows 时区名
WINDOWS_TZ = {
    "SE Asia Standard Time": "Asia/Jakarta", "China Standard Time": "Asia/Shanghai", "Singapore Standard Time": "Asia/Singapore",
    "Tokyo Standard Time": "Asia/Tokyo", "UTC": "UTC", "GMT Standard Time": "Europe/London", "Pacific Standard Time": "America/Los_Angeles",
    "Eastern Standard Time": "America/New_York", "India Standard Time": "Asia/Kolkata", "W. Europe Standard Time": "Europe/Berlin",
}


class CalendarError(FeishuError):
    """订阅链接打不开或内容不对。沿用外部服务错误的类型，原有的出错处理照常生效。"""


def _unfold(text: str) -> list[str]:
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _zone(name: str | None, fallback: str) -> ZoneInfo:
    for candidate in (WINDOWS_TZ.get(name or "", name), fallback):
        try:
            return ZoneInfo(candidate) if candidate else ZoneInfo(fallback)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


def _when(value: str, params: dict, timezone: str) -> tuple[datetime, bool]:
    """(时间, 是否全天)"""
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        day = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        return datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(timezone)), True
    moment = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return moment.replace(tzinfo=UTC), False
    return moment.replace(tzinfo=_zone(params.get("TZID"), timezone)), False


def parse(text: str, timezone: str) -> list[dict]:
    """把 ICS 解析成原始日程（未展开重复）。"""
    events, current = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = {"attendees": [], "exdates": []}
            continue
        if line == "END:VEVENT":
            if current and current.get("start"):
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *raw_params = head.split(";")
        params = dict(p.split("=", 1) for p in raw_params if "=" in p)
        name = name.upper()
        if name == "UID":
            current["uid"] = value
        elif name == "SUMMARY":
            current["summary"] = _unescape(value)
        elif name == "DESCRIPTION":
            current["description"] = _unescape(value)[:2000]
        elif name == "LOCATION":
            current["location"] = _unescape(value) or None
        elif name == "URL":
            current["url"] = value
        elif name == "STATUS":
            current["status"] = value.upper()
        elif name in ("DTSTART", "DTEND"):
            moment, all_day = _when(value, params, timezone)
            current["start" if name == "DTSTART" else "end"] = moment
            if name == "DTSTART":
                current["all_day"] = all_day
        elif name == "RRULE":
            current["rrule"] = value
        elif name == "EXDATE":
            for item in value.split(","):
                current["exdates"].append(_when(item, params, timezone)[0])
        elif name == "RECURRENCE-ID":
            current["recurrence_id"] = _when(value, params, timezone)[0]
        elif name == "ORGANIZER":
            current["organizer"] = params.get("CN", "").strip('"') or value.removeprefix("mailto:")
        elif name == "ATTENDEE":
            who = params.get("CN", "").strip('"') or value.removeprefix("mailto:")
            current["attendees"].append(who)
    return events


def expand(events: list[dict], start: datetime, end: datetime) -> list[dict]:
    """在 [start, end) 窗口里的日程实例：重复日程展开，单独改过的那一次（RECURRENCE-ID）替换对应实例。"""
    overrides = {(e["uid"], e["recurrence_id"]): e for e in events if e.get("recurrence_id") and e.get("uid")}
    out = []
    for event in events:
        if event.get("recurrence_id") or event.get("status") == "CANCELLED":
            continue
        duration = (event.get("end") or event["start"] + timedelta(hours=1)) - event["start"]
        if event.get("rrule"):
            try:
                rule = rrulestr(event["rrule"], dtstart=event["start"])
            except (ValueError, TypeError):
                continue
            starts = rule.between(start - duration, end, inc=True)
        else:
            starts = [event["start"]]
        for moment in starts:
            if moment in event["exdates"]:
                continue
            instance = overrides.get((event.get("uid"), moment), event)
            if instance.get("status") == "CANCELLED":
                continue
            begin = instance["start"] if instance is not event else moment
            finish = (instance.get("end") or begin + duration) if instance is not event else moment + duration
            if finish <= start or begin >= end:
                continue
            out.append({**instance, "start": begin, "end": finish})
    for (uid, _), override in overrides.items():  # 改到了窗口里、原本不在展开结果里的那一次
        if override.get("status") != "CANCELLED" and start <= override["start"] < end and not any(
                o is override or (o.get("uid") == uid and o["start"] == override["start"]) for o in out):
            out.append(override)
    return sorted(out, key=lambda e: e["start"])


async def fetch(url: str, http: httpx.AsyncClient | None = None) -> str:
    client = http or httpx.AsyncClient(timeout=30, follow_redirects=True)
    try:
        response = await client.get(url, headers={"Accept": "text/calendar"})
    except httpx.HTTPError as exc:
        raise CalendarError(f"打不开日历订阅链接：{exc}") from exc
    finally:
        if http is None:
            await client.aclose()
    if response.status_code != 200:
        raise CalendarError(f"日历订阅链接返回 {response.status_code}，可能已失效或需要重新生成")
    if len(response.content) > MAX_BYTES:
        raise CalendarError("日历内容太大（超过 5MB）")
    text = response.text
    if "BEGIN:VCALENDAR" not in text:
        raise CalendarError("这个链接不是日历订阅（ICS）地址")
    return text


async def list_events(account: dict, timezone: str, start: datetime, end: datetime) -> list[dict]:
    """和飞书日历 list_events 一样的结构。"""
    events = expand(parse(await fetch(account["url"]), timezone), start, end)
    return [{
        "event_id": f"{e.get('uid') or e['start'].isoformat()}", "summary": e.get("summary") or "（无标题）",
        "description": e.get("description") or "", "start": e["start"].astimezone(UTC), "end": e["end"].astimezone(UTC) if e.get("end") else None,
        "all_day": bool(e.get("all_day")), "location": e.get("location"),
        "meeting_url": e.get("url") or _meeting_link(e.get("description") or "") or _meeting_link(e.get("location") or ""),
        "organizer": e.get("organizer"), "attendees": e.get("attendees", [])[:20],
        "rsvp": None,  # 只读订阅：不能替他回复邀请
        "app_link": None, "calendar_id": "ics", "base_event_id": e.get("uid"), "organizer_calendar_id": None,
    } for e in events]


def _meeting_link(text: str) -> str | None:
    match = re.search(r"https://(?:meet\.google\.com|teams\.microsoft\.com|[\w.-]*zoom\.us|vc\.feishu\.cn)/\S+", text)
    return match.group(0).rstrip(">)") if match else None
