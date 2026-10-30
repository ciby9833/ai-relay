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

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttentionRule, FollowUp, ItemFeedback, JudgementRun, Mission, MissionLog, PendingAction

RIGHT_FEEDBACK = ("handled", "handled_after", "handled_before")
WRONG_FEEDBACK = ("not_mine", "not_worth", "duplicate")
# 全部 16 处判断都有自动的对错来源（见 DERIVE）


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


# ---------- 由判断产生的事项：看他在卡片上的反馈（聊天提取、会议行动项） ----------

ITEM_WINDOW = timedelta(minutes=3)


async def _item_feedback(session: AsyncSession, run: JudgementRun, *conditions) -> list[Sample]:
    """这次判断之后马上建出来的事项（同一会话 / 同一份纪要），每件一个样本：处理了 = 对；不归我 / 不值得 / 重复 = 错。"""
    found = (await session.execute(select(FollowUp).where(
        FollowUp.created_at >= run.created_at - timedelta(seconds=5), FollowUp.created_at <= run.created_at + ITEM_WINDOW,
        *conditions))).scalars().all()
    out = []
    for item in found:
        outcome = (await session.execute(select(ItemFeedback.outcome).where(ItemFeedback.item_id == item.id)
                                         .order_by(ItemFeedback.id.desc()).limit(1))).scalar()
        if outcome in RIGHT_FEEDBACK:
            out.append(Sample(run.id, "right", {"real": True}, f"feedback:{outcome}"))
        elif outcome in WRONG_FEEDBACK:
            out.append(Sample(run.id, "wrong", {"real": False}, f"feedback:{outcome}"))
    return out


async def _chat_extract(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    if not run.subject or not run.subject.startswith("chat:"):
        return []
    from app.proactive.chats import chat_link

    link = chat_link(run.subject.split(":", 1)[1])
    conditions = [FollowUp.url == link, FollowUp.key.like("chat:%")]
    if run.user_id is not None:  # 私聊只归读取它的那位
        conditions.append(FollowUp.user_id == run.user_id)
    return await _item_feedback(session, run, *conditions)


async def _meeting_actions(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    if run.user_id is None:
        return []
    return await _item_feedback(session, run, FollowUp.user_id == run.user_id, FollowUp.key.like("meeting:%"))


# ---------- 邮件往来之后有没有继续：回复后的状态、来信是否回应了在等的事 ----------

FOLLOW_WINDOW = timedelta(days=7)
AGAIN_WINDOW = timedelta(days=3)


async def _thread_after(session: AsyncSession, user_id, thread: str | None, since):
    """同一线程在 since 之后：他又发了几封、对方又来了几封。"""
    from app.models import Signal

    if not thread:
        return None, None
    rows = (await session.execute(select(Signal.kind, Signal.occurred_at).where(
        Signal.user_id == user_id, Signal.kind.in_(("mail", "mail_sent")), Signal.payload["thread_id"].astext == thread,
        Signal.occurred_at > since, Signal.occurred_at <= since + FOLLOW_WINDOW))).all()
    mine = [at for kind, at in rows if kind == "mail_sent"]
    theirs = [at for kind, at in rows if kind == "mail"]
    return mine, theirs


async def _reply_state(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    """“办完了”之后 3 天内他又在这个线程里写信 = 错（事还在继续）；7 天都没有动静 = 对。
    “还要他做”之后 7 天内他又回了信 = 对。“在等对方”之后对方 7 天内回信了 = 对。其余不计。"""
    from app.models import Signal

    signal_id, state = _ref(run, "signal"), (run.output or {}).get("state")
    signal = await session.get(Signal, signal_id) if signal_id else None
    if signal is None or state not in ("done", "mine", "waiting"):
        return []
    mine, theirs = await _thread_after(session, signal.user_id, (signal.payload or {}).get("thread_id"), run.created_at)
    if mine is None:
        return []
    elapsed = datetime.now(UTC) - run.created_at
    if state == "done":
        if any(at <= run.created_at + AGAIN_WINDOW for at in mine):
            return [Sample(run.id, "wrong", {"state": "mine"}, "thread:wrote_again")]
        if elapsed >= FOLLOW_WINDOW and not mine and not theirs:
            return [Sample(run.id, "right", {"state": "done"}, "thread:quiet")]
    elif state == "mine" and mine:
        return [Sample(run.id, "right", {"state": "mine"}, "thread:he_followed_up")]
    elif state == "waiting" and theirs:
        return [Sample(run.id, "right", {"state": "waiting"}, "thread:they_replied")]
    return []


async def _mail_progress(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    """说“办完了”的：之后 3 天内他又在这个线程里写信 = 错；7 天没有动静 = 对。其余结论现在没有可靠的信号，不计。"""
    item_id = _ref(run, "item")
    item = await session.get(FollowUp, item_id) if item_id else None
    if item is None or (run.output or {}).get("verdict") != "done":
        return []
    thread = item.key.removeprefix("mail-thread:") if item.key.startswith("mail-thread:") else None
    mine, theirs = await _thread_after(session, item.user_id, thread, run.created_at)
    if mine is None:
        return []
    if any(at <= run.created_at + AGAIN_WINDOW for at in mine):
        return [Sample(run.id, "wrong", {"verdict": "not_done"}, "thread:wrote_again")]
    if datetime.now(UTC) - run.created_at >= FOLLOW_WINDOW and not mine and not theirs:
        return [Sample(run.id, "right", {"verdict": "done"}, "thread:quiet")]
    return []


# ---------- 跟进邮件草稿：和回复草稿一样，看后来原样发出 / 改过 / 取消 ----------

async def _followup_draft(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    body = (run.output or {}).get("text")
    if not body or run.user_id is None:
        return []
    action = (await session.execute(select(PendingAction).where(
        PendingAction.user_id == run.user_id, PendingAction.kind == "send_mail", PendingAction.summary.like("跟进%"),
        PendingAction.created_at >= run.created_at - timedelta(seconds=5), PendingAction.created_at <= run.created_at + timedelta(minutes=2),
    ).order_by(PendingAction.id).limit(1))).scalars().first()
    if action is None or action.status == "pending":
        return []
    if action.status == "cancelled":
        return [Sample(run.id, "wrong", {"used": False}, "draft:cancelled")]
    if action.status == "done":
        same = (action.payload or {}).get("body", "").strip() == body.strip()
        return [Sample(run.id, "right" if same else "partly", {"used": True}, "draft:sent" + ("" if same else "_edited"))]
    return []


# ---------- 写给人看的文字：数字和时间必须出自输入（自动核对，不用人看） ----------

NUMBER = re.compile(r"\d+(?:[.:：/-]\d+)*")
LIST_MARK = re.compile(r"^\s*(?:\d{1,2}[.、)]|[-*•])\s*", re.M)
CITATION = re.compile(r"[【\[](\d{1,2})[】\]]")


def grounded(text: str, source: str) -> str | None:
    """返回第一个“输入里找不到”的数字 / 时间；都找得到返回 None。列表序号（1. 2.）和个位数不算。"""
    body = LIST_MARK.sub("", text or "")
    for token in NUMBER.findall(body):
        if len(token.replace(".", "").replace(":", "").replace("：", "").replace("/", "").replace("-", "")) < 2:
            continue
        if token not in source:
            parts = re.split(r"[.:：/-]", token)
            if not all(p in source for p in parts if len(p) >= 2):
                return token
    return None


async def _written(session: AsyncSession, run: JudgementRun) -> list[Sample]:
    text = (run.output or {}).get("text")
    if not text:
        return []
    missing = grounded(text, run.input)
    if run.name == "meeting_prep":
        materials = len(re.findall(r"^\[\d+\]", run.input, re.M))
        bad = [n for n in CITATION.findall(text) if not 1 <= int(n) <= max(materials, 0)]
        if bad and materials:
            return [Sample(run.id, "wrong", {"grounded": False}, "citation:missing")]
    if missing:
        return [Sample(run.id, "wrong", {"grounded": False}, "number:not_in_input")]
    return [Sample(run.id, "right", {"grounded": True}, "grounded")]


WRITTEN = ("meeting_prep", "attachment_digest", "morning_brief", "team_digest", "approval_summary", "notice_text")

DERIVE = {"mail_triage": _mail_triage, "reply_draft": _reply_draft,
          "mission_completion_check": _completion_check, "rule_proposal": _rule_proposal,
          "chat_extract": _chat_extract, "chat_extract_retry": _chat_extract, "meeting_actions": _meeting_actions,
          "reply_state": _reply_state, "mail_progress": _mail_progress, "followup_draft": _followup_draft,
          **{name: _written for name in WRITTEN}}


async def samples(session: AsyncSession, runs: list[JudgementRun]) -> list[Sample]:
    out: list[Sample] = []
    for run in runs:
        derive = DERIVE.get(run.name)
        if derive is not None and run.error is None:
            out += await derive(session, run)
    return out
