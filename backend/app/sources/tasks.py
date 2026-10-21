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


# ---------- 别人在飞书任务里派给他的事 ----------

# 列任务只能用用户身份，权限二选一（官方文档：GET /task/v2/tasks，type=my_tasks）
SCOPES = ("task:task:read", "task:task:write")
MAX_PAGES = 4


async def my_open_tasks(feishu: FeishuClient, user: User) -> list[dict]:
    tasks, page_token = [], None
    for _ in range(MAX_PAGES):
        params = {"type": "my_tasks", "completed": "false", "page_size": 100, "user_id_type": "open_id"}
        if page_token:
            params["page_token"] = page_token
        data = await feishu.user_api(user, "GET", "/task/v2/tasks", params=params)
        tasks += data.get("items") or []
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return tasks


async def sync(session, feishu: FeishuClient, user: User, state) -> int:
    """别人派给他、还没完成的任务记成信号；之前记下的任务不在“未完成”里了，就是他完成了（或被取消），标为结束。

    他自己给自己建的任务不提醒（他本来就知道）。第一次同步只静默建档。
    """
    from datetime import UTC

    from sqlalchemy import select

    from app.models import Signal
    from app.sources.base import add_signal
    from app.sources.org import Org

    first = not (state.cursor or {}).get("synced")
    org = Org(feishu, user)
    open_tasks = await my_open_tasks(feishu, user)
    seen = set()
    created = 0
    for task in open_tasks:
        guid = task.get("guid")
        creator = (task.get("creator") or {}).get("id")
        if not guid or not creator or creator == user.feishu_open_id:
            continue
        seen.add(guid)
        due = (task.get("due") or {}).get("timestamp")
        created += await add_signal(
            session, user, "task", guid, kind="task", title=task.get("summary") or "（无标题任务）",
            body=(task.get("description") or "")[:2000] or None, url=task.get("url"),
            occurred_at=datetime.fromtimestamp(int(task.get("created_at") or 0) / 1000, UTC) if task.get("created_at") else None,
            status="digest" if first else "notify",
            payload={"guid": guid, "creator_open_id": creator, "creator_name": await org.name(creator),
                     "due": datetime.fromtimestamp(int(due) / 1000, UTC).isoformat() if due else None,
                     "all_day": bool((task.get("due") or {}).get("is_all_day"))},
        )
    # 不在未完成列表里的：他完成了（或任务被删、被移出）
    tracked = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.source == "task", Signal.status.in_(["tracked", "notify", "digest"]))
    )).scalars().all()
    for signal in tracked:
        if signal.external_id not in seen:
            signal.status = "done"
    state.cursor = {**(state.cursor or {}), "synced": True}
    return created
