"""邮件：收件箱里的新邮件；回复确认后发送。

两种邮箱，同一套行为：成员接了自己的标准邮箱（IMAP/SMTP，见 app/sources/imap.py）就用它，否则用飞书邮箱
（回复以草稿形式放进飞书邮箱再发送）。下面每个函数先看他接的是哪种。
"""

import base64
import email
import email.policy
import html
import re
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import connections
from app.feishu.client import FeishuClient, FeishuError
from app.models import Signal, SourceState, User
from app.sources import imap
from app.sources.base import add_signal, existing_ids

MAILBOX = "/mail/v1/user_mailboxes/me"
BODY_LIMIT = 20_000


def _b64url_decode(value: str | None) -> str:
    if not value:
        return ""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _address(entry: dict | None) -> str:
    if not entry:
        return ""
    name, address = entry.get("name") or "", entry.get("mail_address") or ""
    return f"{name} <{address}>" if name else address


async def mailbox(user: User) -> dict | None:
    """他自己接入的标准邮箱（没接返回 None，用飞书邮箱）。"""
    return await connections.account(user, "imap")


async def get_message(feishu: FeishuClient, user: User, message_id: str) -> dict:
    if (box := await mailbox(user)) is not None:
        return await imap.get_message(box, message_id)
    data = await feishu.user_api(
        user, "GET", f"{MAILBOX}/messages/{message_id}", params={"format": "plain_text_full"}
    )
    message = data.get("message") or {}
    return {
        "message_id": message_id,
        "subject": message.get("subject") or "（无主题）",
        "from": _address(message.get("head_from")),
        "from_address": (message.get("head_from") or {}).get("mail_address"),
        "from_name": (message.get("head_from") or {}).get("name"),
        "to": [_address(a) for a in message.get("to") or []],
        "cc": [_address(a) for a in message.get("cc") or []],
        # 原始收件人/抄送的地址（回复全部时要用）
        "to_addresses": [{"name": a.get("name"), "mail_address": a.get("mail_address")} for a in message.get("to") or []],
        "cc_addresses": [{"name": a.get("name"), "mail_address": a.get("mail_address")} for a in message.get("cc") or []],
        "reply_to": (message.get("reply_to") or None),
        "body": _b64url_decode(message.get("body_plain_text"))[:BODY_LIMIT],
        "internal_date": message.get("internal_date"),
        "smtp_message_id": message.get("smtp_message_id"),
        "references": message.get("references"),
        "thread_id": message.get("thread_id"),
        # UNREAD 未读、REPLIED 他已回复过这封（在飞书邮箱里直接回的也算）
        "labels": message.get("label_ids") or [],
        "attachments": [
            {"id": a.get("id"), "filename": a.get("filename") or "（未命名）"}
            for a in message.get("attachments") or [] if a.get("id") and not a.get("is_inline")
        ],
    }


async def attachments_of(feishu: FeishuClient, user: User, signal: Signal) -> list[dict]:
    """邮件的附件列表；早先读进来的邮件没存附件信息，补查一次。"""
    if "attachments" not in (signal.payload or {}):
        fresh = await get_message(feishu, user, signal.external_id)
        signal.payload = {**signal.payload, "attachments": fresh["attachments"]}
    return signal.payload["attachments"]


async def attachment_text(feishu: FeishuClient, user: User, message_id: str, attachment: dict) -> str:
    """下载并解析一个附件（解析结果缓存在内存里，翻页不重复下载）。"""
    from app.sources import files

    key = ("mail", user.id, message_id, attachment["id"])
    if (text := files.cache.get(key)) is not None:
        return text
    if files.kind_of(attachment["filename"]) is None:
        raise files.FileError(f"暂不支持读取这种附件：{attachment['filename']}（支持 xlsx、docx、pdf、csv、txt）")
    if (box := await mailbox(user)) is not None:
        _, content, content_type = await imap.attachment(box, message_id, attachment["id"])
        text = files.to_text(content, attachment["filename"], content_type)
        files.cache.put(key, text)
        return text
    data = await feishu.user_api(
        user, "GET", f"{MAILBOX}/messages/{message_id}/attachments/download_url", params={"attachment_ids": attachment["id"]}
    )
    urls = data.get("download_urls") or []
    if not urls:
        raise FeishuError("飞书没有返回这个附件的下载地址")
    content, content_type = await feishu.download(urls[0]["download_url"])
    text = files.to_text(content, attachment["filename"], content_type)
    files.cache.put(key, text)
    return text


def _clean(text: str | None) -> str:
    """搜索结果里的高亮标签和 HTML 转义还原成普通文字。"""
    return html.unescape(re.sub(r"</?h>", "", text or "")).strip()


FOLDERS = {"INBOX": "收件箱", "SENT": "已发送", "DRAFT": "草稿", "TRASH": "已删除", "SPAM": "垃圾邮件", "ARCHIVED": "已归档"}


async def search(feishu: FeishuClient, user: User, query: str, folder: str | None = None, limit: int = 10) -> list[dict]:
    """实时搜索用户的整个邮箱（所有文件夹，或指定文件夹）。"""
    if (box := await mailbox(user)) is not None:
        return [_summary(m) for m in await imap.search(box, query, folder, limit)]
    async def run(q: str) -> list[dict]:
        body: dict = {"query": q}
        if folder:
            body["filter"] = {"folder": [folder]}
        data = await feishu.user_api(user, "POST", f"{MAILBOX}/search", params={"page_size": limit}, json=body)
        return data.get("items") or []

    items = await run(query)
    if not items and re.search(r"[&<>\"']", query):
        # 搜索索引里存的是转义后的标题（& → &amp;），带这类字符的原文搜不到；去掉这些符号再搜一次
        items = await run(re.sub(r"\s+", " ", re.sub(r"[&<>\"']", " ", query)).strip())
    results = []
    for item in items:
        meta = item.get("meta_data") or {}
        sender = meta.get("from") or {}
        created = meta.get("create_time")
        results.append({
            "message_id": item.get("id"),
            "subject": _clean(meta.get("title")) or "（无主题）",
            "from": _clean(sender.get("name")) or sender.get("mail_address") or "",
            "time": datetime.fromtimestamp(int(created) / 1000, UTC) if created and str(created).isdigit() else None,
            "thread_id": meta.get("thread_id"),
            "snippet": _clean(item.get("display_info"))[:200],
        })
    return results


async def list_folder(feishu: FeishuClient, user: User, folder: str, limit: int = 10) -> list[dict]:
    """某个文件夹里最近的邮件（只取主题、发件人、时间等，不取正文）。"""
    if (box := await mailbox(user)) is not None:
        if folder not in ("INBOX", "SENT"):
            raise imap.MailboxError("接入的邮箱目前只能看收件箱和已发送")
        return [_summary(m) for m in await imap.recent(box, folder, limit, full=False)]
    data = await feishu.user_api(user, "GET", f"{MAILBOX}/messages", params={"folder_id": folder, "page_size": limit})
    results = []
    for message_id in data.get("items") or []:
        meta = (await feishu.user_api(
            user, "GET", f"{MAILBOX}/messages/{message_id}", params={"format": "metadata"}
        )).get("message") or {}
        received = meta.get("internal_date")
        results.append({
            "message_id": message_id, "subject": meta.get("subject") or "（无主题）",
            "from": _address(meta.get("head_from")), "to": [_address(a) for a in meta.get("to") or []],
            "time": datetime.fromtimestamp(int(received) / 1000, UTC) if received else None,
            "thread_id": meta.get("thread_id"),
        })
    return results


def _summary(mail: dict) -> dict:
    received = mail.get("internal_date")
    return {"message_id": mail["message_id"], "subject": mail["subject"], "from": mail["from"], "to": mail["to"],
            "time": datetime.fromtimestamp(int(received) / 1000, UTC) if received else None, "thread_id": mail.get("thread_id"),
            "snippet": (mail.get("body") or "")[:200]}


QUOTE = re.compile(
    r"(\n\s*(On .{5,200}wrote:|在 .{5,100}写道[:：]|发件人[:：]|From:\s|-{3,}\s*Original Message|-{5,}|>)"
    # 有的邮件纯文本没有换行，引用头和正文挤在一行：From: "张三"<a@b.com> / 发件人： "张三"<a@b.com>
    r"|\s(From|发件人)[:：]\s*\"?[^<\n]{0,80}<[^>\s]+@[^>\s]+>)",
    re.S,
)


def strip_quote(text: str) -> str:
    """只留这封信新写的部分（去掉下面引用的历史邮件）。"""
    match = QUOTE.search("\n" + (text or ""))
    return (text[: max(0, match.start() - 1)] if match else text or "").strip()


async def _sync_sent(session: AsyncSession, feishu: FeishuClient, user: User) -> None:
    """记下用户最近发出的邮件：他在 Relay 之外自己回过的信，对应的事要据此判断——办完了，还是转成“等对方回复”。

    正文也要存（去掉引用的历史）：只知道“他回了”不够，要知道他回了什么，才能判断还需不需要等对方。
    """
    if (box := await mailbox(user)) is not None:
        fetched = {m["message_id"]: m for m in await imap.recent(box, "SENT", 20)}
        ids = list(fetched)
    else:
        data = await feishu.user_api(user, "GET", f"{MAILBOX}/messages", params={"folder_id": "SENT", "page_size": 20})
        ids, fetched = data.get("items") or [], {}
    known = await existing_ids(session, user, "mail_sent", ids)
    for message_id in ids:
        if message_id in known:
            continue
        mail = fetched.get(message_id) or await get_message(feishu, user, message_id)
        sent = mail.get("internal_date")
        await add_signal(
            session, user, "mail_sent", message_id, kind="mail_sent", title=mail["subject"],
            body=strip_quote(mail["body"])[:4000],
            payload={"thread_id": mail.get("thread_id"), "to": mail["to"], "to_addresses": mail["to_addresses"]},
            occurred_at=datetime.fromtimestamp(int(sent) / 1000, UTC) if sent else datetime.now(UTC),
            status="ignored",  # 只作为“他已回复、回了什么”的依据，不提醒
        )


async def ensure_signal(session: AsyncSession, feishu: FeishuClient, user: User, message_id: str) -> Signal:
    """把任意一封邮件（任何文件夹）读进来，返回对应的信号（已有就直接返回），以便查看全文和起草回复。"""
    existing = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.source == "mail", Signal.external_id == message_id)
    )).scalars().first()
    if existing:
        return existing
    mail = await get_message(feishu, user, message_id)
    received = datetime.fromtimestamp(int(mail["internal_date"]) / 1000, UTC) if mail["internal_date"] else datetime.now(UTC)
    signal = Signal(
        user_id=user.id, source="mail", kind="mail", external_id=message_id, title=mail["subject"],
        body=mail["body"], payload=mail, occurred_at=received, status="ignored",  # 用户主动查的，不进提醒流程
    )
    session.add(signal)
    await session.flush()
    return signal


async def sync(session: AsyncSession, feishu: FeishuClient, user: User, state: SourceState) -> int:
    # 不只看未读：他在飞书邮箱里先打开过的信（往往正是对方的回复）也要进来，否则“等对方回复”永远等不到
    if (box := await mailbox(user)) is not None:
        fetched = {m["message_id"]: m for m in await imap.recent(box, "INBOX", 20)}
        ids = list(fetched)
    else:
        data = await feishu.user_api(user, "GET", f"{MAILBOX}/messages", params={"folder_id": "INBOX", "page_size": 20})
        ids, fetched = data.get("items") or [], {}
    known = await existing_ids(session, user, "mail", ids)
    first_sync = not state.cursor.get("initialized")
    # 正在跟进的邮件线程：对方在这些线程里的新信，即使他已经在飞书里看过，也要拿来推进对应的事
    from app.models import FollowUp

    watched = {k.removeprefix("mail-thread:") for k in (await session.execute(
        select(FollowUp.key).where(FollowUp.user_id == user.id, FollowUp.status == "open", FollowUp.key.like("mail-thread:%"))
    )).scalars()}
    created = 0
    for message_id in ids:
        if message_id in known:
            continue
        mail = fetched.get(message_id) or await get_message(feishu, user, message_id)
        received = (
            datetime.fromtimestamp(int(mail["internal_date"]) / 1000, UTC)
            if mail["internal_date"] else datetime.now(UTC)
        )
        # 第一次同步时已有的邮件只进简报，不逐封打扰；他已经看过的信也不再打扰，除非是正在跟进的线程里的新回复
        already_read = bool(mail["labels"]) and "UNREAD" not in mail["labels"] and mail.get("thread_id") not in watched
        stale = first_sync or already_read or received < datetime.now(UTC) - timedelta(days=2)
        created += await add_signal(
            session, user, "mail", message_id,
            kind="mail", title=mail["subject"], body=mail["body"], payload=mail,
            occurred_at=received, status="digest" if stale else "new",
        )
    await _sync_sent(session, feishu, user)
    state.cursor = {**state.cursor, "initialized": True}
    return created


async def own_addresses(feishu: FeishuClient, user: User) -> set[str]:
    """用户自己的邮箱地址（回复全部时从抄送里去掉）。"""
    addresses = {user.email.lower()} if user.email else set()
    if (box := await mailbox(user)) is not None:
        return addresses | {box["email"].lower()}
    try:
        profile = await feishu.user_api(user, "GET", f"{MAILBOX}/profile")
        if profile.get("primary_email_address"):
            addresses.add(profile["primary_email_address"].lower())
    except FeishuError:
        pass
    return addresses


def reply_all_split(mail: dict, own: set[str]) -> tuple[list[dict], list[dict]]:
    """回复全部时其他人各在哪：原来的收件人还是收件人，原来的抄送还是抄送（和邮箱客户端一致）；去掉自己和原发件人，去重。"""
    sender = (mail.get("reply_to") or mail.get("from_address") or "").lower()
    seen = {sender, (mail.get("from_address") or "").lower(), *own}
    split: tuple[list[dict], list[dict]] = ([], [])
    for bucket, entries in ((0, mail.get("to_addresses") or []), (1, mail.get("cc_addresses") or [])):
        for entry in entries:
            address = (entry.get("mail_address") or "").lower()
            if address and address not in seen:
                seen.add(address)
                split[bucket].append({"name": entry.get("name") or "", "mail_address": entry["mail_address"]})
    return split


def reply_all_cc(mail: dict, own: set[str]) -> list[dict]:
    """回复全部时除发件人外的其他人（收件人 + 抄送），用于显示“会发给谁”。"""
    to, cc = reply_all_split(mail, own)
    return to + cc


def _addresses(entries: list[dict]) -> str:
    return ", ".join(formataddr((c.get("name") or "", c["mail_address"])) for c in entries)


def build_reply(user: User, mail: dict, body: str, cc: list[dict] | None = None, to_extra: list[dict] | None = None) -> str:
    """构造回复邮件的 EML（带 In-Reply-To / References，归入原线程），返回 base64url。
    回复全部时 to_extra 是原来的其他收件人、cc 是原来的抄送；只回发件人时两者都为空。"""
    # SMTP 策略：CRLF 换行、非 ASCII 头按 RFC 2047 编码
    return base64.urlsafe_b64encode(reply_message(user, mail, body, cc, to_extra).as_bytes(policy=SMTP)).decode()


def reply_message(user: User, mail: dict, body: str, cc: list[dict] | None = None, to_extra: list[dict] | None = None) -> EmailMessage:
    message = EmailMessage()
    subject = mail["subject"]
    message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if user.email:
        message["From"] = formataddr((user.name, user.email))
    message["To"] = ", ".join([mail.get("reply_to") or mail["from_address"]] + ([_addresses(to_extra)] if to_extra else []))
    if cc:
        message["Cc"] = _addresses(cc)
    if mail.get("smtp_message_id"):
        original = mail["smtp_message_id"]
        original = original if original.startswith("<") else f"<{original}>"
        message["In-Reply-To"] = original
        message["References"] = f"{mail.get('references') or ''} {original}".strip()
    message.set_content(body)
    return message


async def send_reply(feishu: FeishuClient, user: User, mail: dict, body: str, cc: list[dict] | None = None,
                     to_extra: list[dict] | None = None) -> None:
    """发出回复：接了标准邮箱就用 SMTP 发（发件人是他的邮箱），否则放进飞书邮箱草稿再发送。"""
    if (box := await mailbox(user)) is not None:
        message = reply_message(user, mail, body, cc, to_extra)
        del message["From"]
        message["From"] = formataddr((user.name, box["email"]))
        await imap.send(box, message)
        return
    draft_id = await create_reply_draft(feishu, user, mail, body, cc, to_extra)
    await send_draft(feishu, user, draft_id)


async def create_reply_draft(feishu: FeishuClient, user: User, mail: dict, body: str, cc: list[dict] | None = None,
                             to_extra: list[dict] | None = None) -> str:
    data = await feishu.user_api(user, "POST", f"{MAILBOX}/drafts", json={"raw": build_reply(user, mail, body, cc, to_extra)})
    return (data.get("draft") or {})["id"]


FORWARD_LIMIT = 20 * 1024 * 1024


def build_forward(user: User, mail: dict, to: list[str], note: str, attachments: list[tuple[str, bytes]] | None = None) -> str:
    """转发：附言 + 原邮件的头信息和正文（+ 原附件），返回 base64url。"""
    message = EmailMessage()
    subject = mail["subject"]
    message["Subject"] = subject if subject.lower().startswith(("fw:", "fwd:")) else f"Fw: {subject}"
    if user.email:
        message["From"] = formataddr((user.name, user.email))
    message["To"] = ", ".join(to)
    sent = datetime.fromtimestamp(int(mail["internal_date"]) / 1000, UTC).strftime("%Y-%m-%d %H:%M UTC") if mail.get("internal_date") else ""
    header = "\n".join([
        "---------- 转发的邮件 / Forwarded message ----------",
        f"发件人 From: {mail.get('from') or mail.get('from_address')}", f"时间 Date: {sent}",
        f"主题 Subject: {subject}", f"收件人 To: {', '.join(mail.get('to') or [])}",
    ] + ([f"抄送 Cc: {', '.join(mail['cc'])}"] if mail.get("cc") else []))
    message.set_content(f"{note.strip()}\n\n{header}\n\n{mail.get('body') or ''}".lstrip())
    for filename, data in attachments or []:
        message.add_attachment(data, maintype="application", subtype="octet-stream", filename=filename)
    return base64.urlsafe_b64encode(message.as_bytes(policy=SMTP)).decode()


async def attachment_bytes(feishu: FeishuClient, user: User, message_id: str, attachments: list[dict]) -> list[tuple[str, bytes]]:
    """下载原邮件的附件原件（转发时带上），总大小不超过 20MB。"""
    if not attachments:
        return []
    if (box := await mailbox(user)) is not None:
        result, total = [], 0
        for a in attachments:
            name, content, _ = await imap.attachment(box, message_id, a["id"])
            total += len(content)
            if total > FORWARD_LIMIT:
                raise imap.MailboxError("附件合计超过 20MB，没法随转发带上")
            result.append((name, content))
        return result
    data = await feishu.user_api(user, "GET", f"{MAILBOX}/messages/{message_id}/attachments/download_url",
                                 params={"attachment_ids": ",".join(a["id"] for a in attachments)})
    names = {a["id"]: a["filename"] for a in attachments}
    result, total = [], 0
    for entry in data.get("download_urls") or []:
        content, _ = await feishu.download(entry["download_url"])
        total += len(content)
        if total > FORWARD_LIMIT:
            raise FeishuError("附件合计超过 20MB，没法随转发带上")
        result.append((names.get(entry.get("attachment_id"), "attachment"), content))
    return result


async def send_raw(feishu: FeishuClient, user: User, raw: str) -> None:
    if (box := await mailbox(user)) is not None:
        message = email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=email.policy.default)
        del message["From"]
        message["From"] = formataddr((user.name, box["email"]))
        await imap.send(box, message)
        return
    data = await feishu.user_api(user, "POST", f"{MAILBOX}/drafts", json={"raw": raw})
    await send_draft(feishu, user, (data.get("draft") or {})["id"])


async def send_draft(feishu: FeishuClient, user: User, draft_id: str) -> None:
    await feishu.user_api(user, "POST", f"{MAILBOX}/drafts/{draft_id}/send", json={})
