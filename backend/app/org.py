"""组织架构：部门（树）、成员资料（部门、上级、岗位、负责什么）、团队，以及从飞书通讯录同步。

用途只有三个（见 docs/SYSTEM_DESIGN.md 第〇、二节）：
- 判断重要程度：上级链的事优先（attention 用 manager_chain）；
- 可见范围：团队负责人只看团队成员的事项数量，不看内容；管理员看工作区统计；
- 给助理背景：同事是谁、在哪个部门、负责什么。
不用于派任务。

规则：
- Relay 自己的组织架构是权威；飞书通讯录是同步来源。手工改过的字段记进 locks，同步时不覆盖。
- 上下级、部门上下级不能成环；上级必须是同一工作区的成员。
- 管理员能改所有人的组织资料；成员只能改自己的岗位和“负责什么”。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Department, FollowUp, Team, TeamMember, User

MEMBER_FIELDS = ("department_id", "manager_id", "title", "responsibilities")
SELF_FIELDS = ("title", "responsibilities")
CHAIN_DEPTH = 4


class OrgError(Exception):
    """给用户看的话。"""


# ---------- 读 ----------

async def members(session: AsyncSession, tenant_id: uuid.UUID, active_only: bool = True) -> list[User]:
    statement = select(User).where(User.tenant_id == tenant_id)
    if active_only:
        statement = statement.where(User.status == "active")
    return list((await session.execute(statement.order_by(User.name))).scalars())


async def departments(session: AsyncSession, tenant_id: uuid.UUID) -> list[Department]:
    return list((await session.execute(select(Department).where(Department.tenant_id == tenant_id).order_by(Department.name))).scalars())


async def manager_chain(session: AsyncSession, user: User, depth: int = CHAIN_DEPTH) -> list[dict]:
    """他的上级链（直属上级在前），按 Relay 的上下级关系。给提醒分级用：open_id / 名字 / 邮箱用来认人。"""
    chain, seen, current = [], {user.id}, user
    for level in range(1, depth + 1):
        if not current.manager_id or current.manager_id in seen:
            break
        boss = await session.get(User, current.manager_id)
        if boss is None or boss.tenant_id != user.tenant_id:
            break
        seen.add(boss.id)
        chain.append({"open_id": boss.feishu_open_id, "name": boss.name, "email": boss.email, "depth": level, "user_id": str(boss.id)})
        current = boss
    return chain


async def profile(session: AsyncSession, user: User) -> dict:
    """一位成员的组织资料（给本人、管理员、助理的上下文用）。"""
    dept = await session.get(Department, user.department_id) if user.department_id else None
    boss = await session.get(User, user.manager_id) if user.manager_id else None
    path = await department_path(session, dept) if dept else []
    return {"department": " / ".join(path) or None, "department_id": str(dept.id) if dept else None,
            "manager": boss.name if boss else None, "manager_id": str(boss.id) if boss else None,
            "title": user.title, "responsibilities": user.responsibilities, "locks": user.org_locks or []}


async def department_path(session: AsyncSession, dept: Department, depth: int = 8) -> list[str]:
    names, seen = [], set()
    while dept is not None and dept.id not in seen and len(names) < depth:
        seen.add(dept.id)
        names.append(dept.name)
        dept = await session.get(Department, dept.parent_id) if dept.parent_id else None
    return names[::-1]


def member_json(user: User) -> dict:
    return {"id": str(user.id), "name": user.name, "email": user.email, "title": user.title,
            "responsibilities": user.responsibilities, "department_id": str(user.department_id) if user.department_id else None,
            "manager_id": str(user.manager_id) if user.manager_id else None, "role": user.role, "status": user.status,
            "feishu": bool(user.feishu_open_id), "locks": user.org_locks or []}


def department_json(dept: Department) -> dict:
    return {"id": str(dept.id), "name": dept.name, "parent_id": str(dept.parent_id) if dept.parent_id else None,
            "lead_id": str(dept.lead_id) if dept.lead_id else None, "source": dept.source, "locks": dept.locks or []}


# ---------- 改 ----------

def _uuid(value) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise OrgError("编号不对") from None


async def _member_of(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> User | None:
    if user_id is None:
        return None
    member = await session.get(User, user_id)
    if member is None or member.tenant_id != tenant_id:
        raise OrgError("这个人不是本工作区的成员")
    return member


async def _department_of(session: AsyncSession, tenant_id: uuid.UUID, dept_id: uuid.UUID | None) -> Department | None:
    if dept_id is None:
        return None
    dept = await session.get(Department, dept_id)
    if dept is None or dept.tenant_id != tenant_id:
        raise OrgError("没有这个部门")
    return dept


async def _check_manager(session: AsyncSession, member: User, manager: User | None) -> None:
    """上级不能是自己，也不能形成环（A 的上级是 B，B 的上级又是 A）。"""
    current, seen = manager, set()
    while current is not None and current.id not in seen:
        if current.id == member.id:
            raise OrgError("上下级关系不能形成循环")
        seen.add(current.id)
        current = await session.get(User, current.manager_id) if current.manager_id else None


async def update_member(session: AsyncSession, actor: User, member: User, changes: dict, *, lock: bool = True) -> User:
    """改组织资料。管理员能改所有字段；本人只能改岗位和“负责什么”。改过的字段加锁，同步不覆盖。"""
    if member.tenant_id != actor.tenant_id:
        raise OrgError("这个人不是本工作区的成员")
    allowed = MEMBER_FIELDS if actor.is_admin else (SELF_FIELDS if actor.id == member.id else ())
    if not allowed:
        raise OrgError("只有管理员能改别人的组织资料")
    for key in changes:
        if key not in allowed:
            raise OrgError("这一项只有管理员能改" if key in MEMBER_FIELDS else "不认识的字段")
    if "department_id" in changes:
        dept = await _department_of(session, actor.tenant_id, _uuid(changes["department_id"]))
        member.department_id = dept.id if dept else None
    if "manager_id" in changes:
        manager = await _member_of(session, actor.tenant_id, _uuid(changes["manager_id"]))
        await _check_manager(session, member, manager)
        member.manager_id = manager.id if manager else None
    for key in ("title", "responsibilities"):
        if key in changes:
            value = (changes[key] or "").strip()
            setattr(member, key, value[:255 if key == "title" else 2000] or None)
    if lock:
        member.org_locks = sorted(set(member.org_locks or []) | set(changes))
    await session.flush()
    return member


async def save_department(session: AsyncSession, actor: User, values: dict, dept: Department | None = None) -> Department:
    if not actor.is_admin:
        raise OrgError("只有管理员能维护部门")
    if dept is None:
        if not (values.get("name") or "").strip():
            raise OrgError("要填部门名称")
        dept = Department(tenant_id=actor.tenant_id, name="", source="manual", locks=[])
        session.add(dept)
    elif dept.tenant_id != actor.tenant_id:
        raise OrgError("没有这个部门")
    changed = set()
    if "name" in values:
        name = (values.get("name") or "").strip()[:255]
        if not name:
            raise OrgError("部门名称不能为空")
        dept.name = name
        changed.add("name")
    if "parent_id" in values:
        parent = await _department_of(session, actor.tenant_id, _uuid(values["parent_id"]))
        current = parent
        while current is not None:  # 不能挂到自己或自己的下级下面
            if dept.id is not None and current.id == dept.id:
                raise OrgError("部门不能挂在自己或自己的下级部门下面")
            current = await session.get(Department, current.parent_id) if current.parent_id else None
        dept.parent_id = parent.id if parent else None
        changed.add("parent_id")
    if "lead_id" in values:
        lead = await _member_of(session, actor.tenant_id, _uuid(values["lead_id"]))
        dept.lead_id = lead.id if lead else None
        changed.add("lead_id")
    if dept.source == "feishu":
        dept.locks = sorted(set(dept.locks or []) | changed)
    dept.updated_at = datetime.now(UTC)
    await session.flush()
    return dept


async def delete_department(session: AsyncSession, actor: User, dept: Department) -> None:
    """删部门：下级部门挂到它的上级，成员的部门清空（不会删人）。"""
    if not actor.is_admin or dept.tenant_id != actor.tenant_id:
        raise OrgError("只有管理员能维护部门")
    for child in (await session.execute(select(Department).where(Department.parent_id == dept.id))).scalars():
        child.parent_id = dept.parent_id
    for member in (await session.execute(select(User).where(User.department_id == dept.id))).scalars():
        member.department_id = None
    await session.delete(dept)
    await session.flush()


# ---------- 团队 ----------

async def teams_of(session: AsyncSession, tenant_id: uuid.UUID) -> list[tuple[Team, list[uuid.UUID]]]:
    rows = list((await session.execute(select(Team).where(Team.tenant_id == tenant_id).order_by(Team.name))).scalars())
    out = []
    for team in rows:
        ids = list((await session.execute(select(TeamMember.user_id).where(TeamMember.team_id == team.id))).scalars())
        out.append((team, ids))
    return out


async def save_team(session: AsyncSession, actor: User, values: dict, team: Team | None = None) -> Team:
    if not actor.is_admin:
        raise OrgError("只有管理员能建立和修改团队")
    if team is None:
        team = Team(tenant_id=actor.tenant_id, name="", created_by=actor.id)
        session.add(team)
    elif team.tenant_id != actor.tenant_id:
        raise OrgError("没有这个团队")
    if "name" in values or not team.name:
        name = (values.get("name") or "").strip()[:255]
        if not name:
            raise OrgError("要填团队名称")
        team.name = name
    if "lead_id" in values:
        lead = await _member_of(session, actor.tenant_id, _uuid(values["lead_id"]))
        team.lead_id = lead.id if lead else None
    await session.flush()
    if "member_ids" in values:
        wanted = {(await _member_of(session, actor.tenant_id, _uuid(v))).id for v in values["member_ids"] or []}
        current = set((await session.execute(select(TeamMember.user_id).where(TeamMember.team_id == team.id))).scalars())
        for user_id in current - wanted:
            await session.delete(await session.get(TeamMember, (team.id, user_id)))
        for user_id in wanted - current:
            session.add(TeamMember(team_id=team.id, user_id=user_id))
    await session.flush()
    return team


async def team_summary(session: AsyncSession, actor: User, team: Team) -> list[dict]:
    """团队负责人看的汇总：每人还没结的事项数、逾期数。只有数字，不含任何事项内容。"""
    if team.tenant_id != actor.tenant_id or not (actor.is_admin or team.lead_id == actor.id):
        raise OrgError("只有团队负责人和管理员能看团队汇总")
    ids = list((await session.execute(select(TeamMember.user_id).where(TeamMember.team_id == team.id))).scalars())
    now = datetime.now(UTC)
    out = []
    for user_id in ids:
        member = await session.get(User, user_id)
        if member is None or member.status != "active":
            continue
        open_count = await session.scalar(select(func.count()).select_from(FollowUp).where(
            FollowUp.user_id == user_id, FollowUp.status == "open", FollowUp.owner == "me"))
        overdue = await session.scalar(select(func.count()).select_from(FollowUp).where(
            FollowUp.user_id == user_id, FollowUp.status == "open", FollowUp.owner == "me", FollowUp.due_at < now))
        waiting = await session.scalar(select(func.count()).select_from(FollowUp).where(
            FollowUp.user_id == user_id, FollowUp.status == "open", FollowUp.owner == "others"))
        out.append({"id": str(user_id), "name": member.name, "open": open_count or 0, "overdue": overdue or 0, "waiting": waiting or 0})
    return out


# ---------- 从飞书通讯录同步 ----------

async def sync_from_feishu(session: AsyncSession, actor: User, feishu) -> dict:
    """用工作区的飞书应用读通讯录：部门树和负责人、本工作区成员的部门 / 上级 / 岗位。

    只同步到已经是 Relay 成员的人（按飞书身份对上）；手工改过的字段不覆盖；同步来的部门标 source=feishu。
    """
    if not actor.is_admin:
        raise OrgError("只有管理员能同步通讯录")
    params = {"department_id_type": "open_department_id", "user_id_type": "open_id", "fetch_child": "true", "page_size": 50}
    raw_depts, token = [], None
    while True:
        data = await feishu.tenant_api("GET", "/contact/v3/departments/0/children", params={**params, **({"page_token": token} if token else {})})
        raw_depts += data.get("items") or []
        token = data.get("page_token") if data.get("has_more") else None
        if not token or len(raw_depts) > 5000:
            break
    by_open = {u.feishu_open_id: u for u in await members(session, actor.tenant_id, active_only=False) if u.feishu_open_id}
    existing = {d.external_id: d for d in await departments(session, actor.tenant_id) if d.external_id}
    stats = {"departments": 0, "members": 0, "skipped_locked": 0}
    now = datetime.now(UTC)
    for raw in raw_depts:
        ext = raw.get("open_department_id")
        if not ext:
            continue
        dept = existing.get(ext)
        if dept is None:
            dept = Department(tenant_id=actor.tenant_id, name=raw.get("name") or "部门", source="feishu", external_id=ext, locks=[])
            session.add(dept)
            existing[ext] = dept
        elif "name" not in (dept.locks or []):
            dept.name = raw.get("name") or dept.name
        dept.updated_at = now
        stats["departments"] += 1
    await session.flush()
    for raw in raw_depts:
        dept = existing.get(raw.get("open_department_id"))
        if dept is None:
            continue
        parent = existing.get(raw.get("parent_department_id"))
        if "parent_id" not in (dept.locks or []):
            dept.parent_id = parent.id if parent and parent.id != dept.id else None
        leader = by_open.get(raw.get("leader_user_id"))
        if leader is not None and "lead_id" not in (dept.locks or []):
            dept.lead_id = leader.id
    # 成员：只查已经在 Relay 的人
    for open_id, member in by_open.items():
        try:
            person = (await feishu.tenant_api("GET", f"/contact/v3/users/{open_id}", params={
                "department_id_type": "open_department_id", "user_id_type": "open_id"})).get("user") or {}
        except Exception:  # noqa: BLE001 - 一个人查不到不影响别人（可能不在应用的通讯录权限范围里）
            continue
        locks = set(member.org_locks or [])
        dept_ids = person.get("department_ids") or []
        if "department_id" not in locks and dept_ids and existing.get(dept_ids[0]):
            member.department_id = existing[dept_ids[0]].id
        boss = by_open.get(person.get("leader_user_id"))
        if "manager_id" not in locks and boss is not None and boss.id != member.id:
            try:
                await _check_manager(session, member, boss)
                member.manager_id = boss.id
            except OrgError:
                pass  # 飞书里的关系会成环：不同步这一条
        if "title" not in locks and person.get("job_title"):
            member.title = person["job_title"][:255]
        stats["skipped_locked"] += len(locks & set(MEMBER_FIELDS))
        stats["members"] += 1
    await session.flush()
    return stats

