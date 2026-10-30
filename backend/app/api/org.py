"""组织架构：部门、成员资料、团队、从飞书通讯录同步。规则见 app/org.py。

本工作区的成员都能看组织架构（谁在哪个部门、岗位、上级、负责什么）；只有管理员能改别人的，成员能改自己的岗位和“负责什么”。
"""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import org
from app.deps import FeishuDep, SessionDep, UserDep
from app.feishu.client import FeishuError, has_feishu
from app.models import Department, Team, User

router = APIRouter(prefix="/api/org", tags=["org"])


def _fail(exc: Exception, status: int = 400):
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("")
async def overview(session: SessionDep, user: UserDep):
    """组织架构：部门树、成员、团队（团队里只有成员名单，不含任何事项）。"""
    teams = [{"id": str(t.id), "name": t.name, "lead_id": str(t.lead_id) if t.lead_id else None,
              "member_ids": [str(i) for i in ids]} for t, ids in await org.teams_of(session, user.tenant_id)]
    return {"departments": [org.department_json(d) for d in await org.departments(session, user.tenant_id)],
            "members": [org.member_json(m) for m in await org.members(session, user.tenant_id)],
            "teams": teams, "me": str(user.id), "can_edit": user.is_admin}


@router.get("/me")
async def my_profile(session: SessionDep, user: UserDep):
    return await org.profile(session, user)


class MemberBody(BaseModel):
    department_id: str | None = None
    manager_id: str | None = None
    title: str | None = Field(default=None, max_length=255)
    responsibilities: str | None = Field(default=None, max_length=2000)


@router.patch("/members/{member_id}")
async def update_member(member_id: uuid.UUID, body: MemberBody, session: SessionDep, user: UserDep):
    member = await session.get(User, member_id)
    if member is None or member.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="没有这个成员")
    try:
        await org.update_member(session, user, member, body.model_dump(exclude_unset=True))
    except org.OrgError as exc:
        _fail(exc, 403 if "只有管理员" in str(exc) else 400)
    await session.commit()
    return org.member_json(member)


class DepartmentBody(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    parent_id: str | None = None
    lead_id: str | None = None


async def _department(session, user, dept_id: uuid.UUID) -> Department:
    dept = await session.get(Department, dept_id)
    if dept is None or dept.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="没有这个部门")
    return dept


@router.post("/departments")
async def create_department(body: DepartmentBody, session: SessionDep, user: UserDep):
    try:
        dept = await org.save_department(session, user, body.model_dump(exclude_unset=True))
    except org.OrgError as exc:
        _fail(exc, 403 if "只有管理员" in str(exc) else 400)
    await session.commit()
    return org.department_json(dept)


@router.patch("/departments/{dept_id}")
async def update_department(dept_id: uuid.UUID, body: DepartmentBody, session: SessionDep, user: UserDep):
    dept = await _department(session, user, dept_id)
    try:
        await org.save_department(session, user, body.model_dump(exclude_unset=True), dept)
    except org.OrgError as exc:
        _fail(exc, 403 if "只有管理员" in str(exc) else 400)
    await session.commit()
    return org.department_json(dept)


@router.delete("/departments/{dept_id}")
async def delete_department(dept_id: uuid.UUID, session: SessionDep, user: UserDep):
    dept = await _department(session, user, dept_id)
    try:
        await org.delete_department(session, user, dept)
    except org.OrgError as exc:
        _fail(exc, 403)
    await session.commit()
    return {"ok": True}


class TeamBody(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    lead_id: str | None = None
    member_ids: list[str] | None = Field(default=None, max_length=500)


async def _team(session, user, team_id: uuid.UUID) -> Team:
    team = await session.get(Team, team_id)
    if team is None or team.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="没有这个团队")
    return team


@router.post("/teams")
async def create_team(body: TeamBody, session: SessionDep, user: UserDep):
    try:
        team = await org.save_team(session, user, body.model_dump(exclude_unset=True))
    except org.OrgError as exc:
        _fail(exc, 403 if "只有管理员" in str(exc) else 400)
    await session.commit()
    return {"id": str(team.id), "name": team.name}


@router.patch("/teams/{team_id}")
async def update_team(team_id: uuid.UUID, body: TeamBody, session: SessionDep, user: UserDep):
    team = await _team(session, user, team_id)
    try:
        await org.save_team(session, user, body.model_dump(exclude_unset=True), team)
    except org.OrgError as exc:
        _fail(exc, 403 if "只有管理员" in str(exc) else 400)
    await session.commit()
    return {"id": str(team.id), "name": team.name}


@router.delete("/teams/{team_id}")
async def delete_team(team_id: uuid.UUID, session: SessionDep, user: UserDep):
    team = await _team(session, user, team_id)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员能删除团队")
    await session.delete(team)
    await session.commit()
    return {"ok": True}


@router.get("/teams/{team_id}/summary")
async def team_summary(team_id: uuid.UUID, session: SessionDep, user: UserDep):
    """团队负责人 / 管理员：每人的事项数量（要处理、逾期、在等别人），不含内容。"""
    team = await _team(session, user, team_id)
    try:
        return await org.team_summary(session, user, team)
    except org.OrgError as exc:
        _fail(exc, 403)


@router.post("/sync-feishu")
async def sync_feishu(session: SessionDep, user: UserDep, feishu: FeishuDep):
    """管理员：从工作区的飞书通讯录同步部门树和成员的部门 / 上级 / 岗位（手工改过的不覆盖）。"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员能同步通讯录")
    if not has_feishu(feishu):
        raise HTTPException(status_code=400, detail="这个工作区还没有接入飞书")
    try:
        stats = await org.sync_from_feishu(session, user, feishu)
    except FeishuError as exc:
        raise HTTPException(status_code=400, detail=f"读取飞书通讯录失败：{exc}") from exc
    await session.commit()
    return stats
