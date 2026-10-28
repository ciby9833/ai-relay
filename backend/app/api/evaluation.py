"""评估：每个人对照“新链路的承诺账本”和“现有系统的事项”，自己标注哪些是真的、状态对不对，补充漏掉的。

隐私：每个人只看得到、只能标注自己的；管理员只看到每个人的汇总数字（标了多少、真实率、状态正确率），看不到内容。
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.api.quality import require_admin
from app.deps import SessionDep, UserDep
from app.ledger import engine
from app.models import (EvalFeedback, EvalLabel, FollowUp, LedgerCommitment, LedgerEvent, LedgerMatter, SourceState, User)

router = APIRouter(prefix="/api", tags=["evaluation"])
MATERIALS = 10


def commitment_key(c: LedgerCommitment) -> str:
    """对账会整体替换一件事的承诺行；同一件事、同样内容的承诺沿用原来的评价。"""
    return f"{c.matter_id}:{c.owner}:{c.what.strip()[:400]}"


@router.post("/eval/enroll")
async def enroll(session: SessionDep, user: UserDep):
    state = await engine.enroll(session, user)
    await session.commit()
    return {"enrolled": True, "since": state.cursor.get("enrolled_at")}


@router.get("/eval")
async def evaluation(session: SessionDep, user: UserDep, days: int = 7):
    days = max(1, min(days, 30))
    since = datetime.now(UTC) - timedelta(days=days)
    state = await session.get(SourceState, (user.id, engine.STATE))
    labels = {(r.target, r.target_key): r.label for r in (await session.execute(
        select(EvalLabel).where(EvalLabel.user_id == user.id))).scalars()}
    ledger = []
    if state is not None:
        matters = {m.id: m for m in (await session.execute(
            select(LedgerMatter).where(LedgerMatter.user_id == user.id, LedgerMatter.last_at >= since))).scalars()}
        commitments = (await session.execute(
            select(LedgerCommitment).where(LedgerCommitment.user_id == user.id, LedgerCommitment.matter_id.in_(list(matters) or [0]))
        )).scalars().all()
        materials: dict[int, list] = {}
        for row in (await session.execute(
            select(LedgerEvent).where(LedgerEvent.matter_id.in_(list(matters) or [0])).order_by(LedgerEvent.at.desc())
        )).scalars():
            if len(materials.setdefault(row.matter_id, [])) < MATERIALS:
                materials[row.matter_id].append({"at": row.at.isoformat(), "actor": row.actor, "text": row.text[:300], "kind": row.kind})
        for c in sorted(commitments, key=lambda c: matters[c.matter_id].last_at, reverse=True):
            key = commitment_key(c)
            m = matters[c.matter_id]
            ledger.append({"key": key, "matter_id": m.id, "matter": m.title, "summary": m.summary, "owner": c.owner, "party": c.party,
                           "what": c.what, "due": c.due, "status": c.status, "evidence": c.evidence, "last_at": m.last_at.isoformat(),
                           "materials": materials.get(m.id, [])[::-1], "label": labels.get(("ledger", key))})
    items = (await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.created_at >= since).order_by(FollowUp.created_at.desc())
    )).scalars().all()
    current = [{"key": str(i.id), "title": i.title, "kind": i.kind, "status": i.status, "resolution": i.resolution,
                "summary": (i.summary or "")[:300], "created_at": i.created_at.isoformat(), "label": labels.get(("followup", str(i.id)))}
               for i in items]
    feedback = [{"id": f.id, "kind": f.kind, "text": f.text, "created_at": f.created_at.isoformat()} for f in (await session.execute(
        select(EvalFeedback).where(EvalFeedback.user_id == user.id).order_by(EvalFeedback.id.desc()).limit(50))).scalars()]
    cursor = (state.cursor or {}) if state else {}
    return {"enrolled": state is not None, "processed_until": cursor.get("until"), "enrolled_at": cursor.get("enrolled_at"),
            "days": days, "ledger": ledger, "current": current, "feedback": feedback}


class LabelBody(BaseModel):
    target: Literal["ledger", "followup"]
    key: str = Field(min_length=1, max_length=600)
    label: Literal["ok", "state", "noise"] | None
    snapshot: dict = Field(default_factory=dict)


@router.put("/eval/labels")
async def set_label(body: LabelBody, session: SessionDep, user: UserDep):
    if body.target == "followup":
        item = await session.get(FollowUp, int(body.key)) if body.key.isdigit() else None
        if item is None or item.user_id != user.id:
            raise HTTPException(status_code=404, detail="事项不存在")
    else:
        matter_id = body.key.split(":", 1)[0]
        matter = await session.get(LedgerMatter, int(matter_id)) if matter_id.isdigit() else None
        if matter is None or matter.user_id != user.id:
            raise HTTPException(status_code=404, detail="承诺不存在")
    if body.label is None:
        await session.execute(EvalLabel.__table__.delete().where(
            EvalLabel.user_id == user.id, EvalLabel.target == body.target, EvalLabel.target_key == body.key))
    else:
        snapshot = {k: str(v)[:300] for k, v in list(body.snapshot.items())[:8]}
        await session.execute(insert(EvalLabel).values(
            user_id=user.id, target=body.target, target_key=body.key, label=body.label, snapshot=snapshot,
        ).on_conflict_do_update(constraint="uq_eval_labels_target",
                                set_={"label": body.label, "snapshot": snapshot, "updated_at": func.now()}))
    await session.commit()
    return {"ok": True}


class FeedbackBody(BaseModel):
    kind: Literal["missed", "comment"]
    text: str = Field(min_length=1, max_length=4000)


@router.post("/eval/feedback")
async def add_feedback(body: FeedbackBody, session: SessionDep, user: UserDep):
    session.add(EvalFeedback(user_id=user.id, kind=body.kind, text=body.text.strip()))
    await session.commit()
    return {"ok": True}


@router.get("/insights/eval")
async def eval_overview(session: SessionDep, user: UserDep):
    """（管理员）每个人的评估汇总：只有数字，没有内容。"""
    require_admin(user)
    users = {u.id: u.name for u in (await session.execute(select(User))).scalars()}
    enrolled = {s.user_id: s.cursor or {} for s in (await session.execute(
        select(SourceState).where(SourceState.source == engine.STATE))).scalars()}
    counts: dict = {}
    for uid, target, label, n in (await session.execute(
        select(EvalLabel.user_id, EvalLabel.target, EvalLabel.label, func.count()).group_by(EvalLabel.user_id, EvalLabel.target, EvalLabel.label)
    )).all():
        counts.setdefault(uid, {}).setdefault(target, {})[label] = n
    missed = dict((await session.execute(
        select(EvalFeedback.user_id, func.count()).where(EvalFeedback.kind == "missed").group_by(EvalFeedback.user_id))).all())

    def rates(c: dict) -> dict:
        total = sum(c.values())
        return {"labeled": total, "real": round((c.get("ok", 0) + c.get("state", 0)) / total, 3) if total else None,
                "correct": round(c.get("ok", 0) / total, 3) if total else None, **{k: c.get(k, 0) for k in ("ok", "state", "noise")}}

    rows = []
    for uid in set(enrolled) | set(counts):
        c = counts.get(uid, {})
        rows.append({"user": users.get(uid, str(uid)), "enrolled": uid in enrolled,
                     "processed_until": enrolled.get(uid, {}).get("until"), "last_run": enrolled.get(uid, {}).get("last_run"),
                     "ledger": rates(c.get("ledger", {})), "current": rates(c.get("followup", {})), "missed": missed.get(uid, 0)})
    total = {t: rates({k: sum(counts.get(u, {}).get(t, {}).get(k, 0) for u in counts) for k in ("ok", "state", "noise")})
             for t in ("ledger", "followup")}
    return {"users": sorted(rows, key=lambda r: -(r["ledger"]["labeled"] + r["current"]["labeled"])),
            "total": {"ledger": total["ledger"], "current": total["followup"]}}
