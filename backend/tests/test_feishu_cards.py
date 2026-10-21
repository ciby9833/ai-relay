"""飞书卡片：业务内容要转义（官方文档：* _ ~ < > [ 等要转成 &#编号; 才能原样显示），卡片不能超过 30 KB。"""
import json

from app.feishu import cards as fc


def test_business_content_is_shown_as_is():
    text = fc.esc("PT_JNT_A <5天> *紧急* [点击确认](http://evil.example/x) J&T ~x~ #3 a|b")
    assert "_" not in text and "*" not in text and "<" not in text and "[" not in text and "~" not in text
    assert "J&T" in text  # 不会被当成实体的 & 不用动
    assert fc.esc("&amp;") == "&#38;amp;"  # 会被当成实体的要转


def test_relay_text_keeps_formatting_but_not_foreign_links():
    text = fc.safe_md("**3 件**<font color='red'>紧急</font>，<5 天 [文档](https://jt.feishu.cn/docx/a) "
                      "[确认](http://evil.example/x) [看板](https://relay.example/b) `a<b` ```\n<x>\n```", ("relay.example",))
    assert "**3 件**<font color='red'>紧急</font>" in text and "&#60;5 天" in text
    assert "[文档](https://jt.feishu.cn/docx/a)" in text and "[看板](https://relay.example/b)" in text
    assert "[确认]" not in text and "确认（http://evil.example/x）" in text
    assert "`a<b`" in text and "```\n<x>\n```" in text  # 代码原样
    assert fc._safe_host("https://evil.feishu.cn.example.com/x", ()) is False


def test_plain_fallback():
    assert fc.plain("✅ ~~a~~ <font color='grey'>J&#38;T &#95;x</font> [看](https://x)") == "✅ a J&T _x 看 https://x"


async def test_oversized_card_is_compacted(monkeypatch):
    """简报里十几件事、每件带完整草稿：超过 30 KB 时换成精简版，而不是被飞书拒收后退回纯文本（按钮全没了）。"""
    from types import SimpleNamespace

    from app.proactive import push

    long_body = "很长的草稿内容。" * 400
    items = {n: SimpleNamespace(id=n, kind="reply", owner="me", status="open", title=f"回复 客户_{n}", summary="摘要" * 50,
                                due_at=None, action_id=1000 + n, signal_ids=[], recommendation=None, url=None, attention="batch")
             for n in range(16)}
    actions = {1000 + n: SimpleNamespace(id=1000 + n, kind="send_mail", status="pending", summary="回复", payload={
        "body": long_body, "to": "a@b.c", "others": []}) for n in range(16)}

    class Session:
        async def get(self, model, key):
            return items.get(key) if model is push.FollowUp else actions.get(key)

    async def lang(session, user):
        return "zh"

    monkeypatch.setattr(push, "language_of", lambda session, user: lang(session, user))
    monkeypatch.setattr(push.attention, "quieter_match", lambda item, signal: None)
    user = SimpleNamespace(timezone="Asia/Jakarta")
    sections = [["要你回复", [{"kind": "item", "item_id": n} for n in range(16)]]]
    card, fallback = await push.render(Session(), user, "简报", "今天有 16 件", sections)
    assert fc.size(card) <= fc.CARD_LIMIT
    content = json.dumps(card, ensure_ascii=False)
    assert content.count('"relay": "confirm"') >= 1  # 按钮还在
    assert "客户&#95;0" in content
