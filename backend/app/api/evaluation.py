"""评估：每个人对照“新链路的承诺账本”和“现有系统的事项”，自己标注哪些是真的、状态对不对，补充漏掉的。

隐私：每个人只看得到、只能标注自己的；管理员只看到每个人的汇总数字（标了多少、真实率、状态正确率），看不到内容。
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.api.quality import require_admin
from app.deps import SessionDep, UserDep
from app.ledger import engine
from app.proactive.items import HIDDEN
from app.models import (EvalFeedback, EvalLabel, FollowUp, LedgerCommitment, LedgerEvent, LedgerMatter, SourceState, User)

router = APIRouter(prefix="/api", tags=["evaluation"])
MATERIALS = 10
# 👎 的原因：前三种说明这条根本不该出现，后三种说明事是真的、但判断错了
NOISE_REASONS = ("not_mine", "duplicate", "too_old")
WRONG_REASONS = ("already_done", "not_done", "wrong_detail")
Reason = Literal["not_mine", "duplicate", "too_old", "already_done", "not_done", "wrong_detail"]


REF = re.compile(r"\[?(?:sig|chat):[^\]\s,，、]+\]?\s*")


def readable(text: str) -> str:
    """依据里的内部编号（[sig:123]、[chat:om_xxx]）给人看时去掉。"""
    return REF.sub("", text or "").strip(" ；;，,")


def commitment_key(c: LedgerCommitment) -> str:
    """对账会整体替换一件事的承诺行；同一件事、同样内容的承诺沿用原来的评价。"""
    return f"{c.matter_id}:{c.owner}:{c.what.strip()[:400]}"


class EnrollBody(BaseModel):
    days: int = Field(default=engine.BACKFILL_DAYS, ge=1, le=3)


@router.post("/eval/enroll")
async def enroll(session: SessionDep, user: UserDep, body: EnrollBody | None = None):
    state = await engine.enroll(session, user, (body or EnrollBody()).days)
    await session.commit()
    return {"enrolled": True, "since": state.cursor.get("enrolled_at")}


@router.get("/eval")
async def evaluation(session: SessionDep, user: UserDep):
    """一次评估是一个任务：开始时选定范围（最近 1~3 天），整理完后持续更新；看到的是从那时起的全部结果。"""
    state = await session.get(SourceState, (user.id, engine.STATE))
    cursor = (state.cursor or {}) if state else {}
    days = cursor.get("backfill_days") or engine.BACKFILL_DAYS
    enrolled_at = datetime.fromisoformat(cursor["enrolled_at"]) if cursor.get("enrolled_at") else datetime.now(UTC)
    since = enrolled_at - timedelta(days=days)
    labels = {(r.target, r.target_key): {"label": r.label, "reason": r.reason, "note": r.note} for r in (await session.execute(
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
                           "what": c.what, "due": c.due, "status": c.status, "evidence": readable(c.evidence), "last_at": m.last_at.isoformat(),
                           "materials": materials.get(m.id, [])[::-1], "feedback": labels.get(("ledger", key))})
    items = (await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.created_at >= since,
                               FollowUp.status.notin_(HIDDEN)).order_by(FollowUp.created_at.desc())
    )).scalars().all()
    current = [{"key": str(i.id), "title": i.title, "kind": i.kind, "status": i.status, "resolution": i.resolution,
                "summary": (i.summary or "")[:300], "created_at": i.created_at.isoformat(), "feedback": labels.get(("followup", str(i.id)))}
               for i in items]
    feedback = [{"id": f.id, "kind": f.kind, "text": f.text, "created_at": f.created_at.isoformat()} for f in (await session.execute(
        select(EvalFeedback).where(EvalFeedback.user_id == user.id).order_by(EvalFeedback.id.desc()).limit(50))).scalars()]
    if state is None:
        status, progress = "not_started", None
    elif cursor.get("backfilled"):
        status, progress = "live", 1.0
    else:
        # 回填进行中：按已处理到的时间点算进度
        done_until = datetime.fromisoformat(cursor["progress"]) if cursor.get("progress") else since
        status = "running" if cursor.get("progress") else "queued"
        progress = round(max(0.0, min(1.0, (done_until - since) / max(enrolled_at - since, timedelta(seconds=1)))), 2)
    return {"enrolled": state is not None, "status": status, "progress": progress, "processed_until": cursor.get("until"),
            "enrolled_at": cursor.get("enrolled_at"), "days": days, "ledger": ledger, "current": current, "feedback": feedback}


class LabelBody(BaseModel):
    target: Literal["ledger", "followup"]
    key: str = Field(min_length=1, max_length=600)
    label: Literal["up", "down"] | None  # None：撤销
    reason: Reason | None = None
    note: str | None = Field(default=None, max_length=1000)
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
        reason = body.reason if body.label == "down" else None
        note = (body.note or "").strip() or None
        await session.execute(insert(EvalLabel).values(
            user_id=user.id, target=body.target, target_key=body.key, label=body.label, reason=reason, note=note, snapshot=snapshot,
        ).on_conflict_do_update(constraint="uq_eval_labels_target",
                                set_={"label": body.label, "reason": reason, "note": note, "snapshot": snapshot, "updated_at": func.now()}))
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
    for uid, target, label, reason, n in (await session.execute(
        select(EvalLabel.user_id, EvalLabel.target, EvalLabel.label, EvalLabel.reason, func.count())
        .group_by(EvalLabel.user_id, EvalLabel.target, EvalLabel.label, EvalLabel.reason)
    )).all():
        bucket = counts.setdefault(uid, {}).setdefault(target, {})
        key = "up" if label == "up" else f"down:{reason or 'unspecified'}"
        bucket[key] = bucket.get(key, 0) + n
    missed = dict((await session.execute(
        select(EvalFeedback.user_id, func.count()).where(EvalFeedback.kind == "missed").group_by(EvalFeedback.user_id))).all())

    def rates(c: dict) -> dict:
        """correct = 👍 的占比；real = 事是真的（👍 + 原因是“判断错了”那三种）的占比；没写原因的 👎 不计入 real。"""
        total = sum(c.values())
        up = c.get("up", 0)
        wrong = sum(c.get(f"down:{r}", 0) for r in WRONG_REASONS)
        return {"labeled": total, "up": up, "down": total - up,
                "real": round((up + wrong) / total, 3) if total else None, "correct": round(up / total, 3) if total else None,
                "reasons": {k.split(":", 1)[1]: v for k, v in c.items() if k.startswith("down:")}}

    rows = []
    for uid in set(enrolled) | set(counts):
        c = counts.get(uid, {})
        rows.append({"user": users.get(uid, str(uid)), "enrolled": uid in enrolled,
                     "processed_until": enrolled.get(uid, {}).get("until"), "last_run": enrolled.get(uid, {}).get("last_run"),
                     "ledger": rates(c.get("ledger", {})), "current": rates(c.get("followup", {})), "missed": missed.get(uid, 0)})
    def merged(target: str) -> dict:
        out: dict = {}
        for per in counts.values():
            for k, v in per.get(target, {}).items():
                out[k] = out.get(k, 0) + v
        return out

    total = {t: rates(merged(t)) for t in ("ledger", "followup")}
    return {"users": sorted(rows, key=lambda r: -(r["ledger"]["labeled"] + r["current"]["labeled"])),
            "total": {"ledger": total["ledger"], "current": total["followup"]}}


NEGATIVE = ("handled_before", "not_mine", "not_worth", "quieter", "duplicate")


@router.get("/insights/reminders")
async def reminder_quality(session: SessionDep, user: UserDep, days: int = 7):
    """（管理员）提醒准不准：来自真实卡片上的反馈，只有数字。

    准确率 = 提醒后处理 ÷（提醒后处理 + 提醒前已处理 + 不归我 + 不值得 + 少提醒 + 重复）；没反应的单独统计，不计入。
    另外看每个来源新建了多少件事、多少先作为候选没有打扰（私聊过度跟踪有没有收住）。
    """
    from app.models import ItemFeedback
    from app.proactive.feedback import source_of

    require_admin(user)
    days = max(1, min(days, 30))
    since = datetime.now(UTC) - timedelta(days=days)
    names = {u.id: u.name for u in (await session.execute(select(User))).scalars()}
    per_user: dict = {}

    def row(uid):
        return per_user.setdefault(uid, {"user": names.get(uid, str(uid)), "pushed": 0, "feedback": {}, "no_response": 0,
                                         "created": {}, "candidates": 0, "promoted": 0})

    fb_items: set[int] = set()
    by_source: dict = {}
    for f in (await session.execute(select(ItemFeedback).where(ItemFeedback.created_at > since))).scalars():
        r = row(f.user_id)
        r["feedback"][f.outcome] = r["feedback"].get(f.outcome, 0) + 1
        by_source.setdefault(f.source, {}).setdefault(f.outcome, 0)
        by_source[f.source][f.outcome] += 1
        fb_items.add(f.item_id)
    created = (await session.execute(select(FollowUp).where(FollowUp.created_at > since))).scalars().all()
    for item in created:
        r = row(item.user_id)
        source = await source_of(session, item)
        if item.status in HIDDEN or (item.facets or {}).get("basis") == "unclear":
            r["candidates"] += 1
            if item.status not in HIDDEN:
                r["promoted"] += 1  # 候选后来有了证据，转成正式事项
            continue
        r["created"][source] = r["created"].get(source, 0) + 1
    pushed = (await session.execute(select(FollowUp.user_id, FollowUp.id).where(FollowUp.pushed_at > since))).all()
    for uid, item_id in pushed:
        r = row(uid)
        r["pushed"] += 1
        if item_id not in fb_items:
            r["no_response"] += 1

    def rates(counts: dict) -> dict:
        after = counts.get("handled_after", 0)
        negative = sum(counts.get(k, 0) for k in NEGATIVE)
        judged = after + negative
        return {"accuracy": round(after / judged, 3) if judged else None,
                "late": round(counts.get("handled_before", 0) / judged, 3) if judged else None, "judged": judged}

    users = [{**r, **rates(r["feedback"])} for r in per_user.values()]
    total: dict = {}
    for r in per_user.values():
        for k, v in r["feedback"].items():
            total[k] = total.get(k, 0) + v
    return {
        "days": days,
        "total": {"feedback": total, **rates(total), "pushed": sum(r["pushed"] for r in users),
                  "no_response": sum(r["no_response"] for r in users), "candidates": sum(r["candidates"] for r in users)},
        "by_source": {s: {"feedback": c, **rates(c)} for s, c in by_source.items()},
        "users": sorted(users, key=lambda r: -r["pushed"]),
    }
