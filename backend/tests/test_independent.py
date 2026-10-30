"""助理不绑飞书：没有飞书的成员接自己的邮箱（IMAP/SMTP）和日历订阅（ICS），得到同一套行为。

用虚构的数据，不连接真实的邮箱或日历。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from app.sources import ics, imap


def _raw(subject, sender, to, message_id, body, date, in_reply_to=None, references=None, html=None, attachment=None) -> bytes:
    message = EmailMessage()
    message["Subject"], message["From"], message["To"], message["Message-ID"] = subject, sender, to, message_id
    message["Date"] = format_datetime(date)
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    if html:
        message.set_content(html, subtype="html")
    else:
        message.set_content(body)
    if attachment:
        message.add_attachment(attachment[1], maintype="text", subtype="csv", filename=attachment[0])
    return message.as_bytes()


def test_standard_mail_has_the_same_shape_and_threads_like_feishu_mail():
    when = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
    first = imap._parse("INBOX:7:101", _raw("运单明细", "Sari <sari@client.test>", "me@co.test, Budi <budi@co.test>",
                                          "<a1@client.test>", "请周五前确认 9 月运单", when,
                                          attachment=("明细.csv", "单号,重量\n1,2\n".encode())), "")
    reply = imap._parse("SENT:3:9", _raw("Re: 运单明细", "me@co.test", "sari@client.test", "<r1@co.test>", "收到，周五前给你",
                                       when + timedelta(hours=1), in_reply_to="<a1@client.test>", references="<a1@client.test>"), "\\Seen")
    later = imap._parse("INBOX:7:105", _raw("Re: 运单明细", "Sari <sari@client.test>", "me@co.test", "<a2@client.test>", "好的",
                                          when + timedelta(hours=2), references="<a1@client.test> <r1@co.test>"), "\\Seen \\Answered")
    # 同一来回的信（包括他自己发出的回复）是同一个线程
    assert first["thread_id"] == reply["thread_id"] == later["thread_id"] != ""
    assert first["labels"] == ["UNREAD"] and later["labels"] == ["REPLIED"]
    assert first["from_address"] == "sari@client.test" and first["from_name"] == "Sari"
    assert [a["mail_address"] for a in first["to_addresses"]] == ["me@co.test", "budi@co.test"]
    assert first["attachments"] == [{"id": "0", "filename": "明细.csv"}] and "周五前" in first["body"]
    assert first["smtp_message_id"] == "<a1@client.test>"
    html = imap._parse("INBOX:7:106", _raw("通知", "x@y.test", "me@co.test", "<h@y.test>", "", when,
                                         html="<p>第一行<br>第二行</p><style>p{}</style>"), "")
    assert html["body"] == "第一行\n第二行"
    with pytest.raises(imap.MailboxError):
        imap._split("../etc:1:2")


ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly-1
SUMMARY:Medan 运营周会
DTSTART;TZID=SE Asia Standard Time:20261102T100000
DTEND;TZID=SE Asia Standard Time:20261102T110000
RRULE:FREQ=WEEKLY;COUNT=6
EXDATE;TZID=SE Asia Standard Time:20261109T100000
ORGANIZER;CN=Sari:mailto:sari@co.test
ATTENDEE;CN=Budi;PARTSTAT=NEEDS-ACTION:mailto:budi@co.test
DESCRIPTION:议程\\n1. 延误复盘\\nhttps://meet.google.com/abc-defg-hij
END:VEVENT
BEGIN:VEVENT
UID:weekly-1
RECURRENCE-ID;TZID=SE Asia Standard Time:20261116T100000
SUMMARY:Medan 运营周会（改到下午）
DTSTART;TZID=SE Asia Standard Time:20261116T150000
DTEND;TZID=SE Asia Standard Time:20261116T160000
END:VEVENT
BEGIN:VEVENT
UID:off-1
SUMMARY:公司假期
DTSTART;VALUE=DATE:20261103
DTEND;VALUE=DATE:20261104
END:VEVENT
BEGIN:VEVENT
UID:gone-1
SUMMARY:已取消的会
DTSTART:20261104T020000Z
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


def test_calendar_subscription_expands_repeats_exceptions_and_moves():
    events = ics.expand(ics.parse(ICS, "Asia/Jakarta"), datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 20, tzinfo=UTC))
    titles = [(e["summary"], e["start"].astimezone(UTC).strftime("%m-%d %H:%M")) for e in events]
    # 11-02、11-16（改到 15:00）、全天的假期；11-09 被排除，取消的不出现。雅加达 10:00 = UTC 03:00
    assert titles == [("Medan 运营周会", "11-02 03:00"), ("公司假期", "11-02 17:00"), ("Medan 运营周会（改到下午）", "11-16 08:00")]
    assert events[0]["organizer"] == "Sari" and events[0]["attendees"] == ["Budi"] and events[1]["all_day"]
    assert "1. 延误复盘" in events[0]["description"]


async def test_member_without_feishu_gets_the_same_assistant(monkeypatch):
    if not os.getenv("RUN_DB_TESTS"):
        pytest.skip("需要 RUN_DB_TESTS=1 和数据库")
    import httpx
    from sqlalchemy import delete, select

    from app import connections, tenancy
    from app.db import SessionLocal, engine
    from app.feishu.client import WebOnly
    from app.main import app
    from app.models import Account, PendingAction, Signal, SourceState, Tenant, User, UserConnection
    from app.proactive import actions, engine as proactive
    from app.proactive.push import push
    from app.proactive.settings import merged

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        account = Account(email=f"sari-{tag}@co.test", name="Sari", password_hash=tenancy.hash_password("sari-pass-1"))
        session.add(account)
        await session.flush()
        sari = await tenancy.create_workspace(session, account, f"NoFeishu {tag}")  # 这个工作区没接飞书
        await session.commit()
        user_id, tenant_id = sari.id, sari.tenant_id

    now = datetime.now(UTC)
    inbox = [imap._parse(f"INBOX:7:{n}", _raw(f"报价确认 {n}", "Client <c@client.test>", f"sari-{tag}@co.test",
                                            f"<q{n}-{tag}@client.test>", "请确认报价", now - timedelta(minutes=n)), "") for n in (1, 2)]
    sent_box: list = []
    monkeypatch.setattr(imap, "_recent", lambda account, kind, limit, full: inbox if kind == "INBOX" else [])
    monkeypatch.setattr(imap, "_send", lambda account, message: sent_box.append(message))
    tomorrow = (now + timedelta(days=1)).strftime("%Y%m%dT020000Z")

    async def fake_fetch(url, http=None):
        assert url == "https://calendar.example/private-abc/basic.ics"
        return f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:m-{tag}\nSUMMARY:客户周会\nDTSTART:{tomorrow}\nEND:VEVENT\nEND:VCALENDAR\n"

    monkeypatch.setattr(ics, "fetch", fake_fetch)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as c:
            await c.post("/api/auth/login", json={"email": f"sari-{tag}@co.test", "password": "sari-pass-1"})
            # 常见邮箱自动带出服务器；密码不回显
            saved = (await c.put("/api/connections/imap", json={"email": f"sari-{tag}@gmail.com", "password": "app-pass-123"})).json()
            assert saved["config"]["imap_host"] == "imap.gmail.com" and saved["secrets"] == {"password": True}
            assert "app-pass-123" not in str(saved)
            await c.put("/api/connections/imap", json={"email": f"sari-{tag}@co.test", "imap_host": "imap.co.test", "imap_port": 993,
                                                       "smtp_host": "smtp.co.test", "smtp_port": 465})
            assert (await c.put("/api/connections/ics", json={"url": "http://calendar.example/x.ics"})).status_code == 400
            cal = (await c.put("/api/connections/ics", json={"url": "webcal://calendar.example/private-abc/basic.ics"})).json()
            assert cal["connected"] and "private-abc" not in str(cal)  # 订阅链接也是密钥
            tested = (await c.post("/api/connections/ics/test")).json()
            assert tested["status"] == "ok" and "1 个日程" in tested["note"]

        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            client = await tenancy.client_for(session, user, None)
            assert isinstance(client, WebOnly)  # 没有飞书：不会拿别的公司的飞书应用替他做事
            assert await proactive.available_sources(client, user) == {"mail": "imap", "calendar": "ics"}
            await proactive.sync_sources(session, client, user, merged({}), force=True)
            mails = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.source == "mail"))).scalars().all()
            meetings = (await session.execute(select(Signal).where(Signal.user_id == user_id, Signal.kind == "meeting"))).scalars().all()
            assert sorted(m.title for m in mails) == ["报价确认 1", "报价确认 2"] and [m.title for m in meetings] == ["客户周会"]
            # 飞书才有的来源（审批、考勤……）不同步、也不记成故障
            states = {s.source: s.last_error for s in (await session.execute(select(SourceState).where(SourceState.user_id == user_id))).scalars()}
            assert set(states) <= {"mail", "calendar"} and not any(states.values())
            # 提醒写在 Relay 里，飞书那一份不发也不报错
            assert await push(session, client, user, "测试", "内容") is None

            # 代拟的回复确认后从他自己的邮箱发出：发件人是他的邮箱，归入原线程
            signal = mails[0]
            action = PendingAction(user_id=user_id, kind="send_mail", summary="回复报价", signal_id=signal.id,
                                   payload={"body": "已确认", "reply_all": False})
            session.add(action)
            await session.flush()
            result = await actions.execute(session, client, user, action)
            await session.commit()
            assert action.status == "done", result
            message = sent_box[0]
            assert f"sari-{tag}@co.test" in message["From"] and message["To"] == "c@client.test"
            assert message["In-Reply-To"] == signal.payload["smtp_message_id"]

        # 同一套主流程：新来一封要他处理的信 → 判断 → 待处理 → 在 Relay 里提醒他（不发飞书）
        inbox.insert(0, imap._parse("INBOX:7:3", _raw("今天确认 Medan 报价", "Client <c@client.test>", f"sari-{tag}@co.test",
                                                     f"<q3-{tag}@client.test>", "请今天确认 Medan 线路报价", now), ""))

        async def judged(system, prompt, tool):
            return {"importance": "urgent", "notify_now": True, "needs_reply": True, "action_type": "reply", "due": "today",
                    "summary": "客户要求今天确认报价", "reason": "客户催办", "why_me": "直接发给她", "ask": "确认报价并回复客户", "when": "今天内"}

        async def drafted(system, prompt, tool):
            return {"body": "您好，报价今天内回复。", "reply_all": False, "why": "只问她"}

        async def text(*args, **kwargs):
            return "客户要你今天确认 Medan 报价。"

        async def no_embedding(value):
            return None

        from app.memory import service as memory_service
        from app.proactive import attention, items

        monkeypatch.setattr(memory_service, "embed", no_embedding)
        monkeypatch.setattr(proactive, "complete_structured", judged)
        monkeypatch.setattr(actions, "complete_structured", drafted)
        for module in (proactive, actions, items):
            monkeypatch.setattr(module, "complete_text", text)
        monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
        monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: True)
        async with SessionLocal() as session:
            from sqlalchemy import update

            await session.execute(update(SourceState).where(SourceState.user_id == user_id).values(last_synced_at=None))  # 到了下一次同步
            await session.commit()
            await proactive.run_for_user(session, WebOnly(), await session.get(User, user_id))
        async with SessionLocal() as session:
            from app.home import home_conversation
            from app.models import FollowUp, Message

            item = (await session.execute(select(FollowUp).where(FollowUp.user_id == user_id, FollowUp.title.like("%Medan%")))).scalars().first()
            assert item is not None and item.status == "open" and item.owner == "me" and item.announced_at is not None
            home = await home_conversation(session, await session.get(User, user_id))
            said = (await session.execute(select(Message).where(Message.conversation_id == home.id, Message.role == "assistant"))).scalars().all()
            assert said, "提醒要写在 Relay 首页的对话里"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(UserConnection).where(UserConnection.user_id == user_id))
            await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        connections.forget(user_id)
        await engine.dispose()
