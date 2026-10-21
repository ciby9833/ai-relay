"""事项档案：复盘 Jennifer 那件事——合同邮件挂着附件，模型却搜了二十多次拿摘要拼。

档案要把同一件事的材料找齐（线程往来、附件、链接、相关聊天、会议、之前的事），并且不把无关的东西拉进来。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.proactive import casefile

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


def test_terms_ignore_reply_prefixes_and_generic_words():
    terms = casefile._terms("Re: Contract Review & IT items — J&T Cargo", "回复 Jennifer Angelina：看一下合同修订意见")
    assert {"contract", "review", "items", "cargo"} <= terms
    assert "re" not in terms and "回复" not in terms


class Feishu:
    """记录 Relay 以他本人身份读了什么；reject=True 时模拟飞书按他的权限拒绝。"""

    def __init__(self):
        self.asked, self.downloads, self.read_chats, self.reject = [], [], [], False

    async def user_api(self, user, method, path, **kwargs):
        from app.feishu.client import FeishuError

        if self.reject:
            raise FeishuError("no permission")
        if path.endswith("/members/is_in_chat"):
            self.asked.append(path.split("/")[4])
            return {"is_in_chat": False}
        if path.endswith("/attachments/download_url"):
            self.downloads.append(kwargs["params"]["attachment_ids"])
            return {"download_urls": [{"download_url": "https://x/a"}]}
        if path == "/im/v1/messages":
            self.read_chats.append(kwargs["params"]["container_id"])
            return {"items": [{"message_id": "om1", "msg_type": "text", "body": {"content": '{"text":"Did you see my email?"}'},
                               "sender": {"id": "ou_jen", "sender_type": "user"}, "create_time": "1760000000000"}]}
        if path.startswith("/contact/v3/users/"):
            return {"user": {"name": "Jennifer Angelina"}}
        raise AssertionError(path)

    async def download(self, url):
        return b"REDLINE TEXT", "text/plain"


@db
async def test_jennifer_case(monkeypatch):
    from sqlalchemy import delete

    from app.agent import loop
    from app.db import SessionLocal, engine
    from app.memory import service as memory_service
    from app.models import ChatMessage, Conversation, FollowUp, Signal, User

    async def no_embedding(text):
        return None

    monkeypatch.setattr(memory_service, "embed", no_embedding)
    now = datetime.now(UTC)
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Quillan", timezone="Asia/Jakarta")
        other = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Someone", timezone="Asia/Jakarta")
        session.add_all([user, other])
        await session.flush()
        user_id, other_id = user.id, other.id

        def mail(kind, minutes_ago, body, **payload):
            return Signal(user_id=user.id, source="mail", kind=kind, external_id=uuid.uuid4().hex,
                          title="Re: Contract Review & IT items", body=body, status="tracked",
                          occurred_at=now - timedelta(minutes=minutes_ago),
                          payload={"thread_id": f"th-{tag}", **payload})

        first = mail("mail", 3000, "Please review the attached contract.", from_name="Jennifer Angelina", from_address="jen@client.com")
        mine = mail("mail_sent", 2000, "Thanks, I will check with IT.")
        latest = mail("mail", 60, "Any update? The tracker is here https://jt.feishu.cn/sheets/ShtAbc123?sheet=x",
                      from_name="Jennifer Angelina", from_address="jen@client.com",
                      attachments=[{"id": "a1", "filename": "Contract_v3.xlsx"}, {"id": "a2", "filename": "Redline.txt"}])
        unrelated = Signal(user_id=user.id, source="mail", kind="mail", external_id=uuid.uuid4().hex, title="Lunch menu",
                           body="menu", status="ignored", occurred_at=now, payload={"thread_id": "other", "from_name": "Jennifer Angelina"})
        session.add_all([first, mine, latest, unrelated])
        await session.flush()
        item = FollowUp(user_id=user.id, key=f"mail-thread:th-{tag}", kind="reply", owner="me",
                        title="回复 Jennifer Angelina：Re: Contract Review & IT items", signal_ids=[latest.id], facets={})
        older = FollowUp(user_id=user.id, key=f"old-{tag}", kind="reply", owner="me", status="done",
                         title="回复 Jennifer Angelina：NDA", resolution="你确认签了 NDA", closed_at=now - timedelta(days=10), facets={})
        session.add_all([item, older])
        session.add_all([
            # 群里她提到合同：相关（他在这个群里说过话）
            ChatMessage(message_id=f"m1-{tag}", chat_id=f"oc_proj_{tag}", chat_name="J&T 项目群", sender_open_id="ou_jen",
                        sender_name="Jennifer Angelina", text="The contract review deadline is Friday", created_at=now - timedelta(hours=5)),
            ChatMessage(message_id=f"m0-{tag}", chat_id=f"oc_proj_{tag}", chat_name="J&T 项目群", sender_open_id=user.feishu_open_id,
                        sender_name="Quillan", text="noted", created_at=now - timedelta(hours=6)),
            # 她在另一个群里也提到合同，但他不在那个群：不能给他看
            ChatMessage(message_id=f"m5-{tag}", chat_id=f"oc_secret_{tag}", chat_name="管理层群", sender_open_id="ou_jen",
                        sender_name="Jennifer Angelina", text="contract margin is too low", created_at=now - timedelta(hours=3)),
            # 群里她说午饭：无关
            ChatMessage(message_id=f"m2-{tag}", chat_id=f"oc_food_{tag}", chat_name="午饭群", sender_open_id="ou_jen",
                        sender_name="Jennifer Angelina", text="Who wants pizza?", created_at=now - timedelta(hours=2)),
            # 她和他的私聊：最近说的都算
            ChatMessage(message_id=f"m3-{tag}", chat_id=f"oc_p2p_{tag}", chat_name="和 Jennifer Angelina 的私聊",
                        sender_open_id="ou_jen", sender_name="Jennifer Angelina", text="Did you see my email?",
                        owner_user_id=user.id, created_at=now - timedelta(hours=1)),
            # 别人的私聊：不能出现在他的档案里
            ChatMessage(message_id=f"m4-{tag}", chat_id=f"oc_p2p2_{tag}", chat_name="和 Jennifer Angelina 的私聊",
                        sender_open_id="ou_jen", sender_name="Jennifer Angelina", text="Contract for you too",
                        owner_user_id=other.id, created_at=now - timedelta(hours=1)),
        ])
        session.add(Signal(user_id=user.id, source="calendar", kind="meeting", external_id=uuid.uuid4().hex,
                           title="J&T contract sync", status="scheduled", occurred_at=now + timedelta(days=1),
                           payload={"organizer": "Jennifer Angelina", "attendees": ["Quillan"]}))
        await session.commit()
        feishu = Feishu()
        try:
            refs = await casefile.build(session, user, item, feishu)
            text = casefile.render(refs, user.timezone)
            by_ref = {r.ref: r for r in refs}
            kinds = [r.kind for r in refs if not r.weak]
            assert kinds.count("mail") == 2 and kinds.count("sent") == 1  # 线程里双方的往来
            assert f"read_mail_attachment(mail_id={latest.id}, attachment=2)" in text and "Redline.txt" in text
            assert by_ref[f"attachment:{latest.id}:2"].why == "Jennifer Angelina 的邮件《Re: Contract Review & IT items》的附件"
            assert by_ref[f"mail:{latest.id}"].why == "这件事的来源邮件" and by_ref[f"mail:{first.id}"].why == "同一邮件线程"
            doc = by_ref["doc:https://jt.feishu.cn/sheets/ShtAbc123?sheet=x"]
            assert doc.why == "链接出现在 Jennifer Angelina 的邮件里" and doc.why_ui["key"] == "case.linkMail"
            group = by_ref[f"chat:oc_proj_{tag}"]
            assert not group.weak and group.why == "群消息里提到「contract」"
            # 只是同一个人：标成弱关联，不当作这件事的材料
            private = by_ref[f"chat:oc_p2p_{tag}"]
            assert private.weak and "没有提到这件事" in private.why
            assert by_ref[f"history:{older.id}"].weak and "（弱关联）" in text
            meeting = next(r for r in refs if r.kind == "meeting")
            assert not meeting.weak and "contract" in meeting.why
            # 无关的、他看不到的都不在
            assert "午饭群" not in text and "Lunch menu" not in text and "Contract for you too" not in text
            assert "管理层群" not in text and feishu.asked == [f"oc_secret_{tag}"]
            assert "不代表内容一定和这件事相关" in text

            # 打开原文：每次重新校验
            opened = await casefile.open_ref(session, feishu, user, item, f"attachment:{latest.id}:2")
            assert opened["content"] == "REDLINE TEXT" and feishu.downloads == ["a2"]
            opened = await casefile.open_ref(session, feishu, user, item, f"mail:{first.id}")
            assert "Please review the attached contract." in opened["content"]
            opened = await casefile.open_ref(session, feishu, user, item, f"chat:oc_p2p_{tag}")
            assert "Did you see my email?" in opened["content"] and feishu.read_chats == [f"oc_p2p_{tag}"]
            for forged in (f"chat:oc_p2p2_{tag}", f"chat:oc_secret_{tag}", f"mail:{unrelated.id}", "doc:https://evil.example/x"):
                with pytest.raises(casefile.RefError):
                    await casefile.open_ref(session, feishu, user, item, forged)  # 不在这件事的档案里：不给看
            stranger = await session.get(User, other_id)
            with pytest.raises(casefile.RefError):
                await casefile.open_ref(session, feishu, stranger, item, f"mail:{first.id}")  # 别人的事项
            feishu.reject = True
            with pytest.raises(casefile.RefError, match="按你本人的权限"):
                await casefile.open_ref(session, feishu, user, item, f"chat:oc_proj_{tag}")

            history = await casefile.thread_history(session, user, latest)
            assert history[0].startswith("Jennifer Angelina") and history[1].startswith("我")

            # 他问“Jennifer Angelina 需要我做什么？”：上下文里直接带上这件事的档案
            conversation = Conversation(user_id=user.id, channel="web", title="t")
            session.add(conversation)
            await session.flush()
            context = await loop.build_context(session, user, conversation, "Jennifer Angelina 需要我做什么？", feishu)
            assert f"#{item.id}《" in context and "read_mail_attachment" in context
            # 只说名字也能认出来（只有这一件事和她有关时）
            assert [i.id for i in await casefile.focus(session, user, "what does jennifer need?", [item])] == [item.id]
            # 引用卡片时带的 #编号
            assert [i.id for i in await casefile.focus(session, user, f"（里面的事项：#{item.id} 回复…）怎么回", [])] == [item.id]
            # 同时像好几件事：不猜
            twin = FollowUp(user_id=user.id, key=f"twin-{tag}", kind="request", owner="me", title="Jennifer Lee 让你：发报价",
                            facets={"people": ["Jennifer Lee"]})
            session.add(twin)
            await session.flush()
            assert await casefile.focus(session, user, "what does jennifer need?", [item, twin]) == []
            unrelated_context = await loop.build_context(session, user, conversation, "今天天气怎么样", feishu)
            assert "的档案" not in unrelated_context
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.message_id.like(f"%-{tag}")))
            await session.execute(delete(User).where(User.id.in_([user_id, other_id])))
            await session.commit()
            await engine.dispose()
