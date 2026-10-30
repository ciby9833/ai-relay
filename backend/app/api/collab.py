"""工作区内的协作委托：请同事做一件事、接受 / 拒绝 / 提修改、提交、验收。规则见 app/collab.py。"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import collab
from app.deps import SessionDep, UserDep
from app.models import User

router = APIRouter(prefix="/api/collab", tags=["collab"])


def _fail(exc: collab.CollabError):
    raise HTTPException(status_code=409 if isinstance(exc, collab.Stale) else 400, detail=str(exc)) from exc


class Material(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=4000)


class CreateBody(BaseModel):
    assignee_id: str
    title: str = Field(max_length=200)
    brief: str = Field(max_length=8000)
    deliverable: str = Field(max_length=2000)
    acceptance: str | None = Field(default=None, max_length=2000)
    due_at: datetime | None = None
    materials: list[Material] = Field(default_factory=list, max_length=collab.MAX_MATERIALS)


class ActBody(BaseModel):
    action: str
    version: int
    note: str | None = Field(default=None, max_length=4000)
    changes: dict | None = None
    materials: list[Material] | None = None


@router.get("/members")
async def colleagues(session: SessionDep, user: UserDep):
    """可以请的同事（同一工作区、在用、不是自己）。"""
    return [{"id": str(u.id), "name": u.name, "email": u.email} for u in await collab.members(session, user)]


@router.get("")
async def list_mine(session: SessionDep, user: UserDep, closed: bool = False):
    return [await collab.describe(session, user, d, with_log=False) for d in await collab.mine(session, user, include_closed=closed)]


@router.get("/{delegation_id}")
async def detail(delegation_id: int, session: SessionDep, user: UserDep):
    try:
        return await collab.describe(session, user, await collab.get_for(session, user, delegation_id))
    except collab.CollabError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("")
async def create(body: CreateBody, session: SessionDep, user: UserDep):
    assignee = await session.get(User, collab.member_id(body.assignee_id))
    try:
        if assignee is None:
            raise collab.CollabError("成员不存在")
        delegation = await collab.create(session, user, assignee, title=body.title, brief=body.brief, deliverable=body.deliverable,
                                         acceptance=body.acceptance, due_at=body.due_at,
                                         materials=[m.model_dump() for m in body.materials])
    except collab.CollabError as exc:
        _fail(exc)
    await session.commit()
    return await collab.describe(session, user, delegation)


@router.post("/{delegation_id}/act")
async def act(delegation_id: int, body: ActBody, session: SessionDep, user: UserDep):
    try:
        delegation = await collab.act(session, user, delegation_id, body.action, body.version, note=body.note, changes=body.changes,
                                      materials=[m.model_dump() for m in body.materials] if body.materials is not None else None)
    except collab.CollabError as exc:
        await session.rollback()
        _fail(exc)
    await session.commit()
    return await collab.describe(session, user, delegation)
