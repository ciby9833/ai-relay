"""从真实反馈推出每次判断的对错（不靠人去读别人的内容）。

只用确定的信号；拿不准的一律算“未知”，不猜：
- mail_triage：这封信变成的事项上，他在卡片上的反馈（正常使用时点的，不需要专门标注）
  处理了（提醒后、自己标的、提醒前就处理了）= 对；不归我 / 不值得提醒 / 重复 = 错；“这类少提醒”不算对错
- reply_draft：草稿后来原样发出 = 对；改过再发 = 部分对；取消 = 错；还没处理 = 未知
- mission_completion_check：全自动，不用人复盘。核对说“通过”、任务结束后 7 天内，他又开了一个几乎一样的任务
  （说明其实没办成）= 错；7 天过去没有重做 = 对；不到 7 天、或任务最后没有结束的不计
- rule_proposal：整理出来的候选规则，他启用 = 对；不用 = 错（每条规则一个样本）

每个样本的结论：right / partly / wrong，以及模型“该给出”的关键判断（truth），回放时拿来比。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttentionRule, FollowUp, ItemFeedback, JudgementRun, Mission, MissionLog, PendingAction

RIGHT_FEEDBACK = ("handled", "handled_after", "handled_before")
WRONG_FEEDBACK = ("not_mine", "not_worth", "duplicate")
LABELED = ("mail_triage", "reply_draft", "mission_completion_check", "rule_proposal")


@dataclass
class Sample:
    run_id: int
    verdict: str  # right | partly | wrong
    truth: dict  # 该给出的关键判断，例如 {"surface": True}
    why: str  # 依据（类别，不含内容）


def _ref(run: JudgementRun, prefix: str) -> int | None:
    if not run.subject or not run.subject.startswith(prefix + ":"):
        return None
    try:
        return int(run.subject.split(":", 1)[1])
    except ValueError:
        return None


def surfaced(output: dict | None) -> bool | None:
    """邮件分级的关键判断：要不要进待处理（有明确要求的 reply / review 才进）。"""
    if not output or "action_type" not in output:
        return None
    return output["action_type"] in ("reply", "review") and bool((output.get("ask") or "").strip())


async def _mail_triage(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    signal_id = _ref(run, "signal")
    if signal_id is None or run.user_id is None:
        return []
    item = (await session.execute(select(FollowUp).where(
        FollowUp.user_id == run.user_id, FollowUp.signal_ids.contains([signal_id])).limit(1))).scalars().first()
    if item is None:
        return []  # 没变成事项：说“不用他处理”的判断，现在没有反馈能说明对错
    feedback = (await session.execute(select(ItemFeedback.outcome).where(ItemFeedback.item_id == item.id)
                                      .order_by(ItemFeedback.id.desc()).limit(1))).scalar()
    if feedback in RIGHT_FEEDBACK:
        return [Sample(run.id, "right" if surfaced(run.output) else "wrong", {"surface": True}, f"feedback:{feedback}")]
    if feedback in WRONG_FEEDBACK:
        return [Sample(run.id, "wrong" if surfaced(run.output) else "right", {"surface": False}, f"feedback:{feedback}")]
    return []  # 没有反馈：不计（不靠人去标注）


async def _reply_draft(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    signal_id = _ref(run, "signal")
    body = (run.output or {}).get("body")
    if signal_id is None or not body:
        return []
    action = (await session.execute(select(PendingAction).where(
        PendingAction.user_id == run.user_id, PendingAction.kind == "send_mail", PendingAction.signal_id == signal_id,
        PendingAction.created_at >= run.created_at - timedelta(seconds=5), PendingAction.created_at <= run.created_at + timedelta(minutes=5),
    ).order_by(PendingAction.id).limit(1))).scalars().first()
    if action is None or action.status == "pending":
        return []
    if action.status == "cancelled":
        return [Sample(run.id, "wrong", {"used": False}, "draft:cancelled")]
    if action.status == "done":
        same = (action.payload or {}).get("body", "").strip() == body.strip()
        return [Sample(run.id, "right" if same else "partly", {"used": True, "edited": not same}, "draft:sent" + ("" if same else "_edited"))]
    return []


REDO_WINDOW = timedelta(days=7)
REDO_SIMILARITY = 0.5


def similarity(a: str, b: str) -> float:
    """两段话有多像：按相邻两个字（中文）/ 词（英文）的重合程度，0 到 1。"""
    def grams(text: str) -> set[str]:
        text = "".join((text or "").lower().split())
        return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())

    x, y = grams(a), grams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


async def _completion_check(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    mission_id = _ref(run, "mission")
    passed = (run.output or {}).get("goal_supported")
    if mission_id is None or passed is not True:
        return []
    mission = await session.get(Mission, mission_id)
    if mission is None or mission.status != "done":
        return []
    closed_at = await session.scalar(select(func.max(MissionLog.created_at)).where(
        MissionLog.mission_id == mission_id, MissionLog.kind == "done")) or run.created_at
    text = mission.instruction or mission.goal or mission.title
    later = (await session.execute(select(Mission).where(
        Mission.user_id == mission.user_id, Mission.id != mission.id, Mission.created_at > closed_at,
        Mission.created_at <= closed_at + REDO_WINDOW))).scalars().all()
    if any(similarity(text, m.instruction or m.goal or m.title) >= REDO_SIMILARITY for m in later):
        return [Sample(run.id, "wrong", {"goal_supported": False}, "mission:redone")]
    if datetime.now(UTC) - closed_at >= REDO_WINDOW:
        return [Sample(run.id, "right", {"goal_supported": True}, "mission:held")]
    return []


async def _rule_proposal(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    if run.user_id is None:
        return []
    rules = (await session.execute(select(AttentionRule).where(
        AttentionRule.user_id == run.user_id, AttentionRule.source == "memory",
        AttentionRule.created_at >= run.created_at - timedelta(seconds=5),
        AttentionRule.created_at <= run.created_at + timedelta(minutes=5)))).scalars().all()
    out = []
    for rule in rules:
        if rule.status == "active":
            out.append(Sample(run.id, "right", {"accepted": True}, "rule:accepted"))
        elif rule.status == "rejected":
            out.append(Sample(run.id, "wrong", {"accepted": False}, "rule:rejected"))
    return out


DERIVE = {"mail_triage": _mail_triage, "reply_draft": _reply_draft,
          "mission_completion_check": _completion_check, "rule_proposal": _rule_proposal}


async def samples(session: AsyncSession, runs: list[JudgementRun]) -> list[Sample]:
    out: list[Sample] = []
    for run in runs:
        derive = DERIVE.get(run.name)
        if derive is not None and run.error is None:
            out += await derive(session, run)
    return out
