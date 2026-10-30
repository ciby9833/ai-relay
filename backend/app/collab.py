"""工作区内的协作委托：一个人（或他的助理替他）请同事做一件事，同事接受后完成并提交，请求方验收。

规则（见 docs/ASSISTANT_ARCHITECTURE.md 第 8 节）：
- 只在同一个工作区的在用成员之间；不能请自己，不跨公司。
- 委托本身是协作状态唯一的权威。双方“待处理”里各有一件事（key = collab:<id>）引用它，跟着它变；
  在“待处理”里点“完成”不能替代提交或验收。
- 只有承接方本人能接受、拒绝、提修改、提交；只有请求方本人能同意修改、改要求、验收、退回、取消。
  助理在对话里准备这些操作，都要本人确认后才执行（PendingAction kind = collab）。
- 双方的私人对话、记忆、账号权限不共享：对方能看到的只有委托里明确写的内容、共享的材料和提交的结果。
- 每次变化版本号 +1，操作要带上看到的版本：重复点击、基于旧状态的操作不会执行两次。
- 没约定期限就是没有期限，不替人编日期。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Delegation, DelegationEvent, FollowUp, User

OPEN_STATES = ("requested", "countered", "accepted", "submitted", "returned")
CLOSED_STATES = ("completed", "declined", "cancelled")
MAX_MATERIALS = 10
STATUS_TEXT = {
    "requested": "等对方回应", "countered": "对方提出了修改", "accepted": "进行中", "submitted": "已提交，等验收",
    "returned": "已退回修改", "completed": "已完成", "declined": "已拒绝", "cancelled": "已取消",
}

# 谁能做什么、从哪个状态出发
ASSIGNEE_ACTIONS = {"accept": ("requested",), "decline": ("requested", "countered"), "counter": ("requested",),
                    "submit": ("accepted", "returned")}
REQUESTER_ACTIONS = {"agree": ("countered",), "revise": ("requested", "countered"), "approve": ("submitted",),
                     "return": ("submitted",), "cancel": OPEN_STATES}
NOTE_REQUIRED = {"decline": "拒绝要说明理由", "return": "退回要说明哪里需要改", "counter": "提修改要说明为什么",
                 "submit": "提交要写明交付了什么"}


class CollabError(Exception):
    """不能执行的协作操作（给用户看的话）。"""


class Stale(CollabError):
    """委托已经变了（对方刚操作过，或者重复点击）。"""


def _clean_materials(items) -> list[dict]:
    """只保留明确给出的材料：标题 + 链接（只认 https）或一段文字。不接受本地路径，对方打不开。"""
    out = []
    for raw in (items or [])[:MAX_MATERIALS]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()[:200]
        url = str(raw.get("url") or "").strip()
        text = str(raw.get("text") or "").strip()[:4000]
        if url and not url.startswith("https://"):
            raise CollabError(f"材料「{title or url}」不是对方能打开的链接（只支持 https 链接，本地文件请先上传或贴内容）")
        if not (url or text):
            continue
        out.append({"title": title or (url or text[:30]), **({"url": url} if url else {}), **({"text": text} if text else {})})
    return out


def _due(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            raise CollabError("期限需要是日期时间，例如 2026-11-05T18:00") from None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def members(session: AsyncSession, user: User) -> list[User]:
    """可以请的同事：同一个工作区、在用、不是自己。"""
    rows = await session.execute(select(User).where(User.tenant_id == user.tenant_id, User.status == "active", User.id != user.id)
                                 .order_by(User.name))
    return list(rows.scalars())


async def find_member(session: AsyncSession, user: User, query: str) -> User:
    """按名字或邮箱在本工作区成员里找人。找不到或同名多人时说清楚。"""
    q = (query or "").strip().lstrip("@").lower()
    if not q:
        raise CollabError("要说明请谁")
    people = await members(session, user)
    exact = [p for p in people if (p.name or "").lower() == q or (p.email or "").lower() == q]
    found = exact or [p for p in people if q in (p.name or "").lower() or q in (p.email or "").lower()]
    if not found:
        raise CollabError(f"这个工作区里没有叫「{query}」的成员（只能请同一工作区的同事；对方需要先加入工作区）")
    if len(found) > 1:
        raise CollabError(f"「{query}」有多位：{'、'.join(p.name for p in found[:6])}，请说明是哪一位")
    return found[0]


async def get_for(session: AsyncSession, user: User, delegation_id: int, lock: bool = False) -> Delegation:
    """只有双方本人能看到这份委托。"""
    statement = select(Delegation).where(Delegation.id == delegation_id, Delegation.tenant_id == user.tenant_id,
                                          or_(Delegation.requester_id == user.id, Delegation.assignee_id == user.id))
    if lock:
        statement = statement.with_for_update()
    delegation = (await session.execute(statement)).scalars().first()
    if delegation is None:
        raise CollabError("找不到这份协作（只有请求方和承接方能看到）")
    return delegation


async def mine(session: AsyncSession, user: User, include_closed: bool = False) -> list[Delegation]:
    statement = select(Delegation).where(Delegation.tenant_id == user.tenant_id,
                                         or_(Delegation.requester_id == user.id, Delegation.assignee_id == user.id))
    if not include_closed:
        statement = statement.where(Delegation.status.in_(OPEN_STATES))
    return list((await session.execute(statement.order_by(Delegation.updated_at.desc()).limit(100))).scalars())


async def _log(session: AsyncSession, delegation: Delegation, actor: User | None, kind: str, note: str | None = None, **data) -> None:
    session.add(DelegationEvent(delegation_id=delegation.id, actor_id=actor.id if actor else None, kind=kind,
                                note=note, data={k: v for k, v in data.items() if v is not None}))


async def create(session: AsyncSession, requester: User, assignee: User, *, title: str, brief: str, deliverable: str,
                 acceptance: str | None = None, due_at=None, materials=None) -> Delegation:
    if requester.status != "active":
        raise CollabError("你的账号已停用")
    if assignee.id == requester.id:
        raise CollabError("不能请自己")
    if assignee.tenant_id != requester.tenant_id or assignee.status != "active":
        raise CollabError("只能请同一个工作区里在用的同事")
    title, brief, deliverable = (title or "").strip()[:200], (brief or "").strip(), (deliverable or "").strip()
    if not title or not brief or not deliverable:
        raise CollabError("要写清楚：标题、要做什么、交付什么")
    delegation = Delegation(tenant_id=requester.tenant_id, requester_id=requester.id, assignee_id=assignee.id, title=title,
                            brief=brief[:8000], deliverable=deliverable[:2000], acceptance=(acceptance or "").strip()[:2000] or None,
                            due_at=_due(due_at), materials=_clean_materials(materials), status="requested", version=1)
    session.add(delegation)
    await session.flush()
    await _log(session, delegation, requester, "request")
    await sync_items(session, delegation)
    return delegation


async def act(session: AsyncSession, user: User, delegation_id: int, action: str, version: int | None, *,
              note: str | None = None, changes: dict | None = None, materials=None) -> Delegation:
    """执行一次协作操作。version 是操作人看到的版本：对不上说明已经变了（或重复点击），不执行。"""
    delegation = await get_for(session, user, delegation_id, lock=True)
    role = "assignee" if delegation.assignee_id == user.id else "requester"
    allowed = ASSIGNEE_ACTIONS if role == "assignee" else REQUESTER_ACTIONS
    if action not in allowed:
        other = "请求方" if role == "assignee" else "承接方"
        raise CollabError(f"这一步只有{other}本人能做")
    if version is not None and version != delegation.version:
        raise Stale("这份协作刚有变化，请刷新后再操作")
    if delegation.status not in allowed[action]:
        raise CollabError(f"现在是「{STATUS_TEXT.get(delegation.status, delegation.status)}」，不能这样操作")
    note = (note or "").strip()[:4000] or None
    if action in NOTE_REQUIRED and not note:
        raise CollabError(NOTE_REQUIRED[action])
    now = datetime.now(UTC)
    changes = changes or {}
    # 先把输入都检查完，再改委托：任何一项不合格都不留下改了一半的状态
    new_due = _due(changes.get("due_at")) if "due_at" in changes else None
    clean = _clean_materials(materials) if materials is not None else None
    if action == "accept":
        delegation.status = "accepted"
    elif action == "decline":
        delegation.status = "declined"
    elif action == "counter":
        proposal = {k: str(v).strip() for k, v in changes.items() if k in ("deliverable", "acceptance") and v}
        if new_due is not None:
            proposal["due_at"] = new_due.isoformat()
        delegation.proposal, delegation.status = {**proposal, "note": note}, "countered"
    elif action == "agree":
        proposal = delegation.proposal or {}
        for key in ("deliverable", "acceptance"):
            if proposal.get(key):
                setattr(delegation, key, proposal[key])
        if proposal.get("due_at"):
            delegation.due_at = _due(proposal["due_at"])
        delegation.status, delegation.proposal = "accepted", None  # 承接方提的条件，请求方同意了：双方都认可，直接开始
    elif action == "revise":
        for key in ("brief", "deliverable", "acceptance", "title"):
            if changes.get(key):
                setattr(delegation, key, str(changes[key]).strip())
        if "due_at" in changes:
            delegation.due_at = new_due
        if clean is not None:
            delegation.materials = clean
        delegation.status, delegation.proposal = "requested", None  # 要求变了：要对方重新接受，不能替他承诺
    elif action == "submit":
        delegation.submission = {"note": note, "materials": clean or [], "at": now.isoformat()}
        delegation.status = "submitted"
    elif action == "approve":
        delegation.status = "completed"
    elif action == "return":
        delegation.status = "returned"
    elif action == "cancel":
        delegation.status = "cancelled"
    if delegation.status in CLOSED_STATES:
        delegation.closed_at = now
    delegation.version += 1
    delegation.updated_at = now
    await _log(session, delegation, user, action, note, changes=changes or None)
    await sync_items(session, delegation, previous_actor=user)
    return delegation


# ---------- 双方“待处理”里的事项：跟着委托变 ----------

def _views(d: Delegation, requester: str, assignee: str) -> dict[str, tuple | None]:
    """每个状态下双方各看到什么：(球在谁那 me/others, 下一步, 要不要告诉他) ；None 表示这件事对他已经结束。"""
    sub = (d.submission or {}).get("note")
    return {
        "requested": {"requester": ("others", f"等 {assignee} 接受", False),
                      "assignee": ("me", f"{requester} 请你：{d.deliverable}。接受、拒绝，或提出修改", True)},
        "countered": {"requester": ("me", f"{assignee} 提出修改：{(d.proposal or {}).get('note') or ''}。同意，或改要求", True),
                      "assignee": ("others", f"等 {requester} 回应你提的修改", False)},
        "accepted": {"requester": ("others", f"{assignee} 已接受，在做", True),
                     "assignee": ("me", f"做完后把结果提交给 {requester}：{d.deliverable}", False)},
        "submitted": {"requester": ("me", f"{assignee} 提交了：{sub or ''}。验收通过，或退回修改", True),
                      "assignee": ("others", f"等 {requester} 验收", False)},
        "returned": {"requester": ("others", f"已退回，等 {assignee} 修改后再提交", False),
                     "assignee": ("me", f"{requester} 退回了，按意见修改后再提交", True)},
    }.get(d.status, {})


RESOLUTIONS = {"completed": ("done", "验收通过"), "declined": ("dismissed", "对方拒绝了"), "cancelled": ("dismissed", "请求方取消了")}


async def sync_items(session: AsyncSession, d: Delegation, previous_actor: User | None = None) -> None:
    """按委托现在的状态更新双方的事项。轮到谁、需要他知道的，标成“还没告诉他”，由常规提醒流程（含飞书）告诉他一次。"""
    requester = await session.get(User, d.requester_id)
    assignee = await session.get(User, d.assignee_id)
    views = _views(d, requester.name, assignee.name)
    now = datetime.now(UTC)
    for role, person, counterpart in (("requester", requester, assignee), ("assignee", assignee, requester)):
        key = f"collab:{d.id}"
        item = (await session.execute(select(FollowUp).where(FollowUp.user_id == person.id, FollowUp.key == key))).scalars().first()
        view = views.get(role)
        if item is None:
            if view is None:
                continue
            item = FollowUp(user_id=person.id, key=key, kind="collab", owner=view[0], title=d.title, signal_ids=[])
            session.add(item)
        item.title, item.due_at, item.waiting_on = d.title, d.due_at, counterpart.name
        item.facets = {**(item.facets or {}), "delegation_id": d.id, "role": role, "counterpart": counterpart.name,
                       "collab_status": d.status, "version": d.version}
        item.updated_at = now
        if view is not None:
            owner, step, tell = view
            item.owner, item.next_step, item.summary = owner, step, d.brief[:500]
            item.status, item.closed_at, item.resolution = "open", None, None
            # 自己刚做的操作不用再告诉自己；轮到他、或者对方有了结果，才告诉他
            mine_now = previous_actor is not None and previous_actor.id == person.id
            item.announced_at = now if (mine_now or not tell) else None
        else:
            status, why = RESOLUTIONS.get(d.status, ("done", STATUS_TEXT.get(d.status, "")))
            actor_is_me = previous_actor is not None and previous_actor.id == person.id
            if d.status == "declined" and role == "requester":
                # 被拒绝了：请求方要知道，自己决定另找人还是放下
                item.owner, item.status, item.closed_at, item.resolution = "me", "open", None, None
                item.next_step = f"{assignee.name} 拒绝了：{await _last_note(session, d)}。另找人，或者放下"
                item.announced_at = None
            elif d.status == "cancelled" and role == "assignee" and not actor_is_me and await _was_accepted(session, d):
                # 他已经接了（可能在做或已提交），请求方取消了：告诉他一声不用再做
                item.owner, item.status, item.closed_at, item.resolution = "me", "open", None, None
                item.next_step = f"{requester.name} 取消了这个请求，不用再做了"
                item.announced_at = None
            elif d.status == "completed" and role == "assignee":
                item.status, item.resolution, item.closed_at = status, f"{requester.name} 验收通过", now
                item.next_step = None
            else:
                item.status, item.resolution, item.closed_at = status, why, now
    await session.flush()


async def _last_note(session: AsyncSession, d: Delegation) -> str:
    note = await session.scalar(select(DelegationEvent.note).where(DelegationEvent.delegation_id == d.id)
                                .order_by(DelegationEvent.id.desc()).limit(1))
    return note or "没写理由"


async def _was_accepted(session: AsyncSession, d: Delegation) -> bool:
    return bool(await session.scalar(select(DelegationEvent.id).where(
        DelegationEvent.delegation_id == d.id, DelegationEvent.kind.in_(("accept", "agree"))).limit(1)))


def closable_from_board(item: FollowUp) -> bool:
    """“待处理”里的协作事项：委托还没结束时，不能用“完成/不跟进”代替提交或验收。"""
    return (item.facets or {}).get("collab_status") in CLOSED_STATES


# ---------- 给前端和助理看 ----------

async def describe(session: AsyncSession, user: User, d: Delegation, with_log: bool = True) -> dict:
    requester = await session.get(User, d.requester_id)
    assignee = await session.get(User, d.assignee_id)
    role = "requester" if d.requester_id == user.id else "assignee"
    allowed = REQUESTER_ACTIONS if role == "requester" else ASSIGNEE_ACTIONS
    data = {
        "id": d.id, "title": d.title, "brief": d.brief, "deliverable": d.deliverable, "acceptance": d.acceptance,
        "due_at": d.due_at.isoformat() if d.due_at else None, "materials": d.materials or [], "status": d.status,
        "status_text": ROLE_STATUS.get(d.status, {}).get(role) or STATUS_TEXT.get(d.status, d.status), "proposal": d.proposal, "submission": d.submission,
        "version": d.version, "role": role,
        "requester": {"id": str(requester.id), "name": requester.name}, "assignee": {"id": str(assignee.id), "name": assignee.name},
        "actions": [a for a, states in allowed.items() if d.status in states],
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
    if with_log:
        names = {requester.id: requester.name, assignee.id: assignee.name}
        events = (await session.execute(select(DelegationEvent).where(DelegationEvent.delegation_id == d.id)
                                        .order_by(DelegationEvent.id))).scalars()
        data["log"] = [{"kind": e.kind, "who": names.get(e.actor_id, "—"), "note": e.note,
                        "at": e.created_at.isoformat() if e.created_at else None} for e in events]
    return data


def as_text(data: dict) -> str:
    """给助理读的版本：只有委托里明确写的内容，不含任何一方的私人对话或记忆。"""
    lines = [f"协作 #{data['id']}《{data['title']}》—— {data['status_text']}",
             f"请求方：{data['requester']['name']}；承接方：{data['assignee']['name']}（你是{'请求方' if data['role'] == 'requester' else '承接方'}）",
             f"要做什么：{data['brief']}", f"交付：{data['deliverable']}",
             f"验收：{data['acceptance'] or '没写'}", f"期限：{data['due_at'] or '未约定'}"]
    for m in data["materials"]:
        lines.append(f"共享材料：{m['title']}" + (f" {m['url']}" if m.get("url") else "") + (f"\n{m['text']}" if m.get("text") else ""))
    if data.get("proposal"):
        lines.append(f"承接方提出的修改：{data['proposal']}")
    if data.get("submission"):
        lines.append(f"提交的结果：{data['submission'].get('note')}")
        for m in data["submission"].get("materials") or []:
            lines.append(f"提交的材料：{m['title']}" + (f" {m['url']}" if m.get("url") else "") + (f"\n{m['text']}" if m.get("text") else ""))
    lines.append(f"你现在能做的：{'、'.join(data['actions']) or '没有（等对方，或已经结束）'}（版本 {data['version']}）")
    return "\n".join(lines)


# 状态说给谁听：同一个状态，请求方和承接方看到的话不一样
ROLE_STATUS = {
    "requested": {"requester": "等对方接受", "assignee": "等你回应"},
    "countered": {"requester": "对方提出了修改", "assignee": "等对方回应你的修改"},
    "submitted": {"requester": "已提交，等你验收", "assignee": "已提交，等对方验收"},
    "returned": {"requester": "已退回，等对方修改", "assignee": "被退回，需要修改"},
}

ACTION_TEXT = {"accept": "接受", "decline": "拒绝", "counter": "提出修改", "submit": "提交结果", "agree": "同意对方的修改",
               "revise": "修改要求", "approve": "验收通过", "return": "退回修改", "cancel": "取消"}


def member_id(value) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise CollabError("成员不存在") from None
