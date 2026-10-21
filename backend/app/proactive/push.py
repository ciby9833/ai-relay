"""把 Relay 的一次汇报推到飞书：上面是汇总，下面每件事一个可折叠面板（明细 + 操作按钮）。

发出去的卡片会记下来：用户点了按钮后按最新状态重新渲染、原地更新；
用户引用这张卡片回复时，也能据此知道他指的是哪几件事。
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.feishu import cards as fc
from app.feishu.client import FeishuClient
from app.models import AttentionRule, FeishuCard, FollowUp, Mission, PendingAction, Signal, User
from app import i18n, insights
from app.proactive.settings import language_of
from app.proactive import attention
from app.proactive.cards import ask
from app.proactive.render import RSVP_LABEL
from app.sources import approval

KIND_ICON = {
    "approval": "📝", "reply": "📧", "review": "📄", "invitation": "📅",
    "attendance": "⏰", "mention": "💬", "waiting": "⏳", "request": "🙋", "biz": "🏢",
}
DETAIL_FIELDS = 6


def _time(value: str | None, timezone: str) -> str:
    return datetime.fromisoformat(value).astimezone(ZoneInfo(timezone)).strftime("%m-%d %H:%M") if value else ""


def panel(header: str, elements: list[dict], expanded: bool = False) -> dict:
    return {
        "tag": "collapsible_panel",
        "expanded": expanded,
        "header": {
            "title": {"tag": "markdown", "content": header},
            "vertical_align": "center",
            "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "size": "16px 16px"},
            "icon_position": "right",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "6px"},
        "vertical_spacing": "8px",
        "padding": "8px 10px 8px 10px",
        "elements": elements,
    }


async def _item_panel(session: AsyncSession, item: FollowUp, user: User, expanded: bool) -> tuple[dict, str]:
    icon = KIND_ICON.get(item.kind, "•")
    if item.status != "open":
        line = f"✅ ~~{item.title}~~　<font color='grey'>{item.resolution or ''}</font>"
        return fc.markdown(line), line
    due = ""
    if item.due_at:
        due = f"　<font color='red'>{item.due_at.astimezone(ZoneInfo(user.timezone)):%m-%d %H:%M} 前</font>"
    action = await session.get(PendingAction, item.action_id) if item.action_id else None
    color = "grey" if item.owner == "others" else "blue"
    # 折叠时也能一眼看到要你做什么
    header = f"{icon} **{item.title}**{due}\n<font color='{color}'>→ {ask(item, action)}</font>"
    body: list[str] = []
    if item.summary:
        body.append(item.summary)
    signal = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
    if item.kind == "approval" and signal:
        fields = ((signal.payload.get("detail") or {}).get("fields") or [])[:DETAIL_FIELDS]
        if fields:
            body.append("\n".join(f"**{f['name']}**：{f['value'][:120]}" for f in fields))
    if item.recommendation:
        body.append(f"💡 {item.recommendation}")
    buttons: list[dict] = []
    if action and action.status == "pending":
        if action.kind == "send_mail":
            quoted = action.payload["body"].replace("\n", "\n> ")
            others = action.payload.get("others") or []
            scope = (f"，抄送 {len(others)} 人" if action.payload.get("reply_all")
                     else f"，只回复发件人（原邮件另有 {len(others)} 人，可在网页改成回复全部）" if others else "")
            body.append(f"✍️ Relay 已起草（给 {action.payload.get('to')}{scope}）：\n> {quoted}")
            label = "发送跟进邮件" if action.summary.startswith("跟进") else "发送这封回复"
            buttons += [
                fc.callback(label, "confirm", "primary", action_id=action.id),
                fc.link("去网页修改", get_settings().frontend_url),
            ]
        elif action.kind == "calendar_rsvp" and signal:
            suggested = action.payload["status"]
            buttons.append(fc.callback(f"按建议{RSVP_LABEL[suggested]}", "confirm", "primary", action_id=action.id))
            buttons += [
                fc.callback(label, "rsvp", signal_id=signal.id, status=status)
                for status, label in RSVP_LABEL.items() if status != suggested
            ]
    native_approval = item.kind == "approval" and approval.needs_input(signal.payload.get("detail") if signal else None)
    if item.kind == "approval" and signal and signal.status != "done" and not native_approval:
        buttons += [
            fc.callback(i18n.ui("approve"), "approval", "primary", signal_id=signal.id, approve=True),
            fc.callback(i18n.ui("reject"), "approval", "danger", signal_id=signal.id, approve=False),
        ]
    if item.url:
        # 需要补填/分配的审批：主按钮就是打开飞书原生审批
        buttons.append(
            fc.link("去飞书审批", insights.open_link(item, "feishu"), "primary") if native_approval
            else fc.link("在飞书查看", insights.open_link(item, "feishu"))
        )
    buttons.append(fc.callback(i18n.ui("done"), "item_done", item_id=item.id))
    if item.owner == "me" and attention.quieter_match(item, signal) is not None and item.attention not in ("brief", "mute"):
        buttons.append(fc.callback(i18n.ui("quieter"), "quieter", item_id=item.id))
    elements = [fc.markdown("\n\n".join(body))] if body else []
    elements.append(fc.button_row(buttons))
    return panel(header, elements, expanded), f"{header}\n" + "\n".join(body)


def _action_panel(action: PendingAction, expanded: bool, timezone: str) -> tuple[dict, str]:
    from app import automation

    if action.status != "pending":
        if action.auto and action.status == "done":
            # 按授权自动办的：告诉他办了什么，能撤销的给撤销按钮
            line = f"🤖 **{i18n.ui('auto_done')}**：{action.result or action.summary}"
            if action.undone_at:
                return fc.markdown(f"~~{line}~~　<font color='grey'>{i18n.ui('undone')}</font>"), line
            if automation.undoable(action):
                return panel(line, [fc.button_row([fc.callback(i18n.ui("undo"), "undo", action_id=action.id)])], True), line
            return fc.markdown(line), line
        line = f"✅ ~~{action.summary}~~　<font color='grey'>{action.result or action.status}</font>"
        return fc.markdown(line), line
    p = action.payload
    body = [f"**对象**：{p.get('to')}"] if p.get("to") else []
    if action.kind == "base_record":
        body += [f"**{k}**：{v}" for k, v in (p.get("shown") or {}).items()]
        if p.get("previous"):
            body.append(f"<font color='grey'>{p['previous']}</font>")
    if action.kind == "create_event" and p.get("start"):
        body.append(f"**时间**：{_time(p['start'], timezone)}")
    if action.kind == "create_task" and p.get("due"):
        body.append(f"**截止**：{_time(p['due'], timezone)}")
    if p.get("body"):
        body.append("> " + p["body"].replace("\n", "\n> "))
    header = f"✍️ **{action.summary}**\n<font color='blue'>→ 确认后执行</font>"
    elements = [fc.markdown("\n".join(body))] if body else []
    buttons = [fc.callback(i18n.ui("confirm_run"), "confirm", "primary", action_id=action.id)]
    if action.scheduled_task_id:
        # 定时任务里的操作：确认的同时可以授权这个任务以后直接办（只限同一个对象）
        buttons.append(fc.callback(i18n.ui("confirm_and_grant"), "grant", action_id=action.id))
    buttons += [fc.link("去网页修改", get_settings().frontend_url), fc.callback(i18n.ui("not_needed"), "cancel", action_id=action.id)]
    elements.append(fc.button_row(buttons))
    return panel(header, elements, expanded), f"{action.summary}\n" + "\n".join(body)


async def _rule_panel(session: AsyncSession, user: User, rule_id: int) -> tuple[dict | None, str]:
    """候选提醒规则：依据是他以前说过的话，点“启用”才生效。"""
    rule = await session.get(AttentionRule, rule_id)
    if rule is None or rule.user_id != user.id:
        return None, ""
    if rule.status != "proposed":
        state = i18n.ui("rule_enabled") if rule.status == "active" else i18n.ui("rule_ignored")
        line = f"🔔 ~~{rule.label}~~　<font color='grey'>{state}</font>" if rule.status == "rejected" else f"🔔 {rule.label}　<font color='grey'>{state}</font>"
        return fc.markdown(line), line
    header = f"🔔 **{rule.label}**"
    body = f"<font color='grey'>{i18n.ui('rule_evidence')}「{(rule.evidence or '')[:120]}」</font>"
    buttons = fc.button_row([
        fc.callback(i18n.ui("rule_accept"), "rule_accept", "primary", rule_id=rule.id),
        fc.callback(i18n.ui("rule_reject"), "rule_reject", rule_id=rule.id),
    ])
    return panel(header, [fc.markdown(body), buttons], True), f"{header}\n{body}"


async def render(
    session: AsyncSession, user: User, title: str, text: str, sections: list
) -> tuple[dict, str]:
    """sections: [[分组标题, [卡片数据...]], ...]；卡片数据与主线消息里的卡片相同。"""
    i18n.current.set(await language_of(session, user))
    total_items = sum(1 for _, group in sections for c in group if c["kind"] == "item")
    elements = [fc.markdown(text)] if text.strip() else []
    fallback = [text] if text.strip() else []
    for label, group in sections:
        if not group:
            continue
        if label:
            elements.append(fc.markdown(f"**{label}**"))
            fallback.append(f"【{label}】")
        for card in group:
            if card["kind"] == "item":
                item = await session.get(FollowUp, card["item_id"])
                if item is None:
                    continue
                element, line = await _item_panel(session, item, user, expanded=total_items == 1)
            elif card["kind"] == "event":
                join = f"　[加入会议]({card['meeting_url']})" if card.get("meeting_url") else ""
                pending = "　<font color='orange'>未回复邀请</font>" if card.get("rsvp") == "needs_action" else ""
                line = f"📅 {_time(card['start'], user.timezone)}　**{card['title']}**{pending}{join}"
                element = fc.markdown(line)
            elif card["kind"] == "mail":
                line = f"📧 **{card['from']}**《{card['subject']}》{card.get('summary') or ''}"
                element = fc.markdown(line)
            elif card["kind"] == "action":
                action = await session.get(PendingAction, card["action_id"])
                if action is None:
                    continue
                element, line = _action_panel(action, len(group) <= 2, user.timezone)
            elif card["kind"] == "mission":
                mission = await session.get(Mission, card["mission_id"])
                if mission is None:
                    continue
                done = sum(1 for s in mission.plan if s.get("status") == "done")
                state = {"active": "推进中", "waiting": "在等对方", "asking": "在等你回答", "done": "已完成",
                         "failed": "没办成", "cancelled": "已取消"}.get(mission.status, mission.status)
                line = f"🧭 **长期任务：{mission.title}**　<font color='grey'>{state}"
                line += f" · 计划 {done}/{len(mission.plan)}</font>" if mission.plan else "</font>"
                element = fc.markdown(line)
            elif card["kind"] == "rule":
                element, line = await _rule_panel(session, user, card["rule_id"])
                if element is None:
                    continue
            elif card["kind"] == "note":
                line = card["text"]
                element = fc.markdown(line)
            else:
                continue
            elements.append(element)
            fallback.append(line)
    return fc.card(title, text, elements=elements), "\n\n".join(fallback)


async def push(
    session: AsyncSession, feishu: FeishuClient, user: User, title: str, text: str,
    cards: list[dict] | None = None, sections: list | None = None,
) -> None:
    sections = sections if sections is not None else [["", cards or []]]
    card, fallback = await render(session, user, title, text, sections)
    message_id = await feishu.send_card(user.feishu_open_id, card, fallback)
    if message_id:
        # 只加入会话，由调用方提交
        session.add(FeishuCard(message_id=message_id, user_id=user.id, title=title, text=text, sections=sections))


async def refresh(session: AsyncSession, feishu: FeishuClient, user: User, message_id: str | None) -> None:
    """按最新状态重新渲染一张已发出的卡片（例如点了“批准”之后按钮变成“已处理”）。"""
    record = await session.get(FeishuCard, message_id) if message_id else None
    if record is None or record.user_id != user.id:
        return
    card, _ = await render(session, user, record.title, record.text, record.sections)
    await feishu.tenant_api("PATCH", f"/im/v1/messages/{message_id}", json={"content": json.dumps(card, ensure_ascii=False)})
