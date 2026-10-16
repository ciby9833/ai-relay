"""考勤：上班或下班缺卡时提醒。以应用身份查询，需要用户的 employee user_id。"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
from app.models import SourceState, User
from app.sources.base import add_signal, ts

CHECK_IN_GRACE = timedelta(minutes=10)
CHECK_OUT_GRACE = timedelta(minutes=30)


async def today_records(feishu: FeishuClient, user: User) -> list[dict]:
    if not user.feishu_user_id:
        raise FeishuError("缺少用户的 user_id：需要开通 contact:user.employee_id:readonly 并重新登录")
    today = int(datetime.now(ZoneInfo(user.timezone)).strftime("%Y%m%d"))
    data = await feishu.tenant_api(
        "POST", "/attendance/v1/user_tasks/query",
        params={"employee_type": "employee_id"},
        json={"user_ids": [user.feishu_user_id], "check_date_from": today, "check_date_to": today},
    )
    results = data.get("user_task_results") or []
    return (results[0].get("records") or []) if results else []


async def sync(session: AsyncSession, feishu: FeishuClient, user: User, state: SourceState) -> int:
    now = datetime.now(UTC)
    day = datetime.now(ZoneInfo(user.timezone)).strftime("%Y-%m-%d")
    created = 0
    for index, record in enumerate(await today_records(feishu, user)):
        check_in_at, check_out_at = ts(record.get("check_in_shift_time")), ts(record.get("check_out_shift_time"))
        if (
            record.get("check_in_result") == "Lack" and check_in_at
            and check_in_at + CHECK_IN_GRACE < now < (check_out_at or now + timedelta(hours=1))
        ):
            created += await add_signal(
                session, user, "attendance", f"{day}:{index}:in",
                kind="attendance_missing", title="还没有打上班卡",
                body=f"班次上班时间 {check_in_at.astimezone(ZoneInfo(user.timezone)):%H:%M}",
                occurred_at=now, status="notify", importance="urgent",
            )
        if (
            record.get("check_out_result") == "Lack" and check_out_at
            and check_out_at + CHECK_OUT_GRACE < now < check_out_at + timedelta(hours=4)
        ):
            created += await add_signal(
                session, user, "attendance", f"{day}:{index}:out",
                kind="attendance_missing", title="还没有打下班卡",
                body=f"班次下班时间 {check_out_at.astimezone(ZoneInfo(user.timezone)):%H:%M}",
                occurred_at=now, status="notify", importance="urgent",
            )
    return created
