"""飞书任务：给同事（或自己）建任务。以用户本人身份创建，任务创建者是他自己。"""

from datetime import datetime

from app.feishu.client import FeishuClient
from app.models import User


async def create(
    feishu: FeishuClient, user: User, summary: str, assignee_ids: list[str], due: datetime | None, description: str = ""
) -> dict:
    body: dict = {
        "summary": summary,
        "description": description,
        "members": [{"id": i, "type": "user", "role": "assignee"} for i in assignee_ids],
    }
    if due:
        body["due"] = {"timestamp": str(int(due.timestamp() * 1000)), "is_all_day": False}
    data = await feishu.user_api(user, "POST", "/task/v2/tasks", params={"user_id_type": "open_id"}, json=body)
    task = data.get("task") or {}
    return {"guid": task.get("guid"), "url": task.get("url")}
