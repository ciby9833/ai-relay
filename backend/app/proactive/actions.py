"""需要用户确认才执行的操作：先准备（起草邮件、拟定会议回复），点确认后才真正执行。"""

import json
import re
import uuid
import httpx
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu import cards
from app.config import get_settings
from app import i18n, insights
from app.feishu.client import FeishuClient, FeishuError, needs_reauth, rich_text
from app.memory import service as memory_service
from app.models import PendingAction, Signal, User
from app.proactive import chats
from app.proactive.llm import complete_structured, complete_text
from app.proactive.prompts import DRAFT_SYSTEM
from app.proactive.render import RSVP_LABEL
from app.sources import approval, calendar, cloud, docs, im, mail, scheduling, tasks, sheets, bitable


class ActionError(Exception):
    pass


async def own_signal(session: AsyncSession, user: User, signal_id: int, kind: str | None = None) -> Signal:
    signal = await session.get(Signal, signal_id)
    if signal is None or signal.user_id != user.id or (kind and signal.kind != kind):
        raise ActionError(f"找不到这条记录 #{signal_id}")
    return signal


async def own_action(session: AsyncSession, user: User, action_id: int) -> PendingAction:
    # 网页与飞书回调可能同时确认同一个操作，锁持有到外层事务提交。
    action = (await session.execute(select(PendingAction).where(
        PendingAction.id == action_id, PendingAction.user_id == user.id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if action is None or action.user_id != user.id:
        raise ActionError(f"找不到待确认操作 #{action_id}")
    return action


async def _profile(session: AsyncSession, user: User) -> str:
    memories = await memory_service.list_memories(session, user.id, "profile", 30)
    return "\n".join(f"- {m.content}" for m in reversed(memories)) or "（暂无）"


_SPLIT = re.compile(r"[\s:：\-—_/|,，、【】\[\]()（）]+")


def keywords(subject: str) -> list[str]:
    subject = re.sub(r"^((re|fw|fwd|回复|转发)\s*[:：]\s*)+", "", subject or "", flags=re.I)
    return [w for w in _SPLIT.split(subject) if len(w) >= 2 and not w.isdigit()][:4]


DRAFT_TOOL = {
    "name": "draft_reply",
    "description": "起草回复，并决定回复全部还是只回发件人",
    "input_schema": {"type": "object", "properties": {
        "body": {"type": "string", "description": "回复正文"},
        "reply_all": {"type": "boolean", "description": "是否回复全部"},
        "why": {"type": "string", "description": "一句话说明为什么回复全部 / 只回发件人（给他看）"}},
        "required": ["body", "reply_all", "why"], "additionalProperties": False},
}
MATERIAL_CHARS = 2500


async def _background(session: AsyncSession, feishu: FeishuClient, user: User, signal: Signal, words: list[str]) -> tuple[list[str], list[str]]:
    """这封信的相关材料：附件原文、正文里的飞书文档、提到这件事的会议纪要、相关群聊、知识库。返回 (给模型看的材料, 给他看的“参考了什么”)。"""
    original = signal.payload
    background, references = [], []
    for attachment in (await mail.attachments_of(feishu, user, signal))[:2]:
        try:
            text = await mail.attachment_text(feishu, user, signal.external_id, attachment)
            background.append(f"附件《{attachment['filename']}》：{text[:MATERIAL_CHARS]}")
            references.append(f"附件《{attachment['filename']}》")
        except Exception:  # noqa: BLE001 - 读不了的附件跳过，不影响起草
            references.append(f"附件《{attachment['filename']}》（没能读取）")
    from app.proactive import casefile

    for url in casefile._links(original.get("body"))[:2]:
        try:
            doc = await cloud.read_url(feishu, user, url)
            background.append(f"邮件里链接的文档《{doc.get('title') or url}》：{str(doc.get('content') or '')[:MATERIAL_CHARS]}")
            references.append(f"邮件里链接的文档《{doc.get('title') or '文档'}》")
        except FeishuError:
            pass
    subject = (original.get("subject") or "").lower()
    meetings = (await session.execute(select(Signal).where(
        Signal.user_id == user.id, Signal.kind == "meeting", Signal.payload["minutes"].isnot(None),
    ).order_by(Signal.occurred_at.desc()).limit(30))).scalars().all()
    for meeting in meetings:
        title = (meeting.title or "").strip()
        if len(title) >= 4 and title.lower() in subject:
            background.append(f"会议《{title}》的纪要要点：{(meeting.payload['minutes'].get('summary') or '')[:MATERIAL_CHARS]}")
            references.append(f"会议《{title}》的纪要")
            break
    try:
        for doc in await docs.search(feishu, user, " ".join(words) or signal.title, limit=3):
            references.append(f"文档《{doc['title']}》")
            background.append(f"文档《{doc['title']}》：{doc['summary']}")
    except FeishuError:
        pass
    for message in await chats.related(session, user, words, limit=5):
        references.append(f"群聊里 {message.sender_name or '某人'} 的消息")
        background.append(f"群聊 {message.sender_name or '某人'}（{message.created_at:%m-%d}）：{message.text[:300]}")
    return background, references


async def write_reply(
    session: AsyncSession, feishu: FeishuClient, user: User, signal: Signal, instructions: str = "",
) -> tuple[str, list[str], bool, str]:
    """起草回复正文，并判断该回复全部还是只回发件人。返回 (正文, 参考了什么, 是否回复全部, 理由)。"""
    original = signal.payload
    words = keywords(original.get("subject") or signal.title)
    background, references = await _background(session, feishu, user, signal, words)
    from app.proactive import casefile

    earlier = await casefile.thread_history(session, user, signal)
    others = mail.reply_all_cc(original, await mail.own_addresses(feishu, user))
    prompt = (
        f"关于我（{user.name}，{user.email or ''}）：\n{await _profile(session, user)}\n\n"
        + (f"<thread>\n这封之前同一线程里的往来（我之前说过的话不能自相矛盾，已经回答过的不要再问）：\n" + "\n".join(earlier) + "\n</thread>\n\n" if earlier else "")
        + f"<mail>\n发件人：{original.get('from')}\n收件人：{'、'.join(original.get('to') or [])}\n抄送：{'、'.join(original.get('cc') or [])}\n"
        f"主题：{original.get('subject')}\n\n{original.get('body')}\n</mail>\n\n"
        + (f"<background>\n这件事的相关材料（只在确实相关时使用）：\n" + "\n\n".join(background) + "\n</background>\n\n" if background else "")
        + f"除发件人外，原邮件还有 {len(others)} 人。\n我的要求：{instructions or '按常理回复'}"
    )
    result = await complete_structured(DRAFT_SYSTEM, prompt, DRAFT_TOOL)
    return result.get("body") or "", references, bool(result.get("reply_all")) and bool(others), result.get("why") or ""


async def _with_addresses(session: AsyncSession, feishu: FeishuClient, user: User, signal: Signal) -> dict:
    """早先同步的邮件没有记下原收件人地址：回复全部前补拉一次。"""
    if "to_addresses" not in signal.payload:
        try:
            fresh = await mail.get_message(feishu, user, signal.external_id)
            signal.payload = {**signal.payload, **fresh}
        except FeishuError:
            pass
    return signal.payload


async def prepare_mail_reply(
    session: AsyncSession, feishu: FeishuClient, user: User, signal_id: int, instructions: str = "",
    reply_all: bool | None = None,
) -> PendingAction:
    """起草回复，先只存在 Relay 里。用户确认发送时才在他的飞书邮箱建草稿并发出。

    reply_all 为 None 时由起草时按内容判断（原邮件发给多人、说的是大家的事 → 回复全部；只问他个人的 → 只回发件人），
    理由写在草稿上，他可以改。他明确说了就按他说的。"""
    signal = await own_signal(session, user, signal_id, "mail")
    original = await _with_addresses(session, feishu, user, signal)
    to_extra, cc = mail.reply_all_split(original, await mail.own_addresses(feishu, user))
    body, references, suggested, why = await write_reply(session, feishu, user, signal, instructions)
    chosen = suggested if reply_all is None else (reply_all and bool(to_extra or cc))
    subject = original.get("subject") or ""
    action = PendingAction(
        user_id=user.id, kind="send_mail", signal_id=signal.id,
        summary=f"回复 {original.get('from_name') or original.get('from_address')}：{subject}",
        payload={
            "to": original.get("reply_to") or original.get("from_address"),
            "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
            "body": body,
            "references": references,
            # 原邮件里除了发件人和自己之外的人：回复全部时原收件人仍是收件人、原抄送仍是抄送
            "others": to_extra + cc, "to_extra": to_extra, "cc": cc,
            "reply_all": chosen,
            "reply_all_why": why if reply_all is None else ("你要求回复全部" if reply_all else "你要求只回复发件人"),
        },
    )
    session.add(action)
    await session.flush()
    return action


async def prepare_mail_forward(
    session: AsyncSession, feishu: FeishuClient, user: User, signal_id: int, to: list[str], note: str = "",
    with_attachments: bool = True,
) -> PendingAction:
    """转发：先只存在 Relay 里，他确认后才发。收件人只用他给的地址。"""
    signal = await own_signal(session, user, signal_id, "mail")
    addresses = [a.strip() for a in to if a and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a.strip())]
    if not addresses:
        raise ActionError("请给出要转发给谁的邮箱地址")
    attachments = await mail.attachments_of(feishu, user, signal) if with_attachments else []
    subject = signal.payload.get("subject") or signal.title
    action = PendingAction(
        user_id=user.id, kind="forward_mail", signal_id=signal.id,
        summary=f"转发《{subject}》给 {'、'.join(addresses)}",
        payload={"to": "、".join(addresses), "to_list": addresses, "subject": subject if subject.lower().startswith(("fw:", "fwd:")) else f"Fw: {subject}",
                 "body": note, "attachments": [a["filename"] for a in attachments], "with_attachments": bool(attachments)},
    )
    session.add(action)
    await session.flush()
    return action


def update_draft(action: PendingAction, body: str | None = None, reply_all: bool | None = None) -> None:
    if action.kind != "send_mail" or action.status != "pending":
        raise ActionError("只有待发送的邮件草稿可以修改")
    payload = dict(action.payload)
    if body is not None:
        payload["body"] = body
    if reply_all is not None:
        payload["reply_all"] = reply_all and bool(payload.get("others"))
    action.payload = payload


async def prepare_rsvp(session: AsyncSession, user: User, signal_id: int, status: str) -> PendingAction:
    if status not in RSVP_LABEL:
        raise ActionError("status 只能是 accept / tentative / decline")
    signal = await own_signal(session, user, signal_id)
    if signal.source != "calendar":
        raise ActionError("这不是一条日程")
    action = PendingAction(
        user_id=user.id, kind="calendar_rsvp", signal_id=signal.id,
        summary=f"{RSVP_LABEL[status]}会议：{signal.title}",
        payload={
            "calendar_id": signal.payload["calendar_id"],
            "event_id": signal.payload["event_id"],
            "status": status,
        },
    )
    session.add(action)
    await session.flush()
    return action


async def prepare_approval(
    session: AsyncSession, user: User, signal_id: int, approve: bool, comment: str = ""
) -> PendingAction:
    signal = await own_signal(session, user, signal_id, "approval_pending")
    if signal.status == "done":
        raise ActionError("这张审批已经处理过了")
    detail = signal.payload.get("detail")
    if approval.needs_input(detail):
        hint = (detail or {}).get("input_hint")
        raise ActionError(
            "这张审批需要你在飞书里处理" + (f"（需要填写：{hint}）" if hint else "（没能确认是否需要补填内容）")
            + "，Relay 不会替你直接批，请点「去飞书审批」。"
        )
    action = PendingAction(
        user_id=user.id, kind="approval_decision", signal_id=signal.id,
        summary=f"{'批准' if approve else '驳回'}：{signal.title}",
        payload={"task": signal.payload, "approve": approve, "comment": comment},
    )
    session.add(action)
    await session.flush()
    return action


# 长期任务里可以由用户预先授权自动执行的操作类型（审批不在其中，始终逐张确认）
GRANTABLE = {
    "send_chat": "给同事发飞书消息",
    "create_task": "给同事建飞书任务",
    "create_event": "建会议并邀请参会人",
    "add_attendees": "给已有会议加参会人",
    "calendar_rsvp": "回复会议邀请",
    "send_mail": "发送邮件",
    "base_record": "往多维表格提交记录",
}


def _new(session: AsyncSession, user: User, kind: str, summary: str, payload: dict, mission_id: int | None) -> PendingAction:
    action = PendingAction(user_id=user.id, kind=kind, summary=summary, payload=payload, mission_id=mission_id)
    session.add(action)
    return action


async def prepare_chat_message(
    session: AsyncSession, user: User, to_name: str, receive_id: str, text: str,
    receive_id_type: str = "open_id", mission_id: int | None = None, as_user: bool = True,
) -> PendingAction:
    """as_user：以用户本人的名义发（对方看到的是他发的）；否则由机器人代发并注明。"""
    action = _new(session, user, "send_chat", f"{'以你的名义' if as_user else '由 Relay 代'}给 {to_name} 发飞书消息", {
        "to": to_name, "receive_id": receive_id, "receive_id_type": receive_id_type, "body": text, "as_user": as_user,
    }, mission_id)
    await session.flush()
    return action


async def prepare_task(
    session: AsyncSession, user: User, summary: str, assignees: list[dict], due: datetime | None,
    description: str = "", mission_id: int | None = None,
) -> PendingAction:
    names = "、".join(a["name"] for a in assignees) or "自己"
    action = _new(session, user, "create_task", f"给 {names} 建飞书任务：{summary}", {
        "to": names, "subject": summary, "body": description, "assignees": assignees,
        "due": due.isoformat() if due else None,
    }, mission_id)
    await session.flush()
    return action


async def prepare_meeting(
    session: AsyncSession, user: User, title: str, start: datetime, end: datetime, attendees: list[dict],
    description: str = "", mission_id: int | None = None,
) -> PendingAction:
    local = start.astimezone(ZoneInfo(user.timezone))
    names = "、".join(a["name"] for a in attendees)
    action = _new(session, user, "create_event", f"约会：{local:%m-%d %H:%M}《{title}》", {
        "to": names, "subject": title, "body": description, "attendees": attendees,
        "start": start.isoformat(), "end": end.isoformat(),
    }, mission_id)
    await session.flush()
    return action


async def prepare_event_change(
    session: AsyncSession, user: User, kind: str, title: str, calendar_id: str, event_id: str,
    summary: str, mission_id: int | None = None, **extra,
) -> PendingAction:
    """改期（update_event）、取消（delete_event）、加人（add_attendees）。"""
    action = _new(session, user, kind, summary, {
        "subject": title, "calendar_id": calendar_id, "event_id": event_id, **extra,
    }, mission_id)
    await session.flush()
    return action


async def _collab(session: AsyncSession, user: User, p: dict) -> str:
    """协作：用户本人确认后才发出请求 / 接受 / 提交……（见 app/collab.py）。准备时看到的版本已经过时就不执行。"""
    from app import collab

    try:
        if p.get("op") == "create":
            assignee = await session.get(User, collab.member_id(p["assignee_id"]))
            if assignee is None:
                raise collab.CollabError("成员不存在")
            d = await collab.create(session, user, assignee, title=p["title"], brief=p["brief"], deliverable=p["deliverable"],
                                    acceptance=p.get("acceptance"), due_at=p.get("due_at"), materials=p.get("materials"))
            return f"已把《{d.title}》发给 {assignee.name}（协作 #{d.id}），等对方接受"
        d = await collab.act(session, user, int(p["delegation_id"]), p["action"], p.get("version"), note=p.get("note"),
                             changes=p.get("changes"), materials=p.get("materials"))
        return f"协作《{d.title}》：已{collab.ACTION_TEXT.get(p['action'], p['action'])}，现在是「{collab.STATUS_TEXT[d.status]}」"
    except collab.CollabError as exc:
        raise ActionError(str(exc)) from exc


async def execute(session: AsyncSession, feishu: FeishuClient, user: User, action: PendingAction) -> str:
    if action.user_id != user.id:
        raise ActionError("不能执行他人的操作")
    if action.status != "pending":
        return f"这个操作已经{ {'done': '执行过', 'cancelled': '取消', 'failed': '失败'}.get(action.status, '处理过') }了"
    try:
        if action.kind == "cloud_write" and action.payload.get("operation") == "fill_sheet_cells":
            try:
                await sheets.write_cells(feishu, user, action.payload)
            except sheets.SheetError as exc:
                raise ActionError(str(exc)) from exc
            except FeishuError as exc:
                if needs_reauth(exc):
                    raise
                raise ActionError(sheets.explain(exc, writing=True)) from exc
            result = f"已{action.summary.replace('填写', '填好', 1)}"
        elif action.kind == "cloud_write":
            p = action.payload
            if p.get("before") is not None and await cloud.before_write(feishu, user, p["operation"], p["arguments"]) != p["before"]:
                raise ActionError("原内容已变化，本次未写入。请重新读取并准备修改，让用户确认最新预览。")
            data = await cloud.call(feishu, user, p["operation"], p["arguments"], allow_write=True,
                client_token=idempotency_key(user, action))
            action.payload = {**p, "response": data}
            result = cloud_result(action.summary, p["operation"], data)
        elif action.kind == "send_mail":
            signal = await session.get(Signal, action.signal_id) if action.signal_id else None
            if signal is None:
                raise ActionError("原邮件已不存在")
            p = action.payload
            if p.get("reply_all"):
                # 早先起草的草稿没有分开记收件人和抄送：发送前按原邮件重新分
                to_extra, cc = (p.get("to_extra"), p.get("cc")) if "to_extra" in p else mail.reply_all_split(
                    await _with_addresses(session, feishu, user, signal), await mail.own_addresses(feishu, user))
            else:
                to_extra, cc = None, None
            await mail.send_reply(feishu, user, signal.payload, p["body"], cc, to_extra)
            result = f"已发送：{action.summary}"
        elif action.kind == "forward_mail":
            signal = await session.get(Signal, action.signal_id) if action.signal_id else None
            if signal is None:
                raise ActionError("原邮件已不存在")
            p = action.payload
            files = await mail.attachment_bytes(feishu, user, signal.external_id,
                                                await mail.attachments_of(feishu, user, signal)) if p.get("with_attachments") else []
            await mail.send_raw(feishu, user, mail.build_forward(user, signal.payload, p["to_list"], p.get("body") or "", files))
            result = f"已{action.summary}" + (f"（带 {len(files)} 个附件）" if files else "")
        elif action.kind == "send_chat":
            p = action.payload
            if p.get("as_user", False):
                sent = await im.send_as_user(feishu, user, p["receive_id"], p["receive_id_type"], p["body"])
            else:
                sent = await feishu.tenant_api(
                    "POST", "/im/v1/messages", params={"receive_id_type": p["receive_id_type"]},
                    json={"receive_id": p["receive_id"], **rich_text(f"_{relay_signature(user)}_\n\n{p['body']}")},
                )
            # 记下消息落在哪个会话（私聊也有 chat_id），长期任务据此去等对方回复；message_id 用来撤回
            action.payload = {**p, "chat_id": (sent or {}).get("chat_id") or (p["receive_id"] if p["receive_id_type"] == "chat_id" else None),
                              "message_id": (sent or {}).get("message_id"), "sent_at": datetime.now(UTC).isoformat()}
            result = f"已{action.summary}"
        elif action.kind == "base_record":
            p = action.payload
            try:
                record = await bitable.add_record(feishu, user, p["app_token"], p["table_id"], p["fields"],
                                                  client_token=idempotency_key(user, action))
            except FeishuError as exc:
                if needs_reauth(exc):
                    raise
                raise ActionError(bitable.explain(exc, writing=True)) from exc
            action.payload = {**p, "record_id": record.get("record_id")}
            result = f"已在《{p.get('table_name') or '多维表格'}》提交：" + "；".join(f"{k}={v}" for k, v in (p.get("shown") or {}).items())
        elif action.kind == "create_task":
            p = action.payload
            due = datetime.fromisoformat(p["due"]) if p.get("due") else None
            created = await tasks.create(feishu, user, p["subject"], [a["open_id"] for a in p["assignees"]], due, p.get("body") or "")
            action.payload = {**p, "task": created}
            result = f"已{action.summary}"
        elif action.kind == "create_event":
            p = action.payload
            created = await scheduling.create_meeting(
                session, feishu, user, p["subject"], datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"]),
                [a["open_id"] for a in p["attendees"]], p.get("body") or "",
            )
            action.payload = {**p, "event": created}
            result = f"已发出会议邀请：{action.summary}"
        elif action.kind == "update_event":
            p = action.payload
            await calendar.update_event(feishu, user, p["calendar_id"], p["event_id"],
                                        datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"]))
            result = f"已{action.summary}"
        elif action.kind == "delete_event":
            p = action.payload
            await calendar.delete_event(feishu, user, p["calendar_id"], p["event_id"])
            result = f"已{action.summary}"
        elif action.kind == "add_attendees":
            p = action.payload
            await calendar.add_attendees(feishu, user, p["calendar_id"], p["event_id"], [a["open_id"] for a in p["attendees"]])
            result = f"已{action.summary}"
        elif action.kind == "approval_decision":
            p = action.payload
            await approval.decide(feishu, user, p["task"], p["approve"], p.get("comment") or "")
            result = f"已{action.summary}"
        elif action.kind == "calendar_rsvp":
            p = action.payload
            await calendar.reply_invitation(feishu, user, p["calendar_id"], p["event_id"], p["status"])
            result = f"已{action.summary}"
            # 同一日程的信号（会议本身和邀请）都更新回复状态，卡片上立即可见
            await session.execute(
                update(Signal)
                .where(Signal.user_id == user.id, Signal.source == "calendar",
                       Signal.payload["event_id"].astext == p["event_id"])
                .values(payload=Signal.payload.op("||")(cast({"rsvp": p["status"]}, JSONB)))
            )
        elif action.kind == "collab":
            result = await _collab(session, user, action.payload)
        else:
            raise ActionError(f"未知操作 {action.kind}")
    except httpx.TransportError:
        # 超时不代表飞书未执行。禁止自动重复提交，先核实目标资源。
        action.status, action.result = "failed", "网络中断，执行结果未知。请先在飞书核实目标资源，避免重复创建或追加。"
        action.decided_at = datetime.now(UTC)
        return action.result
    except FeishuError as exc:
        if needs_reauth(exc):
            # 缺授权不算失败：操作保留，补齐授权后可以再点一次
            scopes = re.findall(r"\[([^\]]+)\]", str(exc))
            missing = f"（需要的权限：{scopes[0]}）" if scopes else ""
            return (
                f"Relay 还没有这项操作的授权{missing}。如果飞书后台已开通，请打开 {get_settings().frontend_url} "
                "重新用飞书登录一次再试（会自动申请应用已开通的全部权限）；如果还没开通，需要先在飞书后台开通并发布。"
            )
        action.status, action.result = "failed", str(exc)
        action.decided_at = datetime.now(UTC)
        if action.kind == "approval_decision":
            return (
                f"这张审批没能直接{'批准' if action.payload['approve'] else '驳回'}（飞书返回：{exc}）。"
                "可能这个节点需要你在飞书里补充信息，比如选择下一步的处理人。请点卡片上的「在飞书查看」处理。"
            )
        return f"执行失败：{exc}"
    except ActionError as exc:
        action.status, action.result = "failed", str(exc)
        action.decided_at = datetime.now(UTC)
        return f"执行失败：{exc}"
    from app.proactive import verify

    outcome = await verify.record(feishu, user, action)
    from app import assurance
    assurance.record(session, user.id, "write_verification", {"action_id": action.id, **(outcome or {"ok": None, "detail": "没有独立回读接口"})}, action.mission_id)
    if outcome is not None and outcome["ok"] is False:
        result += f"（⚠️ 写入后核对不一致：{outcome['detail']}，请到飞书里看一下）"
    action.status, action.result, action.decided_at = "done", result, datetime.now(UTC)
    await insights.record(session, user, insights.action_decision(action), action=action)
    if action.signal_id:
        signal = await session.get(Signal, action.signal_id)
        if signal and signal.status != "scheduled":
            signal.status = "done"
    return result


def cancel(action: PendingAction) -> str:
    if action.status != "pending":
        return "这个操作已经处理过了"
    action.status, action.decided_at = "cancelled", datetime.now(UTC)
    return f"已取消：{action.summary}"


def confirm_card(action: PendingAction) -> tuple[dict, str]:
    if action.kind == "send_mail":
        body = action.payload["body"]
        text = f"**收件人** {action.payload.get('to')}\n\n{body}"
    elif action.kind == "cloud_write":
        text = action.payload["body"]
    elif action.kind == "base_record":
        text = "\n".join(f"**{k}**：{v}" for k, v in (action.payload.get("shown") or {}).items())
        if action.payload.get("previous"):
            text += f"\n\n{action.payload['previous']}"
    else:
        text = action.summary
    buttons = [
        cards.callback(i18n.ui("confirm_send" if action.kind == "send_mail" else "confirm"), "confirm", "primary", action_id=action.id),
        cards.callback(i18n.ui("cancel"), "cancel", action_id=action.id),
    ]
    return cards.card(i18n.ui("pending_confirm", x=action.summary), text, buttons, "wathet"), f"{action.summary}\n\n{text}"


def idempotency_key(user: User, action: PendingAction) -> str:
    """飞书写接口的 client_token：同一个操作重试时不变（不会重复写入），格式必须是标准 UUID v4。

    uuid5 是 v5 格式，飞书会拒绝（Invalid client token）；取它的字节、把版本位改成 4。
    """
    seed = uuid.uuid5(uuid.NAMESPACE_URL, f"relay:{user.id}:{action.id}")
    return str(uuid.UUID(bytes=seed.bytes, version=4))


def relay_signature(user: User) -> str:
    """机器人代发时的署名：对方未必懂中文，用英文。"""
    return f"Sent by Relay on behalf of {user.name}"


def cloud_result(summary: str, operation: str, data: dict) -> str:
    """云文档写入完成后的一句话；飞书返回的原始数据留在 payload 里。"""
    if operation == "create_doc":
        doc = (data or {}).get("document") or {}
        return f"已{summary}" + (f"（document_id：{doc['document_id']}，可以接着往里追加内容）" if doc.get("document_id") else "")
    return f"已完成：{summary}"


async def mute(session: AsyncSession, user: User, signal_id: int) -> str:
    """用户说“这类邮件不用提醒”：按发件人记成规则（只放进早上的简报），推送前由代码直接执行。"""
    from app.proactive import attention

    signal = await own_signal(session, user, signal_id)
    sender = (signal.payload or {}).get("from_address") or (signal.payload or {}).get("from")
    if not sender:
        raise ActionError("这封邮件没有发件人，没法归类")
    await attention.set_rule(session, user, {"group": "mail", "person": sender}, "brief", "web")
    signal.status = "ignored"
    return f"好的，之后 {sender} 的邮件只放进每日简报"
