"""标准邮箱（IMAP 收、SMTP 发）：Gmail、Outlook、企业邮箱……

返回和飞书邮箱一样的邮件结构（app/sources/mail.py 的 get_message），所以后面的判断、待处理、代拟回复、
“他在 Relay 之外回过信”的判断都不用改。邮件编号：<文件夹>:<UIDVALIDITY>:<UID>。

IMAP 没有“会话”的概念：用 References / In-Reply-To 里最早的那封信的 Message-ID 当线程编号，
同一来回的信（包括他自己发出的回复）落在同一个线程里。
"""

import asyncio
import email
import hashlib
import html
import imaplib
import re
import smtplib
import ssl
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.policy import default as default_policy
from email.utils import getaddresses, parsedate_to_datetime

from app.feishu.client import FeishuError

TIMEOUT = 30
BODY_LIMIT = 20_000
SENT_NAMES = ("Sent", "Sent Items", "Sent Messages", "[Gmail]/Sent Mail", "[Google Mail]/Sent Mail", "INBOX.Sent", "已发送", "Sent Mail")


class MailboxError(FeishuError):
    """邮箱连不上、登录失败、找不到邮件。沿用外部服务错误的类型，原有的出错处理（记错误、跳过、提示）照常生效。"""


def _connect(account: dict) -> imaplib.IMAP4_SSL:
    try:
        box = imaplib.IMAP4_SSL(account["imap_host"], int(account.get("imap_port") or 993), timeout=TIMEOUT,
                                ssl_context=ssl.create_default_context())
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailboxError(f"连不上收信服务器 {account.get('imap_host')}：{exc}") from exc
    try:
        box.login(account.get("username") or account["email"], account["password"])
    except imaplib.IMAP4.error as exc:
        box.logout()
        raise MailboxError("邮箱登录失败：请检查账号和密码（Gmail、Outlook 等需要用“应用专用密码”）") from exc
    return box


def _decode(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except (ValueError, LookupError):
        return str(value)


def _addresses(value) -> list[dict]:
    return [{"name": _decode(name) or None, "mail_address": address} for name, address in getaddresses([_decode(value)]) if address]


def _display(entry: dict) -> str:
    return f"{entry['name']} <{entry['mail_address']}>" if entry.get("name") else entry["mail_address"]


def _html_to_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _body(message: Message) -> str:
    plain, rich = None, None
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):
            content = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and plain is None:
            plain = content
        elif part.get_content_type() == "text/html" and rich is None:
            rich = content
    text = plain if plain and plain.strip() else _html_to_text(rich or "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:BODY_LIMIT]


def _attachments(message: Message) -> list[tuple[str, Message]]:
    found = []
    for part in message.walk():
        filename = part.get_filename()
        if filename and part.get_content_disposition() != "inline":
            found.append((_decode(filename), part))
    return found


def thread_of(message: Message) -> str:
    """线程编号：References 里最早的一封，没有就是 In-Reply-To，再没有就是它自己。"""
    refs = re.findall(r"<[^>]+>", str(message.get("References") or ""))
    root = refs[0] if refs else (re.findall(r"<[^>]+>", str(message.get("In-Reply-To") or "")) or [str(message.get("Message-ID") or "")])[0]
    return "t" + hashlib.sha1(root.strip().lower().encode()).hexdigest()[:20] if root.strip() else ""


def _parse(message_id: str, raw: bytes, flags: str) -> dict:
    message = email.message_from_bytes(raw, policy=default_policy)
    sender = (_addresses(message.get("From")) or [{"name": None, "mail_address": ""}])[0]
    to, cc = _addresses(message.get("To")), _addresses(message.get("Cc"))
    try:
        sent = parsedate_to_datetime(str(message.get("Date"))) if message.get("Date") else None
    except (TypeError, ValueError):
        sent = None
    labels = [] if "\\Seen" in flags else ["UNREAD"]
    if "\\Answered" in flags:
        labels.append("REPLIED")
    reply_to = _addresses(message.get("Reply-To"))
    return {
        "message_id": message_id,
        "subject": _decode(message.get("Subject")) or "（无主题）",
        "from": _display(sender) if sender["mail_address"] else "",
        "from_address": sender["mail_address"], "from_name": sender["name"],
        "to": [_display(a) for a in to], "cc": [_display(a) for a in cc], "to_addresses": to, "cc_addresses": cc,
        "reply_to": reply_to[0]["mail_address"] if reply_to else None,
        "body": _body(message),
        "internal_date": str(int((sent or datetime.now(UTC)).timestamp() * 1000)),
        "smtp_message_id": str(message.get("Message-ID") or "").strip() or None,
        "references": str(message.get("References") or "").strip() or None,
        "thread_id": thread_of(message),
        "labels": labels or ["READ"],
        "attachments": [{"id": str(n), "filename": name} for n, (name, _) in enumerate(_attachments(message))],
    }


def _folder(box: imaplib.IMAP4_SSL, account: dict, kind: str) -> str:
    if kind == "INBOX":
        return "INBOX"
    if account.get("sent_folder"):
        return account["sent_folder"]
    status, rows = box.list()
    names = []
    for row in rows or []:
        line = row.decode(errors="replace") if isinstance(row, bytes) else str(row)
        name = line.rsplit(' "', 1)[-1].strip('"') if '"' in line else line.split()[-1]
        if "\\Sent" in line:
            return name  # 服务器标了“已发送”（RFC 6154）
        names.append(name)
    for candidate in SENT_NAMES:
        if candidate in names:
            return candidate
    raise MailboxError("找不到“已发送”文件夹，请在设置里填写它的名字")


def _quoted(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _select(box: imaplib.IMAP4_SSL, folder: str) -> str:
    status, _ = box.select(_quoted(folder), readonly=True)
    if status != "OK":
        raise MailboxError(f"打不开文件夹 {folder}")
    status, data = box.response("UIDVALIDITY")
    return (data[0].decode() if data and data[0] else "0")


def _fetch(box: imaplib.IMAP4_SSL, uids: list[bytes], what: str) -> list[tuple[bytes, bytes, str]]:
    if not uids:
        return []
    status, data = box.uid("FETCH", b",".join(uids), f"(UID FLAGS {what})")
    out = []
    for entry in data or []:
        if isinstance(entry, tuple):
            head = entry[0].decode(errors="replace")
            uid = re.search(r"UID (\d+)", head)
            flags = re.search(r"FLAGS \(([^)]*)\)", head)
            out.append((uid.group(1).encode() if uid else b"", entry[1], flags.group(1) if flags else ""))
    return out


# ---------- 同步线程里执行的操作（imaplib / smtplib 是同步的） ----------

def _recent(account: dict, kind: str, limit: int, full: bool) -> list[dict]:
    box = _connect(account)
    try:
        folder = _folder(box, account, kind)
        validity = _select(box, folder)
        status, data = box.uid("SEARCH", None, "ALL")
        uids = (data[0] or b"").split()[-limit:][::-1]
        what = "BODY.PEEK[]" if full else "BODY.PEEK[HEADER]"
        return [_parse(f"{kind}:{validity}:{uid.decode()}", raw, flags) for uid, raw, flags in _fetch(box, uids, what) if uid]
    finally:
        box.logout()


def _get(account: dict, message_id: str) -> tuple[dict, bytes]:
    kind, validity, uid = _split(message_id)
    box = _connect(account)
    try:
        if _select(box, _folder(box, account, kind)) != validity:
            raise MailboxError("邮箱文件夹已经重建，这封信的编号失效了")
        rows = _fetch(box, [uid.encode()], "BODY.PEEK[]")
        if not rows:
            raise MailboxError("这封邮件已经不在邮箱里了")
        _, raw, flags = rows[0]
        return _parse(message_id, raw, flags), raw
    finally:
        box.logout()


def _search(account: dict, query: str, kind: str, limit: int) -> list[dict]:
    box = _connect(account)
    try:
        folder = _folder(box, account, kind)
        validity = _select(box, folder)
        words = query.replace('"', " ").strip()
        try:
            box._encoding = "utf-8"  # 非 ASCII 的搜索词（中文）用 UTF-8 发送
            status, data = box.uid("SEARCH", "CHARSET", "UTF-8", "OR", "SUBJECT", _quoted(words), "FROM", _quoted(words))
        except imaplib.IMAP4.error:
            status, data = box.uid("SEARCH", None, "TEXT", _quoted(words.encode("ascii", "ignore").decode() or "x"))
        uids = (data[0] or b"").split()[-limit:][::-1] if status == "OK" else []
        return [_parse(f"{kind}:{validity}:{uid.decode()}", raw, flags) for uid, raw, flags in _fetch(box, uids, "BODY.PEEK[HEADER]") if uid]
    finally:
        box.logout()


def _send(account: dict, message: EmailMessage) -> None:
    host, port = account["smtp_host"], int(account.get("smtp_port") or 465)
    context = ssl.create_default_context()
    try:
        if account.get("smtp_security") == "starttls":
            server = smtplib.SMTP(host, port, timeout=TIMEOUT)
            server.starttls(context=context)
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context)
        with server:
            server.login(account.get("username") or account["email"], account["password"])
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailboxError("发信服务器登录失败：请检查账号和密码（很多邮箱要用“应用专用密码”）") from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise MailboxError(f"发信失败：{exc}") from exc
    # 放一份到“已发送”，他在自己的邮箱里也看得到（有的服务器会自动放，重复的那份由服务器去重或无害）
    try:
        box = _connect(account)
        try:
            if "gmail" not in host:  # Gmail 发出时自动放进已发送，再放会重复
                box.append(_quoted(_folder(box, account, "SENT")), "\\Seen", imaplib.Time2Internaldate(datetime.now(UTC)),
                           message.as_bytes())
        finally:
            box.logout()
    except (MailboxError, imaplib.IMAP4.error, OSError):
        pass


def _split(message_id: str) -> tuple[str, str, str]:
    parts = message_id.split(":")
    if len(parts) != 3 or parts[0] not in ("INBOX", "SENT"):
        raise MailboxError("不认识的邮件编号")
    return parts[0], parts[1], parts[2]


# ---------- 对外（异步） ----------

async def test(account: dict) -> None:
    """接入时测试：能登录收信服务器、能找到已发送文件夹、能登录发信服务器（不真的发信）。"""
    def run():
        box = _connect(account)
        try:
            _folder(box, account, "SENT")
        finally:
            box.logout()
        host, port = account["smtp_host"], int(account.get("smtp_port") or 465)
        try:
            if account.get("smtp_security") == "starttls":
                server = smtplib.SMTP(host, port, timeout=TIMEOUT)
                server.starttls(context=ssl.create_default_context())
            else:
                server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ssl.create_default_context())
            with server:
                server.login(account.get("username") or account["email"], account["password"])
        except smtplib.SMTPAuthenticationError as exc:
            raise MailboxError("发信服务器登录失败：请检查账号和密码") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise MailboxError(f"连不上发信服务器 {host}：{exc}") from exc

    await asyncio.to_thread(run)


async def recent(account: dict, kind: str = "INBOX", limit: int = 20, full: bool = True) -> list[dict]:
    return await asyncio.to_thread(_recent, account, kind, limit, full)


async def get_message(account: dict, message_id: str) -> dict:
    mail, _ = await asyncio.to_thread(_get, account, message_id)
    return mail


async def attachment(account: dict, message_id: str, attachment_id: str) -> tuple[str, bytes, str]:
    """(文件名, 内容, 类型)"""
    _, raw = await asyncio.to_thread(_get, account, message_id)
    found = _attachments(email.message_from_bytes(raw, policy=default_policy))
    index = int(attachment_id)
    if index >= len(found):
        raise MailboxError("找不到这个附件")
    name, part = found[index]
    return name, part.get_payload(decode=True) or b"", part.get_content_type()


async def search(account: dict, query: str, folder: str | None, limit: int) -> list[dict]:
    kinds = ["SENT"] if folder == "SENT" else ["INBOX"] if folder == "INBOX" else ["INBOX", "SENT"]
    results = []
    for kind in kinds:
        results += await asyncio.to_thread(_search, account, query, kind, limit)
    return results[:limit]


async def send(account: dict, message: EmailMessage) -> None:
    if not message.get("From"):
        message["From"] = account["email"]
    await asyncio.to_thread(_send, account, message)
