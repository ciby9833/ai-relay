"""把信号渲染成飞书卡片。"""

from zoneinfo import ZoneInfo

from app import i18n
from app.feishu import cards
from app.models import Signal

RSVP_LABEL = {"accept": "接受", "tentative": "待定", "decline": "拒绝"}


def _when(signal: Signal, timezone: str) -> str:
    if not signal.occurred_at:
        return ""
    return signal.occurred_at.astimezone(ZoneInfo(timezone)).strftime("%m-%d %H:%M")


def signal_card(signal: Signal, timezone: str) -> tuple[dict, str]:
    """返回 (卡片, 卡片发送失败时的纯文本)。"""
    payload = signal.payload or {}
    if signal.kind == "mail":
        title = f"📧 {payload.get('from_name') or payload.get('from_address') or '新邮件'}：{signal.title}"
        text = f"{signal.summary or ''}\n\n<font color='grey'>{signal.reason or ''}</font>".strip()
        buttons = []
        if signal.needs_reply:
            buttons.append(cards.callback(i18n.ui("draft_reply"), "draft_reply", "primary", signal_id=signal.id))
        buttons.append(cards.callback(i18n.ui("mute"), "mute", signal_id=signal.id))
        template = "red" if signal.importance == "urgent" else "blue"
    elif signal.kind == "invitation":
        title = f"📅 会议邀请：{signal.title}"
        text = (
            f"**时间** {_when(signal, timezone)}\n**组织者** {payload.get('organizer') or '-'}\n"
            f"**参会人** {'、'.join(payload.get('attendees') or []) or '-'}"
        )
        buttons = [
            cards.callback(label, "rsvp", "primary" if status == "accept" else "default",
                           signal_id=signal.id, status=status)
            for status, label in RSVP_LABEL.items()
        ]
        template = "blue"
    elif signal.kind == "approval_pending":
        title = f"📝 待你审批：{signal.title}"
        text = signal.body or ""
        buttons = [cards.link("去审批", signal.url)] if signal.url else []
        template = "orange"
    elif signal.kind == "attendance_missing":
        title = f"⏰ {signal.title}"
        text = signal.body or ""
        buttons = []
        template = "red"
    elif signal.kind == "mention":
        title = f"💬 {payload.get('chat_name') or '群聊'}里@你的消息还没回复"
        text = f"> {signal.body or ''}"
        buttons = [cards.link("去回复", signal.url)] if signal.url else []
        template = "orange"
    else:
        title, text, buttons, template = signal.title, signal.body or "", [], "blue"
    fallback = f"**{title}**\n\n{text}"
    return cards.card(title, text or " ", buttons, template), fallback
