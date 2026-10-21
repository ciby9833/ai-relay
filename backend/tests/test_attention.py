"""提醒节奏：按真实场景验证“什么事立刻说、什么事攒着说、他说过不用提醒的就不说”。

场景来自生产数据：管理者一天收到二十来件事，大部分是审批（请假、报销）和不急的邮件，
以前每件都实时推一次。现在应当只有今天要处理的、紧急的、上级的才打断他。
"""
import os
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import AttentionRule, FollowUp, Signal, User
from app.proactive import attention

JKT = ZoneInfo("Asia/Jakarta")


def _user():
    return User(id=uuid.uuid4(), feishu_open_id="ou_me", name="Pieter", timezone="Asia/Jakarta")


def _approval(kind_name="请假", initiator="Budi", initiator_id="ou_budi"):
    signal = Signal(kind="approval_pending", title=f"{kind_name}申请",
                    payload={"initiator_names": [initiator], "initiators": [initiator_id],
                             "detail": {"approval_name": kind_name}})
    item = FollowUp(kind="approval", owner="me", title=f"{initiator}：{kind_name}申请", importance="normal", facets={})
    return item, signal


def _mail(sender="客户A", address="a@client.com", importance="normal", due=None):
    signal = Signal(kind="mail", title="报价确认", payload={"from_name": sender, "from_address": address})
    item = FollowUp(kind="reply", owner="me", title=f"回复 {sender}", importance=importance, due_at=due, facets={})
    return item, signal


def _rule(rule_id, match, level):
    return AttentionRule(id=rule_id, match=match, level=level, label=attention.describe_match(match), status="active")


NOW = datetime(2026, 10, 21, 3, 0, tzinfo=UTC)  # 雅加达 10:00，周三


def _level(item, signal, rules=(), leaders=None):
    return attention.decide(item, signal, _user(), list(rules), leaders, NOW)


def test_routine_approvals_and_mail_wait_for_the_digest():
    for item, signal in [_approval(), _approval("报销", "Sari", "ou_sari"), _mail()]:
        d = _level(item, signal)
        assert d.level == "batch" and d.rule is None and not d.critical


CHAIN = [{"open_id": "ou_boss", "name": "Hendra", "depth": 1}, {"open_id": "ou_ceo", "name": "Wilson", "depth": 2}]


def test_what_interrupts_right_away():
    urgent, signal = _mail(importance="urgent")
    assert (_level(urgent, signal).level, _level(urgent, signal).critical) == ("now", True)
    today, signal = _mail(due=NOW + timedelta(hours=5))
    d = _level(today, signal)
    assert (d.level, d.note, d.critical) == ("now", "今天要处理", False)  # 一般的今天要办：受每小时次数限制
    next_week, signal = _mail(due=NOW + timedelta(days=6))
    assert _level(next_week, signal).level == "batch"
    # 很久以前就过期的不算“今天”，不用再打断他（到期提醒自有次数上限）
    stale, signal = _mail(due=NOW - timedelta(days=3))
    assert _level(stale, signal).level == "batch"
    # 直属上级发起的事：按 open_id 认人，不靠名字
    item, signal = _approval("采购", "Hendra Wijaya", "ou_boss")
    d = _level(item, signal, leaders=CHAIN)
    assert d.level == "now" and d.critical and "直属上级 Hendra" in d.note
    # 上级的上级（CEO）在群里连着提问题：都算高危强时效
    chat = FollowUp(kind="request", owner="me", title="Wilson 让你：今天说明 Medan 网点延误原因", importance="normal",
                    facets={"people": ["Wilson"], "open_ids": ["ou_ceo"]})
    d = _level(chat, None, leaders=CHAIN)
    assert d.critical and "Wilson" in d.note
    # 在等别人的事，即使今天到期也不打断他
    waiting = FollowUp(kind="waiting", owner="others", title="等 Budi 回复", importance="normal",
                       due_at=NOW + timedelta(hours=1), waiting_on="Budi", facets={})
    assert _level(waiting, None, leaders=CHAIN).level == "batch"


def test_explicit_rules_win_and_the_most_specific_one_applies():
    rules = [
        _rule(1, {"group": "approval", "approval": "请假"}, "brief"),
        _rule(2, {"person": "Budi"}, "now"),
        _rule(3, {"group": "approval", "approval": "请假", "person": "Budi"}, "mute"),
    ]
    item, signal = _approval("请假", "Sari", "ou_sari")
    assert _level(item, signal, rules).level == "brief"
    item, signal = _approval("请假", "Budi Santoso", "ou_budi")
    d = _level(item, signal, rules)
    assert (d.level, d.rule.id) == ("mute", 3) and d.note.startswith("你设的规则")
    item, signal = _mail(sender="Budi Santoso", address="budi@co.com")
    d = _level(item, signal, rules)
    assert d.level == "now" and d.critical  # 他说过“随时告诉我”的人：不受次数限制
    # 他说“请假审批只放简报”：即使是上级的请假单也按他说的办
    item, signal = _approval("请假", "Hendra", "ou_boss")
    assert _level(item, signal, rules[:1], CHAIN).level == "brief"


def test_urgent_breaks_through_quiet_rules():
    """他设了“仓库系统的邮件只放简报”，但这封是爆仓事故（分级为 urgent）：照样马上说，并说明原因。"""
    rules = [_rule(1, {"group": "mail", "person": "alert@wms.co"}, "brief"), _rule(2, {"group": "mail", "person": "ops@wms.co"}, "mute")]
    incident, signal = _mail(sender="WMS", address="alert@wms.co", importance="urgent")
    d = _level(incident, signal, rules)
    assert d.level == "now" and d.critical and "虽然你设了" in d.note
    routine, signal = _mail(sender="WMS", address="ops@wms.co")
    assert _level(routine, signal, rules).level == "mute"


def test_a_system_the_user_silenced_cannot_shout_its_way_through():
    """WMS 把每条通知都标成紧急：他专门设了“WMS 的通知只放简报”就按他说的办；没设规则时紧急照样马上说。"""
    flood = FollowUp(kind="biz", owner="me", title="WMS：库存同步完成", importance="urgent", facets={"system": "WMS"})
    assert _level(flood, None, [_rule(1, {"group": "biz", "system": "WMS"}, "brief")]).level == "brief"
    assert _level(flood, None).critical
    # 按发件人设的邮件规则不受影响：事故邮件照样突破
    mail, signal = _mail(sender="WMS", address="alert@wms.co", importance="urgent")
    assert _level(mail, signal, [_rule(2, {"group": "mail", "person": "alert@wms.co"}, "brief")]).critical


def test_repeat_within_cooldown():
    item = FollowUp(kind="biz", owner="me", title="Medan 网点停运", importance="normal", facets={},
                    pushed_at=datetime.now(UTC) - timedelta(minutes=10), pushed_importance="normal")
    assert attention.is_repeat(item)  # 10 分钟前刚说过，又有更新：原地更新卡片
    item.importance = "urgent"
    assert not attention.is_repeat(item)  # 升级成紧急：另发一条
    item.pushed_importance = "urgent"
    assert attention.is_repeat(item)
    item.pushed_at = datetime.now(UTC) - timedelta(hours=1)
    assert not attention.is_repeat(item)  # 隔了一段时间的新进展：照常处理


def test_rule_matching_is_not_too_loose():
    rules = [_rule(1, {"group": "chat", "chat": "印尼报价群"}, "mute")]
    elsewhere = FollowUp(kind="request", owner="me", title="x", importance="normal", facets={"chat": "仓库群", "people": ["Ali"]})
    assert _level(elsewhere, None, rules).level == "batch"
    there = FollowUp(kind="request", owner="me", title="x", importance="normal", facets={"chat": "印尼报价群", "people": ["Ali"]})
    assert _level(there, None, rules).level == "mute"
    # 很短的名字不会反向包含进规则里（“Al” 不该匹配 “Alice”的规则）
    short = FollowUp(kind="request", owner="me", title="x", importance="normal", facets={"people": ["Al"]})
    assert _level(short, None, [_rule(2, {"person": "Alice"}, "mute")]).level == "batch"


def test_quieter_picks_the_natural_category():
    item, signal = _approval("请假", "Budi")
    assert attention.quieter_match(item, signal) == {"group": "approval", "approval": "请假"}
    item, signal = _mail(sender="系统通知", address="noreply@erp.co")
    assert attention.quieter_match(item, signal) == {"group": "mail", "person": "noreply@erp.co"}
    mention = FollowUp(kind="mention", owner="me", title="x", importance="normal", facets={})
    msignal = Signal(kind="mention", title="x", payload={"chat_name": "仓库群", "sender_name": "Ali"})
    assert attention.quieter_match(mention, msignal) == {"group": "chat", "chat": "仓库群"}
    assert attention.describe_match({"group": "approval", "approval": "请假"}) == "请假审批"
    assert attention.describe_match({"group": "mail", "person": "a@x.com"}, "en") == "emails from “a@x.com”"


def test_digest_times():
    user = _user()
    settings = {"digest_times": ["11:30", "16:30"], "quiet_start": "21:00", "quiet_end": "08:00"}
    at = lambda h, m, day=21: datetime(2026, 10, day, h, m, tzinfo=JKT)  # noqa: E731
    assert not attention.digest_due(settings, user, None, at(10, 0))
    assert attention.digest_due(settings, user, None, at(11, 31))
    assert not attention.digest_due(settings, user, at(11, 31).isoformat(), at(12, 0))
    assert attention.digest_due(settings, user, at(11, 31).isoformat(), at(16, 45))
    assert not attention.digest_due(settings, user, None, at(11, 31, day=24))  # 周六不汇总，周一简报一起说


# ---------- 走一遍真实的一天（需要数据库） ----------

db = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


class Feishu:
    """他的上级是 Hendra（ou_boss），Hendra 的上级是 CEO Wilson（ou_ceo）。"""

    CHAIN = {"ou_boss": ("Hendra", "ou_ceo"), "ou_ceo": ("Wilson", None)}

    def __init__(self):
        self.cards = []
        self.patched = []

    async def send_card(self, open_id, card, fallback):
        self.cards.append(fallback)
        return f"om_{uuid.uuid4().hex}"

    async def user_api(self, user, method, path, **kwargs):
        open_id = path.rsplit("/", 1)[1]
        if open_id == user.feishu_open_id:
            return {"user": {"leader_user_id": "ou_boss"}}
        name, boss = self.CHAIN.get(open_id, (None, None))
        return {"user": {"name": name, "leader_user_id": boss}}

    async def tenant_api(self, method, path, **kwargs):
        self.patched.append(path)  # 原地更新卡片
        return {}


@db
async def test_a_busy_day(monkeypatch):
    """上午来了 6 张请假/报销单和两封普通邮件：不打断他；上级在群里让他办事：立刻说，攒着的顺便带上；
    之后又来的单子等到汇总时间；他点了“少提醒这类”之后，请假单只进简报。"""
    from sqlalchemy import delete, select

    from app.db import SessionLocal, engine
    from app.proactive import callbacks, items
    from app.proactive.settings import merged

    async def no_post(*args, **kwargs):
        return None

    async def narrate(system, prompt):
        return "有几件事。"

    monkeypatch.setattr(items, "post", no_post)
    monkeypatch.setattr(items, "complete_text", narrate)
    monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
    clock = {"digest": False}
    monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: clock["digest"])
    feishu = Feishu()
    settings = merged({})

    async with SessionLocal() as session:
        user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Pieter", timezone="Asia/Jakarta")
        session.add(user)
        await session.flush()

        async def approval(n, kind_name, initiator="Budi"):
            signal = Signal(user_id=user.id, source="approval", kind="approval_pending", external_id=f"t{n}-{uuid.uuid4().hex}",
                            title=f"{kind_name}申请", status="tracked",
                            payload={"initiator_names": [initiator], "initiators": [f"ou_{initiator}"],
                                     "detail": {"approval_name": kind_name}})
            session.add(signal)
            await session.flush()
            session.add(FollowUp(user_id=user.id, key=f"approval:{signal.external_id}", kind="approval", owner="me",
                                 title=f"{initiator}：{kind_name}申请", signal_ids=[signal.id], facets={}))

        async def run():
            await items.announce(session, feishu, user, settings, [])

        try:
            for n in range(4):
                await approval(n, "请假")
            for n in range(2):
                await approval(10 + n, "报销", "Sari")
            for n in range(2):
                session.add(FollowUp(user_id=user.id, key=f"mail-thread:{n}", kind="review", owner="me",
                                     title=f"看一下 客户{n} 的周报", facets={}))
            await session.commit()
            await run()
            assert feishu.cards == []  # 一件急事都没有：不打断他

            session.add(FollowUp(user_id=user.id, key="chat:boss", kind="request", owner="me",
                                 title="Hendra 让你：今天把印尼线报价发我", facets={"people": ["Hendra"], "open_ids": ["ou_boss"]}))
            await session.commit()
            await run()
            assert len(feishu.cards) == 1  # 上级的事立刻说，攒着的 8 件顺便带上，一共一条消息
            assert "Hendra 让你" in feishu.cards[0] and feishu.cards[0].count("请假申请") == 4

            await approval(20, "请假")
            await approval(21, "报销", "Sari")
            await session.commit()
            await run()
            assert len(feishu.cards) == 1  # 又来的两张单子：还没到汇总时间

            # 他在上一条卡片里对请假单点了“少提醒这类”
            leave = (await session.execute(select(FollowUp).where(
                FollowUp.user_id == user.id, FollowUp.title == "Budi：请假申请").limit(1))).scalars().first()
            result = await callbacks.handle_card_action(feishu, user.feishu_open_id, {"relay": "quieter", "item_id": leave.id})
            assert result["ok"] and "请假审批" in result["message"] and "简报" in result["message"]

            clock["digest"] = True
            await run()
            assert len(feishu.cards) == 2
            assert "报销申请" in feishu.cards[1] and "请假申请" not in feishu.cards[1]  # 请假单留给早上的简报
            rule = (await session.execute(select(AttentionRule).where(AttentionRule.user_id == user.id))).scalars().one()
            assert rule.level == "brief" and rule.hits >= 1

            pending = (await session.execute(select(FollowUp).where(
                FollowUp.user_id == user.id, FollowUp.announced_at.is_(None)))).scalars().all()
            assert [i.attention for i in pending] == ["brief"]
            await run()
            assert len(feishu.cards) == 2  # 汇总过了：同一个时间点不会再说一次
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()


async def _fresh_user(session):
    user = User(feishu_open_id=f"ou_{uuid.uuid4().hex}", name="Pieter", timezone="Asia/Jakarta")
    session.add(user)
    await session.commit()
    return user


def _quiet_setup(monkeypatch):
    from app.proactive import items

    async def no_post(*args, **kwargs):
        return None

    async def narrate(system, prompt):
        return "有几件事。"

    monkeypatch.setattr(items, "post", no_post)
    monkeypatch.setattr(items, "complete_text", narrate)
    monkeypatch.setattr(items, "in_quiet_hours", lambda settings, tz: False)
    monkeypatch.setattr(attention, "digest_due", lambda *args, **kwargs: False)


@db
async def test_incidents_and_the_ceo_are_not_held_back_by_the_hourly_limit(monkeypatch):
    """这一小时已经提醒过 3 次：一般的“今天要处理”等名额；网点事故（urgent）和 CEO 连续的问题照样马上说；
    同一个事故 10 分钟后又有更新：原地更新卡片，不再发一条；事故升级成紧急：另发一条。"""
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.proactive import items
    from app.proactive.settings import merged

    _quiet_setup(monkeypatch)
    feishu = Feishu()
    settings = merged({})
    async with SessionLocal() as session:
        user = await _fresh_user(session)

        async def run():
            await items.announce(session, feishu, user, settings, [])

        try:
            for _ in range(3):
                await attention.note_interrupt(session, user)
            session.add(FollowUp(user_id=user.id, key="mail-thread:q", kind="reply", owner="me", title="回复 客户A：今天的报价",
                                 due_at=datetime.now(UTC) + timedelta(hours=3), facets={}))
            await session.commit()
            await run()
            assert feishu.cards == []  # 名额用完：一般的今天要办先等着（不降到 16:30 的汇总）

            session.add(FollowUp(user_id=user.id, key="chat:ceo-1", kind="request", owner="me",
                                 title="Wilson 让你：说明 Medan 网点今天的延误", facets={"people": ["Wilson"], "open_ids": ["ou_ceo"]}))
            await session.commit()
            await run()
            assert len(feishu.cards) == 1 and "Wilson 让你" in feishu.cards[0]
            assert "今天的报价" in feishu.cards[0]  # 反正要打断他了：等名额的一起说

            session.add(FollowUp(user_id=user.id, key="chat:ceo-2", kind="request", owner="me",
                                 title="Wilson 让你：明天的补救方案", facets={"people": ["Wilson"], "open_ids": ["ou_ceo"]}))
            await session.commit()
            await run()
            assert len(feishu.cards) == 2  # CEO 接着问：照样马上说

            incident = FollowUp(user_id=user.id, key="biz:wms:medan", kind="biz", owner="me", title="WMS：Medan 网点分拣线停运",
                                importance="normal", facets={"system": "WMS"})
            session.add(incident)
            await session.commit()
            await run()
            assert len(feishu.cards) == 2  # 普通的业务通知，名额又用完了：等着
            incident.announced_at = None
            incident.importance = "urgent"  # 系统判定为事故
            await session.commit()
            await run()
            assert len(feishu.cards) == 3 and "分拣线停运" in feishu.cards[2]

            incident.announced_at = None  # 10 分钟内同一事件又来一条更新
            await session.commit()
            await run()
            assert len(feishu.cards) == 3 and any(p.startswith("/im/v1/messages/") for p in feishu.patched)
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()
            await engine.dispose()


@db
async def test_old_preferences_become_suggestions_not_rules(monkeypatch):
    """以前“这类不用提醒”记成了记忆：整理成候选规则，确认前不起作用；他点“启用”才生效，点“不用”就不再提。"""
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.memory import service as memory_service
    from app.proactive import callbacks, llm

    async def no_embedding(text):
        return None

    async def propose(system, prompt, tool):
        memory_id = int(prompt.split("[")[1].split("]")[0])
        return {"rules": [{"memory_id": memory_id, "group": "approval", "approval": "请假", "level": "brief"}]}

    monkeypatch.setattr(memory_service, "embed", no_embedding)
    monkeypatch.setattr(llm, "complete_structured", propose)
    async with SessionLocal() as session:
        user = await _fresh_user(session)
        user_id = user.id
        try:
            await memory_service.add_memory(session, user.id, "profile", "来自 noreply@erp.co 的「库存日报」这类邮件不需要即时提醒")
            await memory_service.add_memory(session, user.id, "profile", "请假审批不用实时提醒，早上一起看就行")
            await memory_service.add_memory(session, user.id, "profile", "负责印尼区的仓储运营")  # 不是提醒偏好
            await session.commit()
            assert await attention.propose_from_memories(session, user) == 2
            assert await attention.propose_from_memories(session, user) == 0  # 只整理一次
            await session.commit()
            assert await attention.rules_for(session, user) == []  # 候选不生效
            proposed = await attention.rules_for(session, user, status="proposed")
            assert {r.label for r in proposed} == {"noreply@erp.co 的邮件 → 只放进早上简报", "请假审批 → 只放进早上简报"}
            item, signal = _mail(sender="ERP", address="noreply@erp.co")
            assert attention.decide(item, signal, user, await attention.rules_for(session, user)).level == "batch"

            assert len(await attention.proposals_to_show(session, user)) == 2
            assert await attention.proposals_to_show(session, user) == []  # 简报里只主动提一次
            await session.commit()

            mail_rule = next(r for r in proposed if r.match.get("group") == "mail")
            leave_rule = next(r for r in proposed if r.match.get("group") == "approval")
            result = await callbacks.handle_card_action(feishu := Feishu(), user.feishu_open_id, {"relay": "rule_accept", "rule_id": mail_rule.id})
            assert result["ok"]
            await callbacks.handle_card_action(feishu, user.feishu_open_id, {"relay": "rule_reject", "rule_id": leave_rule.id})
            await session.commit()
            for rule in proposed:
                await session.refresh(rule)  # 按钮回调在另一个会话里改的
            active = await attention.rules_for(session, user)
            assert [r.id for r in active] == [mail_rule.id]
            assert attention.decide(item, signal, user, active).level == "brief"
            # 他拒绝过的，之后不会再被整理成候选
            assert (await attention.set_rule(session, user, leave_rule.match, "brief", "memory", status="proposed")).status == "rejected"
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()


@db
async def test_leader_lookup_falls_back_to_app_identity():
    """他在通讯录里看不到自己上级（no user authority）：改用应用身份查；都查不到时一天后再试，不影响提醒。"""
    from sqlalchemy import delete

    from app.db import SessionLocal, engine
    from app.feishu.client import FeishuError

    class Restricted(Feishu):
        def __init__(self, tenant_ok=True):
            super().__init__()
            self.tenant_ok = tenant_ok

        async def user_api(self, user, method, path, **kwargs):
            raise FeishuError("no user authority error")

        async def tenant_api(self, method, path, **kwargs):
            if not self.tenant_ok:
                raise FeishuError("no permission")
            return await Feishu.user_api(self, self.me, method, path, **kwargs)

    async with SessionLocal() as session:
        user = await _fresh_user(session)
        user_id = user.id
        try:
            down = Restricted(tenant_ok=False)
            down.me = user
            assert await attention.leaders(session, down, user) == []
            assert await attention.leaders(session, Restricted(), user) == []  # 一天内不重复查
            state = await attention._state(session, user)
            state.cursor = {**state.cursor, "leaders_next_check": None}
            ok = Restricted()
            ok.me = user
            chain = await attention.leaders(session, ok, user)
            assert [(b["name"], b["depth"]) for b in chain] == [("Hendra", 1), ("Wilson", 2)]
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
            await engine.dispose()
