"""事项档案：一件事相关的材料清单——只是引用（是什么、谁、什么时候、凭什么认为相关、用哪个工具读），不是内容。

以前处理一件事时，材料靠模型临时去搜：Jennifer 那封合同邮件，模型搜了二十多次、拿搜索摘要拼内容，
其实附件就挂在那封邮件上。现在需要的时候按确定的规则把同一件事的材料找齐，每份都写明关联依据：

强关联（规则本身就说明是同一件事）：同一个邮件线程的往来、邮件附件、正文/表单/聊天里出现的飞书链接、
审批单、这件事所在的会话、提到这件事关键词的群消息和会议、提到同样关键词的之前的事。
弱关联（只是同一个人，未必是这件事）：对方最近和他的私聊、对方组织或参加的会、之前和同一个人的事。
弱关联单独标出，不当作这件事的材料；关联上了也不代表内容就相关，引用前要读原文核实。

隐私：私聊只取他本人的（owner_user_id）；群聊只取他在群里的（库里有他在群里说过话/被@过，或飞书确认他是成员）。
打开原文时（open_ref）再按当前用户校验一遍：材料必须在这件事的档案里，附件、文档、聊天都以他本人的飞书身份读取。
"""

import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
from app.models import ChatMessage, FollowUp, Signal, User
from app.proactive import attention

logger = logging.getLogger("relay.casefile")

LOOKBACK = timedelta(days=21)
MAX_STRONG = 15
MAX_WEAK = 4
MAX_CHATS = 3
PRIVATE_RECENT = timedelta(days=3)
LINK = re.compile(r"https?://[\w.-]*(?:feishu\.cn|larksuite\.com|larkoffice\.com)/(?:docx|docs|wiki|sheets|base|file|board|mindnotes|minutes)/[\w-]+[^\s)>\]\"'<，。]*")
LINK_KIND = {"docx": "文档", "docs": "文档", "wiki": "知识库", "sheets": "表格", "base": "多维表格", "file": "文件",
             "board": "画板", "mindnotes": "思维导图", "minutes": "妙记"}
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9&.-]{2,}|[\u4e00-\u9fff]{2,}")
_STOP = {
    "re", "fw", "fwd", "the", "and", "for", "with", "from", "your", "you", "please", "regarding", "about", "this", "that",
    "回复", "转发", "审批", "申请", "邮件", "看一下", "需要你看", "让你", "等审批", "会议邀请", "还没回", "群聊", "消息",
}


# 关联依据：中文给模型看，key/values 给网页按用户的界面语言显示
WHY = {
    "case.sourceMail": "这件事的来源邮件",
    "case.thread": "同一邮件线程",
    "case.threadSent": "同一邮件线程里你发的",
    "case.attachment": "{who} 的邮件《{title}》的附件",
    "case.approval": "这件事的审批单",
    "case.ownChat": "这件事所在的会话",
    "case.privateTerm": "私聊里提到「{term}」",
    "case.groupTerm": "群消息里提到「{term}」",
    "case.privateRecent": "对方最近和你的私聊（没有提到这件事）",
    "case.linkMail": "链接出现在 {who} 的邮件里",
    "case.linkApproval": "链接出现在审批单里",
    "case.linkSummary": "链接出现在这件事的摘要里",
    "case.linkChat": "链接出现在 {who} 在「{chat}」说的话里",
    "case.linkOther": "链接出现在《{title}》里",
    "case.meetingTerm": "会议标题/议程提到「{term}」",
    "case.meetingPerson": "对方组织或参加的会（没有提到这件事）",
    "case.historyTerm": "之前和同一个人的事，也提到「{term}」",
    "case.historyPerson": "之前和同一个人的事（不一定相关）",
    "case.sourceDoc": "这件事的来源",
    "case.evidence": "这件事的进展来自这里（{channel}）",
}


def _why(key: str, **values) -> dict:
    values = {k: str(v) for k, v in values.items()}
    return {"why": WHY[key].format(**values), "why_ui": {"key": key, "values": values}}


@dataclass
class Ref:
    ref: str  # 稳定编号，打开原文时用：mail:<id> | sent:<id> | attachment:<id>:<序号> | doc:<url> | approval:<id> | chat:<chat_id> | meeting:<id> | history:<id>
    kind: str  # mail | sent | attachment | doc | approval | chat | meeting | history
    title: str
    why: str  # 关联依据
    who: str | None = None
    at: datetime | None = None
    how: str | None = None  # 模型怎么读原文：工具调用；为空表示清单里写的就是全部
    note: str | None = None  # 简短摘录或说明
    weak: bool = False  # 只是同一个人，未必是这件事
    why_ui: dict | None = None  # 关联依据的界面文案 key/values

    def json(self) -> dict:
        data = asdict(self)
        data["at"] = self.at.isoformat() if self.at else None
        data.pop("how")
        return data


def _terms(*texts: str | None) -> set[str]:
    """判断“说的是不是同一件事”用的词：主题里的英文词、中文词组（长的再切成四字片段）。"""
    found: set[str] = set()
    for text in texts:
        for token in _TOKEN.findall(re.sub(r"^((re|fw|fwd|回复|转发)\s*[:：]\s*)+", "", text or "", flags=re.I)):
            low = token.lower().strip(".-")
            if low in _STOP or low.isdigit():
                continue
            if re.match(r"[\u4e00-\u9fff]", low) and len(low) > 6:
                found |= {low[i:i + 4] for i in range(0, len(low) - 3, 2)}
            elif len(low) >= 3:
                found.add(low)
    return found


def _matched(text: str | None, terms: set[str]) -> str | None:
    low = (text or "").lower()
    return next((t for t in sorted(terms, key=len, reverse=True) if t in low), None)


def _links(text: str | None) -> list[str]:
    return list(dict.fromkeys(LINK.findall(text or "")))


async def _in_group(session: AsyncSession, feishu: FeishuClient | None, user: User, chat_id: str, cache: dict) -> bool:
    """他在不在这个群：库里有他在群里说过话/被@过就算；否则问飞书（以他本人身份）；都确认不了就当不在。"""
    if chat_id in cache:
        return cache[chat_id]
    rows = list((await session.execute(
        select(ChatMessage).where(ChatMessage.chat_id == chat_id, ChatMessage.owner_user_id.is_(None))
        .order_by(ChatMessage.created_at.desc()).limit(300)
    )).scalars())
    member = any(m.sender_open_id == user.feishu_open_id or any(x.get("open_id") == user.feishu_open_id for x in m.mentions or [])
                 for m in rows)
    if not member and feishu is not None:
        try:
            data = await feishu.user_api(user, "GET", f"/im/v1/chats/{chat_id}/members/is_in_chat")
            member = bool(data.get("is_in_chat"))
        except Exception:  # noqa: BLE001 - 确认不了就不给看
            member = False
    cache[chat_id] = member
    return member


async def build(
    session: AsyncSession, user: User, item: FollowUp, feishu: FeishuClient | None = None, now: datetime | None = None,
) -> list[Ref]:
    now = now or datetime.now(UTC)
    since = now - LOOKBACK
    signals = [s for s in [await session.get(Signal, sid) for sid in item.signal_ids or []] if s is not None and s.user_id == user.id]
    last = signals[-1] if signals else None
    f = attention.facets(item, last)
    people = [str(p) for p in f.get("people") or [] if len(str(p)) >= 3]
    names = [p for p in people if "@" not in p]
    open_ids = set(f.get("open_ids") or [])
    # 人名不算“这件事”的关键词：否则只要是同一个人就会被当成同一件事
    name_words = _terms(*names) | {w.lower() for n in names for w in re.split(r"[\s（）()·.,]+", n) if w}
    terms = _terms(item.title, *(s.title for s in signals)) - name_words
    refs: list[Ref] = []
    texts: list[tuple[dict, str | None]] = [(_why("case.linkSummary"), item.summary)]
    seen_refs: set[str] = set()

    # 0. 这件事本身的来源文档（例如会议纪要），以及每次进展的出处（聊天、邮件、纪要）：都能打开看原文
    for url in _links(item.url):
        kind = LINK_KIND.get(url.split("/")[3] if url.count("/") >= 4 else "", "文档")
        named = re.search(r"《(.+)》", item.recommendation or "")
        refs.append(Ref(f"doc:{url}", "doc", (item.facets or {}).get("minutes_title") or (named.group(1) if named else f"飞书{kind}"),
                        how=f'read_feishu_doc(url="{url}")',
                        note=url, **_why("case.sourceDoc")))
        seen_refs.add(f"doc:{url}")
    for entry in reversed((item.facets or {}).get("evidence") or []):
        ref = entry.get("ref")
        if not ref or ref in seen_refs:
            continue
        seen_refs.add(ref)
        kind, _, rest = ref.partition(":")
        at = datetime.fromisoformat(entry["at"]) if entry.get("at") else None
        why = _why("case.evidence", channel=entry.get("channel") or "")
        if kind == "chat":
            refs.append(Ref(ref, "chat", entry.get("channel") or "聊天", at=at, note=entry.get("text"),
                            how=f'read_chat_messages(chat_id="{rest}", hours=168)', **why))
        elif kind == "mail" and rest.isdigit():
            signal = await session.get(Signal, int(rest))
            if signal is not None and signal.user_id == user.id:
                refs.append(Ref(ref, "mail", signal.title, who=(signal.payload or {}).get("from_name"), at=signal.occurred_at,
                                how=f"read_mail(mail_id={signal.id})", note=entry.get("text"), **why))
        elif kind == "doc":
            refs.append(Ref(ref, "doc", "会议纪要" if entry.get("channel") == "会议纪要" else "飞书文档", at=at, note=entry.get("text"),
                            how=f'read_feishu_doc(url="{rest}")', **why))

    # 1. 同一个邮件线程：双方的往来、附件
    threads = {(s.payload or {}).get("thread_id") for s in signals if s.kind in ("mail", "mail_sent")} - {None}
    thread_mails = list((await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind.in_(["mail", "mail_sent"]),
                             Signal.payload["thread_id"].astext.in_(threads))
        .order_by(Signal.occurred_at)
    )).scalars()) if threads else []
    for mail in thread_mails or [s for s in signals if s.kind == "mail"]:
        p = mail.payload or {}
        if mail.kind == "mail_sent":
            refs.append(Ref(f"sent:{mail.id}", "sent", mail.title, who="你", at=mail.occurred_at,
                            note=(mail.body or "")[:160], **_why("case.threadSent")))
        elif f"mail:{mail.id}" in seen_refs:
            pass
        else:
            sender = p.get("from_name") or p.get("from")
            refs.append(Ref(f"mail:{mail.id}", "mail", mail.title, who=sender, at=mail.occurred_at,
                            how=f"read_mail(mail_id={mail.id})", note=mail.summary,
                            **_why("case.sourceMail" if mail.id in item.signal_ids else "case.thread")))
            for index, attachment in enumerate(p.get("attachments") or [], 1):
                refs.append(Ref(f"attachment:{mail.id}:{index}", "attachment", attachment.get("filename") or "附件",
                                who=sender, at=mail.occurred_at, how=f"read_mail_attachment(mail_id={mail.id}, attachment={index})",
                                **_why("case.attachment", who=sender or "?", title=mail.title)))
        texts.append((_why("case.linkMail", who=p.get("from_name") or ("你" if mail.kind == "mail_sent" else "?")), mail.body))

    # 2. 审批单
    for signal in signals:
        if signal.kind == "approval_pending":
            refs.append(Ref(f"approval:{signal.id}", "approval", signal.title,
                            who="、".join((signal.payload or {}).get("initiator_names") or []) or None,
                            at=signal.occurred_at or signal.created_at, how=f"get_approval_detail(followup_id={item.id})",
                            **_why("case.approval")))
            fields = ((signal.payload or {}).get("detail") or {}).get("fields") or []
            texts.append((_why("case.linkApproval"), "\n".join(str(x.get("value")) for x in fields)))
        elif signal.kind in ("mention", "approval_update", "biz_event", "invitation"):
            texts.append((_why("case.linkOther", title=signal.title), signal.body))

    # 3. 聊天
    source_chat = (item.url or "").split("openChatId=")[-1] if "openChatId=" in (item.url or "") else None
    mention_chat = next(((s.payload or {}).get("chat_id") for s in signals if s.kind == "mention"), None)
    own_chats = {c for c in (source_chat, mention_chat) if c}
    who = [ChatMessage.sender_name.ilike(f"%{n}%") for n in names]
    if open_ids:
        who.append(ChatMessage.sender_open_id.in_(open_ids))
    if own_chats:
        who.append(ChatMessage.chat_id.in_(own_chats))
    messages = list((await session.execute(
        select(ChatMessage).where(or_(ChatMessage.owner_user_id.is_(None), ChatMessage.owner_user_id == user.id),
                                  ChatMessage.created_at > since, or_(*who))
        .order_by(ChatMessage.created_at.desc()).limit(200)
    )).scalars()) if who else []
    chats: dict[str, Ref] = {}
    membership: dict[str, bool] = {}
    for message in messages:
        private = message.owner_user_id == user.id
        term = _matched(message.text, terms)
        if message.chat_id in own_chats:
            why, weak = _why("case.ownChat"), False
        elif term:
            why, weak = _why("case.privateTerm" if private else "case.groupTerm", term=term), False
        elif private and message.created_at > now - PRIVATE_RECENT:
            why, weak = _why("case.privateRecent"), True
        else:
            continue
        if not private and not await _in_group(session, feishu, user, message.chat_id, membership):
            continue  # 他不在这个群：群里的话不给他看
        ref = chats.get(message.chat_id)
        if ref is None and f"chat:{message.chat_id}" in seen_refs:
            continue  # 已经作为进展出处列出来了
        if ref is None:
            if len(chats) >= MAX_CHATS:
                continue
            hours = max(1, min(168, int((now - message.created_at).total_seconds() // 3600) + 2))
            ref = chats[message.chat_id] = Ref(
                f"chat:{message.chat_id}", "chat", message.chat_name or ("私聊" if private else "群聊"),
                who=message.sender_name, at=message.created_at,
                how=f'read_chat_messages(chat_id="{message.chat_id}", hours={hours})',
                note=f"{message.sender_name or '某人'}：{message.text[:120]}", weak=weak, **why)
            refs.append(ref)
        elif ref.weak and not weak:
            ref.why, ref.why_ui, ref.weak = why["why"], why["why_ui"], False
        texts.append((_why("case.linkChat", who=message.sender_name or "?", chat=ref.title), message.text))

    # 4. 链接到的飞书文档
    seen = set(r[4:] for r in seen_refs if r.startswith("doc:"))
    for where, text in texts:
        for url in _links(text):
            if url in seen:
                continue
            seen.add(url)
            kind = LINK_KIND.get(url.split("/")[3] if url.count("/") >= 4 else "", "文档")
            refs.append(Ref(f"doc:{url}", "doc", f"飞书{kind}", how=f'read_feishu_doc(url="{url}")', note=url, **where))

    # 5. 会议：标题提到这件事算强关联；只是对方组织/参加的算弱关联
    meetings = list((await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind == "meeting",
                             Signal.occurred_at.between(now - timedelta(days=7), now + timedelta(days=14)))
        .order_by(Signal.occurred_at).limit(200)
    )).scalars())
    lowered = {n.lower() for n in names}
    from app.proactive.meetings import same_meeting

    listed: list[Signal] = []
    for meeting in meetings:
        if any(same_meeting(meeting, m) for m in listed):
            continue  # 同一个会的另一条日历记录
        listed.append(meeting)
        p = meeting.payload or {}
        attendees = {str(a).lower() for a in (p.get("attendees") or [])} | {str(p.get("organizer") or "").lower()}
        term = _matched(f"{meeting.title} {p.get('description') or ''}", terms)
        if term:
            why, weak = _why("case.meetingTerm", term=term), False
        elif lowered & attendees:
            why, weak = _why("case.meetingPerson"), True
        else:
            continue
        refs.append(Ref(f"meeting:{meeting.id}", "meeting", meeting.title, who=p.get("organizer"), at=meeting.occurred_at,
                        note=(p.get("description") or "")[:120] or None, weak=weak, **why))

    # 6. 之前的事：同一个人，提到同样关键词的算强关联
    if names:
        earlier = list((await session.execute(
            select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.id != item.id, FollowUp.status.in_(("done", "dismissed")),
                                   FollowUp.closed_at > now - timedelta(days=60),
                                   or_(*[FollowUp.title.ilike(f"%{n}%") for n in names]))
            .order_by(FollowUp.closed_at.desc()).limit(5)
        )).scalars())
        for old in earlier:
            term = _matched(f"{old.title} {old.summary or ''}", terms)
            refs.append(Ref(f"history:{old.id}", "history", old.title, at=old.closed_at, note=old.resolution, weak=not term,
                            **(_why("case.historyTerm", term=term) if term else _why("case.historyPerson"))))
    return _trim(refs)


def _trim(refs: list[Ref]) -> list[Ref]:
    """强关联最多 MAX_STRONG 份（先保证原件：附件、审批、文档，再是往来和聊天、会议），弱关联最多 MAX_WEAK 份。"""
    strong = [r for r in refs if not r.weak]
    if len(strong) > MAX_STRONG:
        core = [r for r in strong if r.kind in ("attachment", "approval", "doc")]
        exchanges = [r for r in strong if r.kind in ("mail", "sent")][-(MAX_STRONG // 2):]
        rest = [r for r in strong if r.kind in ("chat", "meeting", "history")]
        keep = {id(r) for r in (core + exchanges + rest)[:MAX_STRONG]}
        strong = [r for r in strong if id(r) in keep]
    return strong + [r for r in refs if r.weak][:MAX_WEAK]


LABEL = {"mail": "邮件", "sent": "你发的", "attachment": "附件", "doc": "文档", "approval": "审批单",
         "chat": "聊天", "meeting": "会议", "history": "之前的事"}


def render(refs: list[Ref], timezone: str) -> str:
    """给模型看的清单。关联是按规则找的，不代表内容一定相关。"""
    tz = ZoneInfo(timezone)
    lines = []
    for n, ref in enumerate(refs, 1):
        head = f"[{n}] {'（弱关联）' if ref.weak else ''}{LABEL.get(ref.kind, ref.kind)}"
        if ref.who:
            head += f" · {ref.who}"
        if ref.at:
            head += f" · {ref.at.astimezone(tz):%m-%d %H:%M}"
        head += f"《{ref.title}》（依据：{ref.why}）"
        if ref.note and ref.kind != "doc":
            head += f"：{ref.note}"
        if ref.how:
            head += f" → {ref.how}"
        lines.append(head)
    if not lines:
        return "（没有找到相关材料）"
    return "\n".join(lines) + "\n（关联是按规则找的，不代表内容一定和这件事相关；引用前先读原文核实，弱关联只是同一个人。）"


class RefError(Exception):
    """打不开这份材料：不在这件事的档案里、不属于他、或飞书拒绝了他本人的读取。"""


OPEN_LIMIT = 20000


async def open_ref(session: AsyncSession, feishu: FeishuClient, user: User, item: FollowUp, ref_id: str) -> dict:
    """打开档案里的一份材料的原文。每次都重新校验：事项是他的、这份材料在这件事当前的档案里、对象属于他，
    附件/文档/聊天以他本人的飞书身份读取（飞书再按他的权限校验一次）。"""
    from app.sources import cloud, im, mail as mail_source

    if item.user_id != user.id:
        raise RefError("找不到这件事")
    refs = {r.ref: r for r in await build(session, user, item, feishu)}
    ref = refs.get(ref_id)
    if ref is None:
        raise RefError("这份材料不在这件事的档案里（可能已经变了，刷新后再看）")
    kind, _, rest = ref_id.partition(":")
    content, url = "", None

    async def own_signal(signal_id: str) -> Signal:
        signal = await session.get(Signal, int(signal_id))
        if signal is None or signal.user_id != user.id:
            raise RefError("这份材料不属于你")
        return signal

    try:
        if kind in ("mail", "sent"):
            signal = await own_signal(rest)
            p = signal.payload or {}
            head = [f"发件人：{p.get('from') or '你'}"] if kind == "mail" else []
            head += [f"收件人：{'、'.join(p.get('to') or [])}"] if p.get("to") else []
            content = "\n".join(head + [f"主题：{signal.title}", "", signal.body or ""])
        elif kind == "attachment":
            signal_id, _, index = rest.partition(":")
            signal = await own_signal(signal_id)
            attachments = await mail_source.attachments_of(feishu, user, signal)
            if not 1 <= int(index) <= len(attachments):
                raise RefError("附件已经不在了")
            content = await mail_source.attachment_text(feishu, user, signal.external_id, attachments[int(index) - 1])
        elif kind == "doc":
            url = rest
            data = await cloud.read_url(feishu, user, url)
            content = data.get("content") if "content" in data else ""
            content = (f"《{data['title']}》\n" if data.get("title") else "") + (content or "（这类文件只有结构，请在飞书里打开）")
        elif kind == "approval":
            signal = await own_signal(rest)
            fields = ((signal.payload or {}).get("detail") or {}).get("fields") or []
            content = "\n".join(f"{x.get('name')}：{x.get('value')}" for x in fields) or (signal.body or "表单内容暂时读不到，需要在飞书里看原单")
            url = signal.url
        elif kind == "chat":
            rows = list((await session.execute(select(ChatMessage.owner_user_id).where(ChatMessage.chat_id == rest).distinct())).scalars())
            if any(owner is not None and owner != user.id for owner in rows) and user.id not in rows:
                raise RefError("这是别人的私聊")
            messages = await im.recent_messages(feishu, user, rest, hours=168, limit=50)  # 以他本人身份读：不在群里就读不到
            from app.sources.org import Org

            org, tz, lines = Org(feishu, user), ZoneInfo(user.timezone), []
            for m in reversed(messages):
                who = "机器人" if m["sender_type"] == "app" else (await org.name(m["sender"]) or "某人")
                lines.append(f"[{m['at'].astimezone(tz):%m-%d %H:%M}] {who}：{m['text'][:500]}")
            content = "\n".join(lines) or "这段时间没有消息"
            url = f"https://applink.feishu.cn/client/chat/open?openChatId={rest}"
        elif kind == "meeting":
            signal = await own_signal(rest)
            p = signal.payload or {}
            tz = ZoneInfo(user.timezone)
            content = "\n".join(x for x in [
                f"时间：{signal.occurred_at.astimezone(tz):%Y-%m-%d %H:%M}" if signal.occurred_at else "",
                f"组织者：{p.get('organizer') or '-'}", f"参会人：{'、'.join(p.get('attendees') or []) or '-'}",
                f"地点：{p.get('location') or '-'}", "", p.get("description") or "（没有议程）"] if x is not None)
            url = p.get("app_link") or p.get("meeting_url")
        elif kind == "history":
            old = await session.get(FollowUp, int(rest))
            if old is None or old.user_id != user.id:
                raise RefError("这份材料不属于你")
            content = "\n".join(x for x in [old.title, old.summary or "", f"结果：{old.resolution or old.status}"] if x)
        else:
            raise RefError("不认识的材料")
    except FeishuError as exc:
        raise RefError(f"飞书拒绝了读取（按你本人的权限）：{exc}") from exc
    except RefError:
        raise
    except Exception as exc:  # noqa: BLE001 - 解析附件等失败
        logger.warning("打开材料失败 %s：%s", ref_id, exc)
        raise RefError(f"读取失败：{exc}") from exc
    truncated = len(content) > OPEN_LIMIT
    return {"ref": ref.json(), "content": content[:OPEN_LIMIT], "truncated": truncated, "url": url}


async def thread_history(session: AsyncSession, user: User, signal: Signal, limit: int = 6) -> list[str]:
    """同一线程里这封之前的往来（双方各说了什么），起草回复时用：不能和他之前说过的话矛盾。"""
    thread = (signal.payload or {}).get("thread_id")
    if not thread:
        return []
    earlier = list((await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.kind.in_(["mail", "mail_sent"]), Signal.id != signal.id,
                             Signal.payload["thread_id"].astext == thread,
                             Signal.occurred_at < (signal.occurred_at or datetime.now(UTC)))
        .order_by(Signal.occurred_at.desc()).limit(limit)
    )).scalars())[::-1]
    return [
        f"{'我' if s.kind == 'mail_sent' else (s.payload or {}).get('from_name') or '对方'}（{s.occurred_at:%m-%d}）：{(s.body or '')[:600]}"
        for s in earlier
    ]


MAX_FOCUS = 2


async def focus(session: AsyncSession, user: User, text: str, open_items: list[FollowUp]) -> list[FollowUp]:
    """这句话说的是哪件事：写了 #编号（包括引用卡片时带上的），或者提到了某件事的对方（全名，或不会认错的名字）。

    认不准（同时像好几件事）就不猜，交给模型用 open_case。
    """
    ids = [int(n) for n in re.findall(r"#(\d{1,9})\b", text or "")]
    if ids:
        found = list((await session.execute(
            select(FollowUp).where(FollowUp.user_id == user.id, FollowUp.id.in_(ids[:MAX_FOCUS + 1]))
        )).scalars())
        return found if len(found) <= MAX_FOCUS else []
    low = (text or "").lower()
    if not low.strip():
        return []
    matched = []
    first_names: dict[str, list[FollowUp]] = {}
    for item in open_items:
        signal = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
        names = [str(p) for p in attention.facets(item, signal).get("people") or [] if "@" not in str(p) and len(str(p)) >= 3]
        if any(name.lower() in low for name in names):
            matched.append(item)
            continue
        for name in names:
            first = name.split()[0].lower()
            if len(first) >= 4 and first != name.lower():
                first_names.setdefault(first, []).append(item)
    if not matched:
        for first, candidates in first_names.items():
            if re.search(rf"\b{re.escape(first)}\b", low) and len(candidates) == 1:
                matched.append(candidates[0])
    return matched if len(matched) <= MAX_FOCUS else []
