"""邮件：回复全部时收件人/抄送各归各位；按内容判断回复全部还是只回发件人（理由给他看）；转发带原附件；
分拣知道他是收件人还是只被抄送；要处理的邮件带上下文（线程往来、附件、文档、相关会议）。"""
import base64
import email
import os
import uuid
from email import policy

import pytest

from app.models import User
from app.sources import mail

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")

ORIGINAL = {
    "subject": "Medan 延误复盘", "from": "Sari <sari@jt.id>", "from_address": "sari@jt.id", "from_name": "Sari",
    "to": ["Xavier <xavier@jt.id>", "Budi <budi@jt.id>"], "cc": ["Kange <kange@jt.id>"],
    "to_addresses": [{"name": "Xavier", "mail_address": "xavier@jt.id"}, {"name": "Budi", "mail_address": "budi@jt.id"}],
    "cc_addresses": [{"name": "Kange", "mail_address": "kange@jt.id"}, {"name": "Sari", "mail_address": "sari@jt.id"}],
    "body": "请大家周五前确认改善方案。", "internal_date": "1761700000000", "smtp_message_id": "abc@jt.id", "thread_id": "th1",
}


def _parse(raw: str):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)


def test_reply_all_keeps_to_and_cc_where_they_were():
    user = User(name="Xavier", email="xavier@jt.id")
    to_extra, cc = mail.reply_all_split(ORIGINAL, {"xavier@jt.id"})
    assert [a["mail_address"] for a in to_extra] == ["budi@jt.id"] and [a["mail_address"] for a in cc] == ["kange@jt.id"]
    message = _parse(mail.build_reply(user, ORIGINAL, "收到，周五前给方案。", cc, to_extra))
    assert message["To"] == "sari@jt.id, Budi <budi@jt.id>" and message["Cc"] == "Kange <kange@jt.id>"
    assert message["In-Reply-To"] == "<abc@jt.id>" and message["Subject"] == "Re: Medan 延误复盘"
    only = _parse(mail.build_reply(user, ORIGINAL, "好的"))
    assert only["To"] == "sari@jt.id" and only["Cc"] is None


def test_forward_carries_the_original_and_its_attachments():
    user = User(name="Xavier", email="xavier@jt.id")
    message = _parse(mail.build_forward(user, ORIGINAL, ["hendri@jt.id"], "Hendri，请看一下这个方案。", [("方案.xlsx", b"xlsx-bytes")]))
    assert message["Subject"] == "Fw: Medan 延误复盘" and message["To"] == "hendri@jt.id"
    text = message.get_body(("plain",)).get_content()
    assert text.startswith("Hendri，请看一下这个方案。") and "转发的邮件" in text and "请大家周五前确认改善方案。" in text
    files = [(part.get_filename(), part.get_content()) for part in message.iter_attachments()]
    assert files == [("方案.xlsx", b"xlsx-bytes")]


@db
async def test_drafts_choose_reply_all_with_a_reason_and_forward_needs_confirmation(monkeypatch):
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.proactive import actions
    from app.sources.base import add_signal

    prompts = []

    async def draft(system, prompt, tool):
        prompts.append(prompt)
        return {"body": "大家好，方案周五前发出。", "reply_all": True, "why": "原邮件发给了几个人，问的是大家的事"}

    async def own(feishu, user):
        return {"xavier@jt.id"}

    async def nothing(*args, **kwargs):
        return [], []

    monkeypatch.setattr(actions, "complete_structured", draft)
    monkeypatch.setattr(actions, "_background", nothing)
    monkeypatch.setattr(mail, "own_addresses", own)

    class Feishu:
        def __init__(self):
            self.raw = []

        async def user_api(self, user, method, path, **kwargs):
            if path.endswith("/attachments/download_url"):
                return {"download_urls": [{"attachment_id": "a1", "download_url": "https://x/a1"}]}
            if path.endswith("/drafts"):
                self.raw.append(kwargs["json"]["raw"])
                return {"draft": {"id": "d1"}}
            if path.endswith("/send"):
                return {}
            raise AssertionError(path)

        async def download(self, url, user=None):
            return b"xlsx-bytes", None

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Xavier", email="xavier@jt.id", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            await add_signal(session, user, "mail", f"m-{tag}", kind="mail", title=ORIGINAL["subject"],
                             body=ORIGINAL["body"], payload={**ORIGINAL, "attachments": [{"id": "a1", "filename": "方案.xlsx"}]}, status="tracked")
            await session.flush()
            from sqlalchemy import select

            from app.models import Signal
            signal = (await session.execute(select(Signal).where(Signal.user_id == user_id))).scalars().one()
            feishu = Feishu()
            reply = await actions.prepare_mail_reply(session, feishu, user, signal.id)
            assert reply.payload["reply_all"] is True and reply.payload["reply_all_why"] == "原邮件发给了几个人，问的是大家的事"
            assert "抄送：Kange" in prompts[0] and "除发件人外，原邮件还有 2 人" in prompts[0]
            forced = await actions.prepare_mail_reply(session, feishu, user, signal.id, reply_all=False)
            assert forced.payload["reply_all"] is False and forced.payload["reply_all_why"] == "你要求只回复发件人"
            await actions.execute(session, feishu, user, reply)
            sent = _parse(feishu.raw[-1])
            assert sent["To"] == "sari@jt.id, Budi <budi@jt.id>" and sent["Cc"] == "Kange <kange@jt.id>"

            with pytest.raises(actions.ActionError):
                await actions.prepare_mail_forward(session, feishu, user, signal.id, ["不是邮箱"])
            forward = await actions.prepare_mail_forward(session, feishu, user, signal.id, ["hendri@jt.id"], "请看一下")
            assert forward.status == "pending" and forward.payload["attachments"] == ["方案.xlsx"] and len(feishu.raw) == 1  # 没确认前不发
            result = await actions.execute(session, feishu, user, forward)
            assert "带 1 个附件" in result and _parse(feishu.raw[-1])["To"] == "hendri@jt.id"
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_mail_items_carry_their_context(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.models import Signal
    from app.proactive import items
    from app.sources.base import add_signal

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{tag}", name="Xavier", email="xavier@jt.id", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()
        user_id = user.id
        try:
            await add_signal(session, user, "mail", f"old-{tag}", kind="mail", title="Medan 运营周会 数据", payload={"thread_id": f"th-{tag}"}, status="tracked")
            await add_signal(session, user, "calendar", f"ev-{tag}", kind="meeting", title="Medan 运营周会", payload={},
                             occurred_at=datetime.now(UTC) + timedelta(days=1), status="scheduled")
            await add_signal(session, user, "mail", f"new-{tag}", kind="mail", title="Re: Medan 运营周会 数据",
                             payload={"thread_id": f"th-{tag}", "subject": "Re: Medan 运营周会 数据",
                                      "body": "见 https://x.feishu.cn/docx/AbC123", "attachments": [{"id": "a", "filename": "数据.xlsx"}]},
                             status="tracked")
            await session.flush()
            signal = (await session.execute(select(Signal).where(Signal.external_id == f"new-{tag}"))).scalars().one()
            context = await items.mail_context(session, user, signal)
            assert context == {"thread": 1, "attachments": ["数据.xlsx"], "links": 1, "meeting": "Medan 运营周会"}
            from app.proactive.push import context_line
            assert context_line(context) == "线程里之前 1 封往来 · 附件 数据.xlsx · 正文里 1 个飞书文档 · 相关会议《Medan 运营周会》"
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
