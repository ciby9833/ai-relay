"""承诺账本的线上增量计算（评估阶段：只算不推，不影响现有事项和提醒）。

和影子实验同一套过滤、归事、对账（见 shadow.py），区别是状态存数据库、每次只处理上次之后的新事件：

    参加评估的用户（打开过“评估”页的）→ 每隔几分钟：
      收集上次处理点之后的事件（往前多看 1 小时：私聊是轮询来的，消息时间可能早于上次处理点；按引用去重）
      → 规则过滤 → 归入事项（轻量模型，每人每次一次调用）→ 只对有新材料的事项对账（判断模型）
      → 5 天没动静的未结承诺标为“可能已过期”

第一次参加时回填最近 2 天（可选 1~3 天）。
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ledger import shadow
from app.models import LedgerCommitment, LedgerEvent, LedgerMatter, SourceState, User

logger = logging.getLogger("relay.ledger")

STATE = "ledger"  # SourceState.source：{"until": 处理到哪, "enrolled_at": 何时加入评估}
BACKFILL_DAYS = 2  # 第一次加入时回填几天（可选 1~3）
OVERLAP = timedelta(hours=1)
MAX_EVENTS_PER_CALL = 60


async def enroll(session: AsyncSession, user: User, days: int = BACKFILL_DAYS) -> SourceState:
    """加入评估（幂等）。之后由 ledger 服务开始为他计算，先回填最近 days 天。"""
    state = await session.get(SourceState, (user.id, STATE))
    if state is None:
        state = SourceState(user_id=user.id, source=STATE, cursor={"enrolled_at": datetime.now(UTC).isoformat(),
                                                                   "backfill_days": max(1, min(days, 3))})
        session.add(state)
        await session.flush()
    return state


async def enrolled_users(session: AsyncSession) -> list[User]:
    return list((await session.execute(
        select(User).join(SourceState, SourceState.user_id == User.id).where(SourceState.source == STATE)
    )).scalars())


def _event_row(user: User, e: shadow.Event, verdict: str, matter_id: int | None) -> LedgerEvent:
    return LedgerEvent(user_id=user.id, ref=e.id, matter_id=matter_id, kind=e.kind, actor=e.actor[:255], text=e.text[:2000],
                       stream=e.stream[:255], at=e.at, verdict=verdict)


async def advance(session: AsyncSession, provider, user: User, now: datetime | None = None) -> shadow.Meter:
    """处理这个人上次之后的新事件。只写账本表和评估状态，不碰现有事项。"""
    now = now or datetime.now(UTC)
    meter = shadow.Meter()
    state = await enroll(session, user)
    cursor = dict(state.cursor or {})
    until = datetime.fromisoformat(cursor["until"]) if cursor.get("until") else now - timedelta(days=cursor.get("backfill_days") or BACKFILL_DAYS)
    start = until - OVERLAP if cursor.get("until") else until
    events = await shadow.collect(session, user, start, now)
    shadow.screen(events)
    seen = set((await session.execute(
        select(LedgerEvent.ref).where(LedgerEvent.user_id == user.id, LedgerEvent.ref.in_([e.id for e in events] or ["-"]))
    )).scalars())
    fresh = [e for e in events if e.keep and e.id not in seen]
    tz = ZoneInfo(user.timezone)
    window_start, processed_until = start, now
    while window_start < now and fresh:
        window = [e for e in fresh if window_start <= e.at < window_start + shadow.WINDOW][:MAX_EVENTS_PER_CALL]
        if window and not await _process_window(session, provider, user, window, tz, meter):
            # 模型出错：处理点停在这一窗之前，下次从这里重试（已写入的事件按引用去重，不会重复判断）
            processed_until = window_start
            break
        window_start += shadow.WINDOW
        # 每处理完一窗就记下进度：页面上能看到“整理到哪了”，中途重启也从这里接着做
        state.cursor = {**(state.cursor or {}), "progress": min(window_start, now).isoformat()}
        await session.commit()
    # 5 天没动静的未结承诺
    stale_before = now - shadow.STALE
    await session.execute(
        update(LedgerCommitment).where(
            LedgerCommitment.user_id == user.id, LedgerCommitment.status == "open",
            LedgerCommitment.matter_id.in_(select(LedgerMatter.id).where(LedgerMatter.user_id == user.id, LedgerMatter.last_at < stale_before)),
        ).values(status="stale", updated_at=now)
    )
    done = processed_until >= now
    state.cursor = {**cursor, "until": max(processed_until, until).isoformat(), "progress": max(processed_until, until).isoformat(),
                    "backfilled": bool(cursor.get("backfilled")) or done, "last_run": {"calls": meter.calls, "tokens": meter.tokens, "errors": meter.errors}}
    await session.commit()
    return meter


async def _process_window(session, provider, user, window: list[shadow.Event], tz, meter: shadow.Meter) -> bool:
    now = window[-1].at
    open_matters = list((await session.execute(
        select(LedgerMatter).where(LedgerMatter.user_id == user.id, LedgerMatter.last_at > now - timedelta(days=14))
        .order_by(LedgerMatter.last_at.desc()).limit(40)
    )).scalars())
    catalog = "\n".join(f"#{m.id} {m.title}（{'、'.join((m.people or [])[:4])}；{(m.summary or '')[:80]}）" for m in open_matters) or "（暂无）"
    result = await shadow._call(provider, shadow.ATTACH_MODEL, shadow.ATTACH_SYSTEM,
                                f"<data>\n他是 {user.name}。\n事项清单：\n{catalog}\n\n新事件：\n"
                                + "\n".join(shadow._line(e, tz) for e in window) + "\n</data>",
                                shadow.ATTACH_TOOL, meter, "attach")
    if not result:
        return False
    by_ref = {e.id: e for e in window}
    known = {m.id: m for m in open_matters}
    fresh: dict[str, LedgerMatter] = {}
    touched: set[int] = set()
    assigned: set[str] = set()
    for a in result.get("assignments") or []:
        found = shadow.EVENT_ID.search(str(a.get("event") or ""))
        event = by_ref.get(found.group(0)) if found else None
        if event is None or event.id in assigned:
            continue
        assigned.add(event.id)
        target = str(a.get("matter") or "none").lstrip("#")
        if target == "none":
            session.add(_event_row(user, event, "none", None))
            continue
        if target == "new":
            key = a.get("new_key") or event.id
            matter = fresh.get(key)
            if matter is None:
                matter = await _new_matter(session, user, event, a)
                fresh[key] = known[matter.id] = matter
        else:
            matter = known.get(int(target)) if target.isdigit() else None
            if matter is None:
                session.add(_event_row(user, event, "none", None))
                continue
        matter.last_at = max(matter.last_at, event.at)
        session.add(_event_row(user, event, "attached", matter.id))
        touched.add(matter.id)
    # 模型漏掉的事件也记下（不再重复送去判断）
    for event in window:
        if event.id not in assigned:
            session.add(_event_row(user, event, "none", None))
    await session.flush()
    for matter_id in touched:
        await _reconcile(session, provider, user, known[matter_id], now, tz, meter)
    return True


async def _new_matter(session, user, event: shadow.Event, a: dict) -> LedgerMatter:
    people = a.get("people") or ([] if event.from_me else [event.actor])
    matter = LedgerMatter(user_id=user.id, title=(a.get("title") or event.text[:60])[:500], people=people,
                          created_at=event.at, last_at=event.at)
    session.add(matter)
    await session.flush()
    return matter


async def _reconcile(session, provider, user, matter: LedgerMatter, now: datetime, tz, meter: shadow.Meter) -> None:
    rows = list((await session.execute(
        select(LedgerEvent).where(LedgerEvent.matter_id == matter.id).order_by(LedgerEvent.at.desc()).limit(shadow.MAX_MATERIAL)
    )).scalars())[::-1]
    material = "\n".join(
        shadow._line(shadow.Event(r.ref, r.kind, r.at, r.actor, r.text, r.stream, from_me=r.actor == user.name), tz) for r in rows)
    current = list((await session.execute(select(LedgerCommitment).where(LedgerCommitment.matter_id == matter.id))).scalars())
    ledger = [{"owner": c.owner, "party": c.party, "what": c.what, "due": c.due, "status": c.status, "evidence": c.evidence}
              for c in current if c.status != "stale"]
    out = await shadow._call(provider, shadow.RECONCILE_MODEL, shadow.RECONCILE_SYSTEM,
                             f"<data>\n他是 {user.name}。现在是 {now.astimezone(tz):%Y-%m-%d %H:%M}。\n事项：{matter.title}（{'、'.join(matter.people or [])}）\n"
                             f"账本现状：{json.dumps(ledger, ensure_ascii=False)}\n\n材料：\n{material}\n</data>",
                             shadow.RECONCILE_TOOL, meter, "reconcile")
    if not out:
        return  # 出错时保留原来的承诺
    matter.summary = (out.get("summary") or matter.summary or "")[:1000]
    await session.execute(delete(LedgerCommitment).where(LedgerCommitment.matter_id == matter.id))
    for c in out.get("commitments") or []:
        session.add(LedgerCommitment(user_id=user.id, matter_id=matter.id, owner=c.get("owner") if c.get("owner") in ("me", "other") else "me",
                                     party=(c.get("party") or "?")[:255], what=c.get("what") or "", due=(c.get("due") or None) and str(c["due"])[:64],
                                     status=c.get("status") if c.get("status") in ("open", "done", "dropped") else "open",
                                     evidence=c.get("evidence") or "", updated_at=now))
    await session.flush()
