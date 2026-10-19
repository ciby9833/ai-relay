"""用户授权 Relay “这类事以后直接办”：授权在哪、办过什么、怎么撤销。

授权有两处来源：
- 长期任务（Mission.grants）：在任务卡片上勾选某几类操作；
- 定时任务（ScheduledTask.grants）：确认某次操作时点“以后直接办”，授权只覆盖同一类操作 + 同一个对象
  （哪张多维表格、给谁发消息），换了对象仍要确认。

所有自动执行的操作都标记 auto=True，在“自动办的事”里列出来，能撤销的给撤销按钮。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
from app.models import Mission, PendingAction, ScheduledTask, User


def kind_label(kind: str) -> str:
    from app.proactive.actions import GRANTABLE  # 避免循环导入（actions → items → automation）

    return GRANTABLE.get(kind, kind)


def scope_of(action: PendingAction) -> dict:
    """授权限定到的对象：同一类操作换了对象（另一张表、另一个人）仍要确认。"""
    p = action.payload or {}
    if action.kind == "base_record":
        return {"app_token": p.get("app_token"), "table_id": p.get("table_id")}
    if action.kind == "send_chat":
        return {"receive_id": p.get("receive_id")}
    if action.kind == "send_mail":
        return {"to": p.get("to")}
    return {}


def scope_label(action: PendingAction) -> str:
    p = action.payload or {}
    if action.kind == "base_record":
        return f"《{p.get('table_name') or '多维表格'}》"
    if action.kind in ("send_chat", "send_mail"):
        return f"给 {p.get('to')}"
    return ""


def task_allows(task: ScheduledTask, action: PendingAction) -> bool:
    scope = scope_of(action)
    return any(g.get("kind") == action.kind and g.get("scope") == scope for g in task.grants or [])


def grant_task(task: ScheduledTask, action: PendingAction) -> str:
    """确认这次操作的同时，授权这个定时任务以后直接办同一类、同一个对象的事。"""
    if task_allows(task, action):
        return "已经授权过了"
    label = f"{kind_label(action.kind)}{scope_label(action)}"
    task.grants = (task.grants or []) + [{
        "kind": action.kind, "scope": scope_of(action), "label": label, "granted_at": datetime.now(UTC).isoformat(),
    }]
    return label


# ---------- 撤销 ----------


def undoable(action: PendingAction) -> bool:
    """执行过、还没撤销、并且飞书那边能收回的操作。发出的邮件、审批决定、回复邀请收不回来。"""
    if action.status != "done" or action.undone_at is not None:
        return False
    p = action.payload or {}
    if action.kind == "base_record":
        return bool(p.get("record_id"))
    if action.kind == "send_chat":
        return bool(p.get("message_id")) and action.decided_at is not None and \
            datetime.now(UTC) - action.decided_at < timedelta(hours=24)  # 飞书只能撤回 24 小时内的消息
    if action.kind == "create_task":
        return bool((p.get("task") or {}).get("guid"))
    if action.kind == "create_event":
        return bool((p.get("event") or {}).get("event_id"))
    return False


async def undo(session: AsyncSession, feishu: FeishuClient, user: User, action: PendingAction) -> str:
    """撤销一次已执行的操作：删掉提交的记录、撤回消息、删除建的任务或会议。"""
    from app.sources import bitable, calendar

    if action.user_id != user.id:
        raise PermissionError("不能撤销他人的操作")
    if not undoable(action):
        return "这个操作撤销不了（已经撤销过，或飞书那边收不回来）"
    p = action.payload
    try:
        if action.kind == "base_record":
            await bitable.delete_record(feishu, user, p["app_token"], p["table_id"], p["record_id"])
            result = f"已删除提交到《{p.get('table_name') or '多维表格'}》的记录"
        elif action.kind == "send_chat":
            if p.get("as_user", False):
                await feishu.user_api(user, "DELETE", f"/im/v1/messages/{p['message_id']}")
            else:
                await feishu.tenant_api("DELETE", f"/im/v1/messages/{p['message_id']}")
            result = f"已撤回发给 {p.get('to')} 的消息"
        elif action.kind == "create_task":
            await feishu.user_api(user, "DELETE", f"/task/v2/tasks/{p['task']['guid']}")
            result = "已删除建的飞书任务"
        elif action.kind == "create_event":
            await calendar.delete_event(feishu, user, p["event"]["calendar_id"], p["event"]["event_id"])
            result = "已取消这个会议（参会人会收到取消通知）"
        else:
            return "这个操作撤销不了"
    except FeishuError as exc:
        return f"撤销失败：{exc}"
    action.undone_at = datetime.now(UTC)
    action.result = f"{action.result or ''}（{result}）".strip()
    from app import insights

    await insights.record(session, user, "undo", action=action)
    return result


# ---------- “自动办的事”页面 ----------


async def overview(session: AsyncSession, user: User, days: int = 30) -> dict:
    """当前有哪些授权（可以收回），最近自动办了什么（能撤销的可以撤销）。"""
    grants = []
    missions = (await session.execute(
        select(Mission).where(Mission.user_id == user.id, Mission.status.in_(("active", "waiting", "asking")))
    )).scalars().all()
    for mission in missions:
        for kind in mission.grants or []:
            grants.append({"source": "mission", "source_id": mission.id, "source_title": mission.title,
                           "kind": kind, "label": kind_label(kind), "granted_at": None})
    tasks = (await session.execute(
        select(ScheduledTask).where(ScheduledTask.user_id == user.id, ScheduledTask.enabled)
    )).scalars().all()
    for task in tasks:
        for index, grant in enumerate(task.grants or []):
            grants.append({"source": "task", "source_id": task.id, "source_title": task.title, "kind": grant["kind"],
                           "index": index, "label": grant.get("label") or kind_label(grant["kind"]),
                           "granted_at": grant.get("granted_at")})
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (await session.execute(
        select(PendingAction).where(PendingAction.user_id == user.id, PendingAction.auto, PendingAction.created_at >= since)
        .order_by(PendingAction.id.desc()).limit(100)
    )).scalars().all()
    titles = {("mission", m.id): m.title for m in missions} | {("task", t.id): t.title for t in tasks}
    history = [{
        "action_id": a.id, "kind": a.kind, "summary": a.summary, "status": a.status, "result": a.result,
        "at": (a.decided_at or a.created_at).isoformat(),
        "source": "mission" if a.mission_id else "task" if a.scheduled_task_id else None,
        "source_title": titles.get(("mission", a.mission_id)) or titles.get(("task", a.scheduled_task_id)),
        "undoable": undoable(a), "undone_at": a.undone_at.isoformat() if a.undone_at else None,
    } for a in rows]
    return {"grants": grants, "history": history}


async def revoke(session: AsyncSession, user: User, source: str, source_id: int, kind: str, index: int | None = None) -> str:
    if source == "mission":
        mission = await session.get(Mission, source_id)
        if mission is None or mission.user_id != user.id:
            raise PermissionError("没有找到这个任务")
        mission.grants = [g for g in mission.grants or [] if g != kind]
        return f"已收回《{mission.title}》的授权：{kind_label(kind)}"
    task = await session.get(ScheduledTask, source_id)
    if task is None or task.user_id != user.id:
        raise PermissionError("没有找到这个定时任务")
    grants = list(task.grants or [])
    if index is not None and 0 <= index < len(grants) and grants[index]["kind"] == kind:
        removed = grants.pop(index)
    else:
        removed = next((g for g in grants if g["kind"] == kind), None)
        grants = [g for g in grants if g is not removed]
    task.grants = grants
    return f"已收回《{task.title}》的授权：{(removed or {}).get('label') or kind_label(kind)}"
