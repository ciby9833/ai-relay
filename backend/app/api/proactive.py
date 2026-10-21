"""主动助手相关接口：动态（信号）、待确认操作、设置、数据源状态。"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import automation, i18n, insights
from app.db import SessionLocal
from fastapi.responses import RedirectResponse
from app.deps import FeishuDep, SessionDep, UserDep
from app.home import post
from app.llm.base import LLMError
from app.models import AttentionRule, FollowUp, PendingAction, ScheduledTask, Signal, SourceState, User
from app.proactive import actions, attention, cards, casefile, items
from app.proactive.engine import morning_brief, sync_sources
from app.proactive.settings import get_settings_row, language_of, merged

router = APIRouter(prefix="/api", tags=["proactive"])


@router.get("/signals")
async def list_signals(session: SessionDep, user: UserDep):
    result = await session.execute(
        select(Signal)
        .where(Signal.user_id == user.id, Signal.status.not_in(["scheduled", "watching"]))
        .order_by(Signal.created_at.desc())
        .limit(80)
    )
    return [
        {
            "id": s.id, "source": s.source, "kind": s.kind, "title": s.title,
            "summary": s.summary or (s.body or "")[:160], "url": s.url,
            "status": s.status, "importance": s.importance, "needs_reply": s.needs_reply,
            "from": (s.payload or {}).get("from"),
            "occurred_at": (s.occurred_at or s.created_at).isoformat(),
        }
        for s in result.scalars()
    ]


@router.get("/actions")
async def list_actions(session: SessionDep, user: UserDep):
    result = await session.execute(
        select(PendingAction).where(PendingAction.user_id == user.id)
        .order_by(PendingAction.id.desc()).limit(30)
    )
    return [
        {
            "id": a.id, "kind": a.kind, "summary": a.summary, "status": a.status, "result": a.result,
            "body": a.payload.get("body"), "to": a.payload.get("to"), "created_at": a.created_at.isoformat(),
        }
        for a in result.scalars()
    ]


@router.post("/actions/{action_id}/{decision}")
async def decide_action(
    action_id: int, decision: Literal["confirm", "cancel", "grant", "undo"], session: SessionDep, user: UserDep, feishu: FeishuDep
):
    """confirm 执行；cancel 不用了；grant 执行并授权所属定时任务以后直接办；undo 撤销一次已执行的操作。"""
    try:
        action = await actions.own_action(session, user, action_id)
    except actions.ActionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if decision == "undo":
        message = await automation.undo(session, feishu, user, action)
        await session.commit()
        if action.undone_at is None:
            raise HTTPException(status_code=400, detail=message)
        return {"message": message, "status": action.status}
    if decision in ("confirm", "grant"):
        message = await actions.execute(session, feishu, user, action)
        if decision == "grant" and action.status == "done" and action.scheduled_task_id:
            task = await session.get(ScheduledTask, action.scheduled_task_id)
            if task is not None and task.user_id == user.id:
                label = automation.grant_task(task, action)
                message = f"{message}。以后《{task.title}》会直接{label}"
                await insights.record(session, user, "grant", action=action)
    else:
        message = actions.cancel(action)
        await insights.record(session, user, "cancel", action=action)
    await session.commit()
    if decision in ("confirm", "grant") and action.status != "done":
        # 没执行成功：让前端把原因显示在卡片上
        raise HTTPException(status_code=400, detail=message)
    return {"message": message, "status": action.status}


@router.post("/signals/{signal_id}/draft-reply")
async def draft_reply(signal_id: int, session: SessionDep, user: UserDep, feishu: FeishuDep):
    try:
        action = await actions.prepare_mail_reply(session, feishu, user, signal_id)
    except (actions.ActionError, LLMError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await items.link_action(session, user, action)
    # 草稿出现在主线里，用户可以直接改、直接发，或者接着用一句话让 Relay 改
    await post(
        session, user, event=f"用户让 Relay 起草对邮件 #{signal_id} 的回复（待确认操作 #{action.id}）",
        text="草稿在这里，可以直接改；也可以告诉我怎么调整。确认后我再发出去。",
        cards=[cards.draft_card(action)],
    )
    await session.commit()
    return {"action_id": action.id}


class DraftBody(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=50_000)
    reply_all: bool | None = None


@router.patch("/actions/{action_id}")
async def edit_draft(action_id: int, data: DraftBody, session: SessionDep, user: UserDep):
    try:
        action = await actions.own_action(session, user, action_id)
        actions.update_draft(action, data.body, data.reply_all)
    except actions.ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await insights.record(session, user, "edit", action=action)
    await session.commit()
    return {"ok": True}


class RsvpBody(BaseModel):
    status: Literal["accept", "tentative", "decline"]


@router.post("/signals/{signal_id}/rsvp")
async def rsvp(signal_id: int, data: RsvpBody, session: SessionDep, user: UserDep, feishu: FeishuDep):
    """在日程卡片上点接受/拒绝：点击本身就是用户的明确指令，直接执行。"""
    try:
        action = await actions.prepare_rsvp(session, user, signal_id, data.status)
    except actions.ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    message = await actions.execute(session, feishu, user, action)
    if action.status != "done":
        await session.rollback()  # 没回复成功就不留这条待确认操作
        raise HTTPException(status_code=400, detail=message)
    await session.commit()
    return {"message": message, "status": action.status}


@router.get("/board")
async def board(session: SessionDep, user: UserDep):
    """跟进看板：等你 / 等别人 / Relay 在办。"""
    result = await session.execute(
        select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.status == "open")
        .order_by(FollowUp.importance.desc(), FollowUp.due_at.asc().nulls_last(), FollowUp.updated_at.desc())
    )
    open_items = [await items.item_json(session, i) for i in result.scalars()]
    now = datetime.now(UTC)
    local_now = now.astimezone(ZoneInfo(user.timezone))
    day_end = local_now.replace(hour=23, minute=59).astimezone(UTC)
    settings = merged((await get_settings_row(session, user)).data)
    await session.commit()
    # Relay 在办：它接下来会主动替你做的准备和盯梢
    relay = []
    meetings = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind == "meeting", Signal.status == "scheduled",
                             Signal.occurred_at.between(now, day_end)).order_by(Signal.occurred_at)
    )).scalars().all()
    for meeting in meetings:
        if (meeting.payload or {}).get("rsvp") == "decline" or (meeting.payload or {}).get("all_day"):
            continue
        prep_at = meeting.occurred_at - timedelta(minutes=settings["meeting_brief_minutes"])
        relay.append({"kind": "meeting_prep", "title": f"准备《{meeting.title}》的会前资料",
                      "detail": f"{prep_at.astimezone(ZoneInfo(user.timezone)):%H:%M} 发给你", "at": prep_at.isoformat(),
                      "title_ui": {"key": "board.prepare", "values": {"title": meeting.title}},
                      "detail_ui": {"key": "board.preparedAt", "values": {"time": f"{prep_at.astimezone(ZoneInfo(user.timezone)):%H:%M}"}}})
    watching = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind == "mention", Signal.status == "watching")
    )).scalars().all()
    for signal in watching:
        relay.append({"kind": "watch", "title": f"盯着{signal.payload.get('chat_name') or '群聊'}里@你的消息",
                      "detail": "两小时内没回会提醒你", "at": signal.occurred_at.isoformat() if signal.occurred_at else None,
                      "title_ui": {"key": "board.mentions", "values": {"name": signal.payload['chat_name']}} if signal.payload.get('chat_name') else {"key": "board.groupMentions"},
                      "detail_ui": {"key": "board.twoHours"}})
    for item in open_items:
        if item["owner"] == "others" and item["remind_at"]:
            relay.append({"kind": "watch", "title": f"盯着 {item['waiting_on'] or '对方'} 的回复",
                          "detail": "没回的话会提醒你并起草跟进", "at": item["remind_at"],
                          "title_ui": {"key": "board.reply", "values": {"name": item['waiting_on']}} if item['waiting_on'] else {"key": "board.replyUnknown"},
                          "detail_ui": {"key": "board.followup"}})
    return {
        "me": [i for i in open_items if i["owner"] == "me"],
        "others": [i for i in open_items if i["owner"] == "others"],
        "relay": relay,
    }


# 写成两条固定路径：用 /items/{id}/{decision} 这种通配会先于后面的 /items/{id}/approval 匹配，
# 把批准请求当成 decision="approval" 拦下来返回 422
@router.post("/items/{item_id}/done")
async def mark_item_done(item_id: int, session: SessionDep, user: UserDep):
    return await _close_item(item_id, "done", session, user)


@router.post("/items/{item_id}/dismiss")
async def dismiss_item(item_id: int, session: SessionDep, user: UserDep):
    return await _close_item(item_id, "dismiss", session, user)


async def _close_item(item_id: int, decision: Literal["done", "dismiss"], session, user):
    item = await session.get(FollowUp, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="事项不存在")
    items.close(item, "done" if decision == "done" else "dismissed", "你标记为已处理" if decision == "done" else "你说不用再跟了")
    await insights.record(session, user, decision, item=item)
    if item.action_id:
        action = await session.get(PendingAction, item.action_id)
        if action and action.status == "pending":
            actions.cancel(action)
    await session.commit()
    return {"ok": True}


class ApprovalBody(BaseModel):
    approve: bool
    comment: str = Field(default="", max_length=1000)


@router.post("/items/{item_id}/approval")
async def decide_approval(item_id: int, data: ApprovalBody, session: SessionDep, user: UserDep, feishu: FeishuDep):
    """在审批卡片上点批准/驳回：点击本身就是用户的明确指令，直接执行。"""
    item = await session.get(FollowUp, item_id)
    if item is None or item.user_id != user.id or item.kind != "approval" or not item.signal_ids:
        raise HTTPException(status_code=404, detail="审批事项不存在")
    try:
        action = await actions.prepare_approval(session, user, item.signal_ids[-1], data.approve, data.comment)
    except actions.ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    message = await actions.execute(session, feishu, user, action)
    if action.status != "done":
        await session.rollback()
        raise HTTPException(status_code=400, detail=message)
    await session.commit()
    await items.advance(session, user)
    return {"message": message}


class SettingsBody(BaseModel):
    proactive: bool
    brief_enabled: bool = True
    sources: dict[str, bool]
    quiet_start: str = Field(pattern=r"^\d{2}:\d{2}$")
    quiet_end: str = Field(pattern=r"^\d{2}:\d{2}$")
    brief_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    meeting_brief_minutes: int = Field(ge=0, le=120)
    max_interrupts_per_hour: int = Field(ge=0, le=60)
    digest_times: list[Annotated[str, Field(pattern=r"^\d{2}:\d{2}$")]] = Field(default=["11:30", "16:30"], max_length=6)
    language: str = Field(default="auto", pattern="^(auto|zh|en|id)$")


@router.get("/settings")
async def get_settings(session: SessionDep, user: UserDep):
    row = await get_settings_row(session, user)
    await session.commit()
    states = (await session.execute(select(SourceState).where(SourceState.user_id == user.id))).scalars().all()
    return {
        "settings": merged(row.data),
        "detected_language": (row.data or {}).get("detected_language"),
        "sources": {
            s.source: {"last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None, "error": s.last_error}
            for s in states
        },
    }


@router.put("/settings")
async def put_settings(body: SettingsBody, session: SessionDep, user: UserDep):
    row = await get_settings_row(session, user)
    # 合并而不是覆盖：识别到的语言等后台记录的字段要保留
    row.data = {**(row.data or {}), **body.model_dump()}
    await session.commit()
    return {"settings": merged(row.data)}


# ---------- 事项档案：相关材料 ----------


async def _own_item(session, user: User, item_id: int) -> FollowUp:
    item = await session.get(FollowUp, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="事项不存在")
    return item


@router.get("/items/{item_id}/case")
async def item_case(item_id: int, session: SessionDep, user: UserDep, feishu: FeishuDep):
    """这件事的相关材料：来源、时间、关联依据；弱关联（只是同一个人）单独标出。"""
    item = await _own_item(session, user, item_id)
    refs = await casefile.build(session, user, item, feishu)
    await session.commit()
    return {"refs": [r.json() for r in refs]}


class OpenRefBody(BaseModel):
    ref: str = Field(min_length=3, max_length=2000)


@router.post("/items/{item_id}/case/open")
async def open_case_ref(item_id: int, body: OpenRefBody, session: SessionDep, user: UserDep, feishu: FeishuDep):
    """看一份材料的原文：每次都按当前用户重新校验（见 casefile.open_ref）。"""
    item = await _own_item(session, user, item_id)
    try:
        result = await casefile.open_ref(session, feishu, user, item, body.ref)
    except casefile.RefError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await session.commit()
    return result


# ---------- 提醒规则：哪类事立刻说 / 攒着说 / 只放简报 / 不提醒 ----------


def _rule_json(rule: AttentionRule) -> dict:
    return {"id": rule.id, "match": rule.match, "level": rule.level, "label": rule.label, "source": rule.source,
            "status": rule.status, "evidence": rule.evidence,
            "hits": rule.hits, "last_hit_at": rule.last_hit_at.isoformat() if rule.last_hit_at else None,
            "created_at": rule.created_at.isoformat() if rule.created_at else None}


class RuleBody(BaseModel):
    level: Literal["now", "batch", "brief", "mute"]


async def _own_rule(session, user: User, rule_id: int) -> AttentionRule:
    rule = await session.get(AttentionRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="规则不存在")
    return rule


@router.get("/notify-rules")
async def list_rules(session: SessionDep, user: UserDep):
    """生效的规则和等他确认的候选（他拒绝过的不列）。"""
    return [_rule_json(r) for r in await attention.rules_for(session, user, status=None) if r.status != "rejected"]


@router.post("/notify-rules/{rule_id}/{decision}")
async def decide_rule(rule_id: int, decision: Literal["accept", "reject"], session: SessionDep, user: UserDep):
    """候选规则：启用 / 不用。"""
    try:
        rule = await attention.decide_proposal(session, user, rule_id, decision == "accept")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return _rule_json(rule)


@router.put("/notify-rules/{rule_id}")
async def update_rule(rule_id: int, body: RuleBody, session: SessionDep, user: UserDep):
    rule = await _own_rule(session, user, rule_id)
    rule = await attention.set_rule(session, user, rule.match, body.level, "web")
    await session.commit()
    return _rule_json(rule)


@router.delete("/notify-rules/{rule_id}")
async def delete_rule(rule_id: int, session: SessionDep, user: UserDep):
    await session.delete(await _own_rule(session, user, rule_id))
    await session.commit()
    return {"ok": True}


@router.post("/items/{item_id}/quieter")
async def quieter(item_id: int, body: RuleBody, session: SessionDep, user: UserDep):
    """看板上“这类以后……”：按这件事的类别设一条规则。"""
    item = await session.get(FollowUp, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="事项不存在")
    i18n.current.set(await language_of(session, user))
    try:
        message = await attention.quieter(session, user, item, body.level, "web")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await insights.record(session, user, "mute" if body.level in ("brief", "mute") else "louder", item=item)
    await session.commit()
    return {"message": message}


@router.post("/sync")
async def sync_now(session: SessionDep, user: UserDep, feishu: FeishuDep):
    """立即同步一次所有数据源（不推送），方便刚授权后马上看到效果。"""
    settings = merged((await get_settings_row(session, user)).data)
    await sync_sources(session, feishu, user, settings, force=True)
    return {"ok": True, "at": datetime.now(UTC).isoformat()}


@router.post("/brief")
async def brief_now(session: SessionDep, user: UserDep, feishu: FeishuDep):
    """立即生成并推送一份简报。"""
    settings = merged((await get_settings_row(session, user)).data)
    await morning_brief(session, feishu, user, settings, force=True)
    return {"ok": True}


@router.get("/open/{item_id}")
async def open_original(item_id: int, u: str, s: str, f: str = "web"):
    """“在飞书查看”：先记下他打开了原文（衡量 Relay 给的信息够不够他直接做决定），再跳过去。

    链接带签名，不依赖登录态：飞书内置浏览器里没有 Relay 的 cookie。
    """
    if not insights.verify(item_id, u, s):
        raise HTTPException(status_code=404)
    async with SessionLocal() as session:
        item = await session.get(FollowUp, item_id)
        if item is None or str(item.user_id) != u or not item.url:
            raise HTTPException(status_code=404)
        user = await session.get(User, item.user_id)
        insights.via.set("feishu_card" if f == "feishu" else "web")
        await insights.record(session, user, "open_original", item=item)
        await session.commit()
        url = item.url
    return RedirectResponse(url, status_code=302)


@router.get("/insights")
async def get_insights(session: SessionDep, user: UserDep, days: int = 7):
    """这段时间他怎么处理的：多少件不看原文就处理了、多少件替他办掉了、哪些类别他总是同样处理。"""
    return await insights.summary(session, user, max(1, min(days, 90)))


def _push_kind(title: str) -> str:
    """按卡片标题归类（三种语言的标题前缀）：立刻打扰 / 汇总 / 简报 / 会前准备 / 任务 / 其他。"""
    prefixes = {key: [v.split("{")[0] for v in i18n._STRINGS[key].values()] for key in ("things_to_know", "digest")}
    if any(title.startswith(p) for p in prefixes["things_to_know"]):
        return "interrupt"
    if any(title.startswith(p) for p in prefixes["digest"]):
        return "digest"
    if title.startswith("Relay 简报"):
        return "brief"
    if title.startswith("🗓"):
        return "meeting"
    if title.startswith("Relay 任务"):
        return "mission"
    return "other"


@router.get("/insights/notifications")
async def notification_stats(session: SessionDep, user: UserDep, days: int = 7, offset: int = 0):
    """Complete local calendar days, including zero-push days; today is intentionally excluded."""
    from app.models import FeishuCard, UserDecision

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以查看")
    days, offset = max(1, min(days, 30)), max(0, min(offset, 30))
    now = datetime.now(UTC)
    users = {u.id: u for u in (await session.execute(select(User))).scalars()}
    stats, windows = {}, {}
    keys = ("pushes", "interrupt", "digest", "brief", "meeting", "mission", "other", "items", "handled")
    for uid, person in users.items():
        tz = ZoneInfo(person.timezone)
        end = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=offset)
        start = end - timedelta(days=days)
        # Exclude days before account creation from the per-person denominator.
        start = max(start, person.created_at.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0))
        if start >= end:
            continue
        windows[uid] = (start, end)
        stats[uid] = {(start + timedelta(days=i)).strftime("%Y-%m-%d"): dict.fromkeys(keys, 0)
                      for i in range((end.date() - start.date()).days)}

    def day_of(uid, moment):
        if uid not in windows:
            return None
        start, end = windows[uid]
        return stats[uid].get(moment.astimezone(start.tzinfo).strftime("%Y-%m-%d")) if start <= moment < end else None

    since = now - timedelta(days=days + offset + 2)
    for card in (await session.execute(select(FeishuCard).where(FeishuCard.created_at >= since))).scalars():
        entry = day_of(card.user_id, card.created_at)
        if entry is not None:
            entry["pushes"] += 1
            entry[_push_kind(card.title or "")] += 1
    for uid, created in (await session.execute(select(FollowUp.user_id, FollowUp.created_at).where(FollowUp.created_at >= since))).all():
        entry = day_of(uid, created)
        if entry is not None:
            entry["items"] += 1
    for uid, created in (await session.execute(
        select(UserDecision.user_id, UserDecision.created_at).where(UserDecision.created_at >= since,
            UserDecision.decision != "open_original", UserDecision.via != "auto")
    )).all():
        entry = day_of(uid, created)
        if entry is not None:
            entry["handled"] += 1
    return sorted([{"user_id": str(uid), "user": users[uid].name, "timezone": users[uid].timezone,
                    "days": by_day, "observed_days": len(by_day),
                    "pushes_per_day": round(sum(d["pushes"] for d in by_day.values()) / len(by_day), 2)}
                   for uid, by_day in stats.items()], key=lambda r: -r["pushes_per_day"])


@router.get("/automations")
async def list_automations(session: SessionDep, user: UserDep):
    """自动办的事：当前有哪些授权（可收回），最近按授权办了什么（能撤销的可撤销）。"""
    return await automation.overview(session, user)


class RevokeBody(BaseModel):
    source: Literal["mission", "task"]
    source_id: int
    kind: str = Field(max_length=32)
    index: int | None = None


@router.post("/automations/revoke")
async def revoke_automation(body: RevokeBody, session: SessionDep, user: UserDep):
    try:
        message = await automation.revoke(session, user, body.source, body.source_id, body.kind, body.index)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await insights.record(session, user, "revoke", detail={"source": body.source, "source_id": body.source_id, "kind": body.kind})
    await session.commit()
    return {"message": message}
