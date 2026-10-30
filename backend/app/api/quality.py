"""Admin-only quality baseline, with explicit denominators and human closure adjudication."""
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app import assurance
from app.deps import SessionDep, UserDep
from app.models import AssuranceEvent, Mission, MissionLog, User

router = APIRouter(prefix="/api/insights", tags=["quality"])


def require_admin(user):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以查看")


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": round(numerator / denominator, 4) if denominator else None}


@router.get("/quality")
async def quality(session: SessionDep, user: UserDep, days: int = 7, offset: int = 0):
    require_admin(user)
    days, offset = max(1, min(days, 30)), max(0, min(offset, 30))
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=offset)
    start = end - timedelta(days=days)
    members = select(User.id).where(User.tenant_id == user.tenant_id)  # 只看本工作区
    events = list((await session.scalars(select(AssuranceEvent).where(
        AssuranceEvent.created_at >= start, AssuranceEvent.created_at < end, AssuranceEvent.user_id.in_(members)))).all())
    coverage = await session.scalar(select(func.min(AssuranceEvent.created_at)).where(AssuranceEvent.user_id.in_(members)))
    checks = [e for e in events if e.kind == "completion_check"]
    writes = [e for e in events if e.kind in ("write_verification", "business_verification")]
    known = [e for e in writes if e.detail.get("ok") is not None]
    # Only instrumented runs count; pre-rollout wake logs must not dilute the handoff rate.
    active = {e.mission_id for e in events if e.mission_id and e.kind in
              ("mission_run", "completion_check", "human_takeover", "completion")}
    handoffs = {e.mission_id for e in events if e.kind == "human_takeover"}
    closed = (await session.execute(select(Mission, User.name, func.max(MissionLog.created_at).label("closed_at"))
        .join(User, Mission.user_id == User.id).join(MissionLog, MissionLog.mission_id == Mission.id)
        .where(Mission.status == "done", MissionLog.kind == "done", MissionLog.created_at >= start, MissionLog.created_at < end,
               User.tenant_id == user.tenant_id)
        .group_by(Mission.id, User.name).order_by(func.max(MissionLog.created_at).desc()))).all()
    ids = [m.id for m, _, _ in closed]
    reviews = {}
    if ids:
        for e in (await session.scalars(select(AssuranceEvent).where(AssuranceEvent.kind == "closure_review",
                         AssuranceEvent.mission_id.in_(ids)).order_by(AssuranceEvent.id))).all():
            reviews[e.mission_id] = {**e.detail, "at": e.created_at.isoformat()}
    assessed = [r for r in reviews.values() if r["verdict"] != "unknown"]
    turns = [e for e in events if e.kind == "turn" and e.detail.get("channel") != "mission"]
    tool_counts = sorted(e.detail.get("tool_calls", 0) for e in turns)
    return {
        "start": start.isoformat(), "end": end.isoformat(), "coverage_start": coverage.isoformat() if coverage else None,
        # 对话质量：问了却没拿到回答（出错 / 什么都没说）、查到上限才勉强作答、一轮里查了很多次
        "turn_no_answer": rate(sum(e.detail.get("outcome") in ("error", "no_answer") for e in turns), len(turns)),
        "turn_forced_final": rate(sum(e.detail.get("outcome") == "forced_final" for e in turns), len(turns)),
        "turn_heavy_search": rate(sum(e.detail.get("tool_calls", 0) >= 15 for e in turns), len(turns)),
        "turn_median_tools": tool_counts[len(tool_counts) // 2] if tool_counts else None,
        "turn_errors": [{"at": e.created_at.isoformat(), "errors": e.detail.get("errors")} for e in turns
                        if e.detail.get("outcome") == "error"][-20:],
        "turns_by_prompt": by_prompt(turns),
        "false_closure": rate(sum(r["verdict"] == "false_close" for r in assessed), len(assessed)),
        "review_coverage": rate(len(assessed), len(closed)),
        "completion_failure": rate(sum(e.detail.get("passed") is not True for e in checks), len(checks)),
        "verification_failure": rate(sum(e.detail.get("ok") is False for e in known), len(known)),
        "verification_unknown": len(writes) - len(known),
        "human_takeover": rate(len(handoffs), len(active)),
        "closed_total": len(closed),
        "closures": [{"id": m.id, "title": m.title, "user": name, "instruction": m.instruction or m.goal,
                      "result": m.result, "criteria": m.criteria, "closed_at": at.isoformat(), "review": reviews.get(m.id)}
                     for m, name, at in closed[:100]],
    }


def by_prompt(turns) -> list[dict]:
    """按系统提示词版本对比对话质量：改提示词后看没回答、勉强作答、工具出错、查找超限有没有变多。"""
    from collections import Counter

    groups: dict[str, list] = {}
    for e in turns:
        groups.setdefault(e.detail.get("prompt") or "旧版（未记录）", []).append(e)
    out = []
    for version, rows in groups.items():
        tools = sum(len(e.detail.get("tools") or []) for e in rows)
        codes = Counter(code for e in rows for code in e.detail.get("tool_errors") or [])
        counts = sorted(e.detail.get("tool_calls", 0) for e in rows)
        out.append({
            "version": version, "turns": len(rows), "first_at": min(e.created_at for e in rows).isoformat(),
            "no_answer": rate(sum(e.detail.get("outcome") in ("error", "no_answer") for e in rows), len(rows)),
            "forced_final": rate(sum(e.detail.get("outcome") == "forced_final" for e in rows), len(rows)),
            "median_tools": counts[len(counts) // 2] if counts else None,
            "tool_error": rate(sum(codes.values()), tools) if tools else rate(0, 0),
            "error_codes": dict(codes.most_common(6)),
        })
    return sorted(out, key=lambda g: g["first_at"])


class ReviewBody(BaseModel):
    verdict: Literal["correct", "false_close", "unknown"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("请填写复盘依据")
        return value.strip()


@router.post("/missions/{mission_id}/review")
async def review_closure(mission_id: int, body: ReviewBody, session: SessionDep, user: UserDep):
    require_admin(user)
    mission = await session.scalar(select(Mission).join(User, Mission.user_id == User.id)
                                   .where(Mission.id == mission_id, User.tenant_id == user.tenant_id).with_for_update(of=Mission))
    if mission is None:
        raise HTTPException(status_code=404, detail="任务不存在")  # 别的工作区的任务：当作不存在
    if mission.status != "done":
        raise HTTPException(status_code=400, detail="只能复盘已完成的任务")
    assurance.record(session, mission.user_id, "closure_review",
                     {**body.model_dump(), "reviewer_id": str(user.id)}, mission.id)
    await session.commit()
    return {"ok": True}
