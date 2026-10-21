"""长期任务：查看、授权、回答、立即推进、取消。"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversations import mission_json
from app.deps import SessionDep, UserDep
from app.missions import service
from app.models import Mission, User
from app.proactive.actions import GRANTABLE

router = APIRouter(prefix="/api/missions", tags=["missions"])


async def _own(session: AsyncSession, user: User, mission_id: int) -> Mission:
    mission = await session.get(Mission, mission_id)
    if mission is None or mission.user_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return mission


@router.get("")
async def list_missions(session: SessionDep, user: UserDep):
    missions = (await session.execute(
        select(Mission).where(Mission.user_id == user.id).order_by(Mission.updated_at.desc()).limit(50)
    )).scalars().all()
    return {
        "missions": [await mission_json(session, m) for m in missions],
        "grantable": GRANTABLE,
    }


@router.get("/{mission_id}")
async def get_mission(mission_id: int, session: SessionDep, user: UserDep):
    return await mission_json(session, await _own(session, user, mission_id), logs=50)


class GrantsBody(BaseModel):
    grants: list[str]


@router.put("/{mission_id}/grants")
async def set_grants(mission_id: int, body: GrantsBody, session: SessionDep, user: UserDep):
    """用户为这个任务预先授权自动执行的操作类型（只能由用户在界面上设置，模型不能自己授权）。"""
    mission = await _own(session, user, mission_id)
    unknown = set(body.grants) - set(GRANTABLE)
    if unknown:
        raise HTTPException(status_code=400, detail=f"不支持授权：{'、'.join(unknown)}")
    mission.grants = sorted(set(body.grants))
    names = "、".join(GRANTABLE[g] for g in mission.grants) or "无"
    await service.log(session, mission, "step", f"你更新了自动执行授权：{names}")
    await session.commit()
    return {"grants": mission.grants}


class CriteriaBody(BaseModel):
    criteria: list[str] = Field(min_length=1, max_length=6)


@router.put("/{mission_id}/criteria")
async def set_criteria(mission_id: int, body: CriteriaBody, session: SessionDep, user: UserDep):
    """用户改验收清单（做到什么才算办成）。只有用户能改，Relay 在任务里只能标记状态和证据。"""
    from app.missions import criteria

    mission = await _own(session, user, mission_id)
    if mission.status not in service.OPEN:
        raise HTTPException(status_code=400, detail="任务已经结束")
    try:
        criteria.replace_texts(mission, body.criteria)
    except criteria.CriteriaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await service.log(session, mission, "step", "你改了验收清单：" + "；".join(c["text"] for c in mission.criteria))
    await session.commit()
    return {"criteria": mission.criteria}


class AnswerBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/{mission_id}/answer")
async def answer(mission_id: int, body: AnswerBody, session: SessionDep, user: UserDep):
    mission = await _own(session, user, mission_id)
    if mission.status not in service.OPEN:
        raise HTTPException(status_code=400, detail="任务已经结束")
    await service.answer(session, mission, body.text)
    await session.commit()
    return {"ok": True}


@router.post("/{mission_id}/wake")
async def wake(mission_id: int, session: SessionDep, user: UserDep):
    """让任务马上醒来看一次。"""
    mission = await _own(session, user, mission_id)
    if mission.status not in service.OPEN:
        raise HTTPException(status_code=400, detail="任务已经结束")
    mission.status, mission.wait_for, mission.next_run_at = "active", None, datetime.now(UTC)
    await service.log(session, mission, "step", "你让它马上推进一次")
    await session.commit()
    return {"ok": True}


@router.post("/{mission_id}/cancel")
async def cancel(mission_id: int, session: SessionDep, user: UserDep):
    mission = await _own(session, user, mission_id)
    mission.status, mission.result = "cancelled", "你取消了这个任务"
    mission.updated_at = datetime.now(UTC)
    await service.log(session, mission, "done", "已取消")
    await session.commit()
    return {"ok": True}
