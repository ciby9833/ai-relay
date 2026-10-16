"""记忆和定时任务的查看与删除：用户必须能看到助手记了什么、会在什么时候主动找他。"""

from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select

from app.deps import SessionDep, UserDep
from app.memory import service as memory_service
from app.models import ScheduledTask

router = APIRouter(prefix="/api", tags=["assistant"])


@router.get("/memories")
async def list_memories(session: SessionDep, user: UserDep):
    memories = await memory_service.list_memories(session, user.id)
    return [
        {
            "id": m.id,
            "kind": m.kind,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in memories
    ]


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, session: SessionDep, user: UserDep):
    if not await memory_service.delete_memory(session, user.id, memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    await session.commit()
    return {"ok": True}


@router.get("/tasks")
async def list_tasks(session: SessionDep, user: UserDep):
    result = await session.execute(
        select(ScheduledTask).where(ScheduledTask.user_id == user.id).order_by(ScheduledTask.id)
    )
    return [
        {
            "id": t.id,
            "title": t.title,
            "prompt": t.prompt,
            "cron": t.cron,
            "enabled": t.enabled,
            "next_run_at": t.next_run_at.astimezone(ZoneInfo(t.timezone)).isoformat()
            if t.next_run_at
            else None,
        }
        for t in result.scalars()
    ]


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, session: SessionDep, user: UserDep):
    result = await session.execute(
        delete(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.user_id == user.id)
    )
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="任务不存在")
    await session.commit()
    return {"ok": True}
