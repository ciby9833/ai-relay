"""影子实验的链路本身要对：过滤规则、按时间重放（只看得到当时的信息）、同一件事归到一起、只读。"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.ledger import shadow

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")
NOW = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)


def ev(id, kind, text, minutes=0, **kw):
    return shadow.Event(id, kind, NOW + timedelta(minutes=minutes), kw.pop("actor", "某人"), text, kw.pop("stream", "chat:oc_1:群"), **kw)


def test_screen_keeps_what_concerns_him():
    events = [
        ev("a", "chat", "他PDA有是把这个上传吗？", from_me=True),
        ev("b", "chat", "（回复 Xavier：他PDA有）@Xavier 是的，用PDA", 8, mentions_me=True),
        ev("c", "chat", "今天中午吃什么", 9),
        ev("d", "chat", "能不能帮忙看一下这个报表？", 10),  # 他说过话的群里的请求
        ev("e", "chat", "好的", 11, stream="chat:oc_9:别的群"),
        ev("f", "mail_in", "《Weekly digest》", 12, stream="mail:t1", why="noreply@erp.co"),
        ev("g", "mail_in", "《报价确认》请今天确认", 13, stream="mail:t2", mentions_me=True, why="a@client.com"),
        ev("h", "chat", "kirim data besok ya", 14, stream="chat:oc_p:私聊", private=True),
    ]
    shadow.screen(events)
    assert [e.id for e in events if e.keep] == ["a", "b", "d", "g", "h"]


class Scripted:
    """按剧本回答：归入事项、对账。"""

    name = "fake"

    def __init__(self, answers):
        self.answers, self.prompts = answers, []

    async def stream(self, *, model, system, messages, tools):
        from app.llm.base import Completion

        self.prompts.append((model, messages[0]["content"][0]["text"]))
        answer = self.answers.pop(0)
        yield Completion(blocks=[{"type": "tool_use", "id": "x", "name": tools[0]["name"], "input": answer}], stop_reason="tool_use",
                         usage={"input_tokens": 100, "output_tokens": 10})


@db
async def test_replay_builds_one_matter_and_closes_it_from_context():
    from sqlalchemy import delete, func, select

    from app.db import SessionLocal, engine
    from app.models import ChatMessage, FollowUp, User

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        me = User(feishu_open_id=f"ou_{tag}", name="Xavier(吴川)", timezone="Asia/Jakarta")
        session.add(me)
        await session.flush()
        user_id = me.id
        start = datetime.now(UTC) - timedelta(hours=3)
        for n, (sender, text, minutes, mention) in enumerate([
            (me.feishu_open_id, "他PDA有是把这个上传吗？", 0, False),
            ("ou_c", "@Xavier(吴川) 是的，用PDA", 8, True),
            ("ou_c", "今天中午吃什么", 9, False),
            ("ou_h", "这盘点的逻辑估计得改下", 70, False),
        ]):
            session.add(ChatMessage(message_id=f"om_{tag}_{n}", chat_id=f"oc_{tag}", chat_name="终端项目", sender_open_id=sender,
                                    sender_name="Xavier(吴川)" if sender == me.feishu_open_id else sender, text=text,
                                    mentions=[{"open_id": me.feishu_open_id}] if mention else [],
                                    parent_message_id=f"om_{tag}_0" if n == 1 else None, created_at=start + timedelta(minutes=minutes)))
        await session.commit()
        provider = Scripted([
            {"assignments": [{"event": f"[chat:om_{tag}_0] 10-23 他：他PDA有是把这个上传吗？", "matter": "new", "new_key": "pda", "title": "PDA 是否上传盘点数据", "people": ["Callesya"]},
                             {"event": f"chat:om_{tag}_1", "matter": "new", "new_key": "pda"}]},
            {"summary": "对方答了：用 PDA 上传", "commitments": [{"owner": "other", "party": "Callesya", "what": "答复 PDA 是否上传",
                                                         "status": "done", "evidence": "她答“是的，用PDA”"}]},
        ])
        try:
            before = await session.scalar(select(func.count()).select_from(FollowUp))
            result = await shadow.replay(session, provider, me, start - timedelta(minutes=1), start + timedelta(hours=2))
            matters = list(result["matters"].values())
            assert len(matters) == 1 and matters[0].commitments[0].status == "done"
            assert len(matters[0].events) == 2  # 吃饭那条被规则挡掉，没进模型
            assert "（回复 Xavier(吴川)：他PDA有是把这个上传吗？）" in provider.prompts[0][1]  # 话题回复带上被回复的话
            assert provider.prompts[0][0] == shadow.ATTACH_MODEL and provider.prompts[1][0] == shadow.RECONCILE_MODEL
            assert result["meter"].calls == {"attach": 1, "reconcile": 1}
            assert await session.scalar(select(func.count()).select_from(FollowUp)) == before  # 只读
        finally:
            await session.rollback()
            await session.execute(delete(ChatMessage).where(ChatMessage.chat_id == f"oc_{tag}"))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
