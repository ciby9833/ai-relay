"""连接器清单是唯一权威：代码里的工具 / 数据源和清单一一对应；错误码统一；只有 confirm_action 能执行；文档由清单生成。"""
import json
import os
import pathlib
from types import SimpleNamespace

import pytest

import app.agent.tools  # noqa: F401  注册全部工具
from app.agent.tools.base import TOOLS, ToolContext, ToolError, execute
from app.connectors import catalog, errors
from app.feishu.client import FeishuAuthError, FeishuError
from app.sources import SYNCERS


def test_every_tool_and_source_is_in_the_catalogue_and_nothing_else():
    assert set(TOOLS) == set(catalog.CONTRACTS)
    assert {s.name for s in catalog.SOURCES} == set(SYNCERS)
    for contract in catalog.TOOLS:
        assert contract.effect in catalog.EFFECTS, contract
        assert contract.connector in catalog.CONNECTORS, contract
        assert set(contract.errors) <= set(errors.ERRORS), contract


def test_only_confirm_action_executes_and_only_when_the_person_is_there():
    writers = [t.name for t in catalog.TOOLS if t.effect == "write"]
    assert writers == ["confirm_action"] and TOOLS["confirm_action"].user_initiated_only
    # 名字是 prepare_ / draft_ 开头的都只准备
    for name in TOOLS:
        if name.startswith(("prepare_", "draft_")):
            assert catalog.CONTRACTS[name].effect == "prepare", name


def test_feishu_errors_are_classified_by_cause():
    assert errors.classify(FeishuError("x", 99991679)) == "app_scope"
    assert errors.classify(FeishuError("forbidden", 1061004)) == "no_access"
    assert errors.classify(FeishuAuthError("expired")) == "needs_reauth"
    assert errors.classify(FeishuError("这个工作区还没有接入飞书，请管理员……")) == "not_connected"
    assert errors.classify(FeishuError("boom", 500)) == "upstream"
    try:
        try:
            raise FeishuError("no permission", 1310213)
        except FeishuError as exc:
            raise ToolError("读取表格失败") from exc
    except ToolError as wrapped:
        assert errors.classify(wrapped) == "no_access"  # 工具包了一层，也按根因判断
    assert errors.classify(ToolError("Mac 不在线", "offline")) == "offline"
    result = errors.error_result("read_sheet_range", "app_scope", "读取失败")
    assert result["ok"] is False and result["error"]["code"] == "app_scope" and "管理员" in result["error"]["who"]


class _Session:
    def begin_nested(self):
        class _Nested:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False
        return _Nested()


async def test_prepare_results_say_what_waits_for_confirmation(monkeypatch):
    async def fake_prepare(ctx, args):
        ctx.cards.append({"kind": "action", "action_id": 42})
        return "已准备好（待确认操作 #42）"

    monkeypatch.setattr(TOOLS["prepare_chat_message"], "handler", fake_prepare)
    ctx = ToolContext(session=_Session(), user=SimpleNamespace(), conversation=SimpleNamespace(channel="web"), feishu=None)
    text, failed = await execute(ctx, "prepare_chat_message", {"to": "Budi", "text": "hi"})
    result = json.loads(text)
    assert not failed and result["effect"] == "prepare" and result["needs_confirmation"] and result["pending_action_ids"] == [42]


async def test_executor_enforces_contracts(monkeypatch):
    calls = []

    async def fake_search(ctx, args):
        calls.append(args["query"])
        if args["query"] == "boom":
            raise FeishuError("required privileges", 99991679)
        return "ok"

    monkeypatch.setattr(TOOLS["search_docs"], "handler", fake_search)
    ctx = ToolContext(session=_Session(), user=SimpleNamespace(), conversation=SimpleNamespace(channel="web"), feishu=None)
    # 飞书报错按根因归类，告诉他该谁处理
    text, failed = await execute(ctx, "search_docs", {"query": "boom"})
    assert failed and json.loads(text)["error"]["code"] == "app_scope" and ctx.last_error == "app_scope"
    ok, failed = await execute(ctx, "search_docs", {"query": "报价"})
    assert not failed and json.loads(ok) == {"ok": True, "tool": "search_docs", "effect": "read", "result": "ok"}
    await execute(ctx, "search_docs", {"query": "报价单"})
    # 同一轮第 4 次查找：不再执行，告诉它查过什么
    text, failed = await execute(ctx, "search_docs", {"query": "quotation"})
    assert failed and ctx.last_error == "limit" and "报价单" in text and calls == ["boom", "报价", "报价单"]
    # 没登记的工具、无人值守时执行已确认操作：都不执行
    assert json.loads((await execute(ctx, "no_such_tool", {}))[0])["error"]["code"] == "unsupported"
    text, failed = await execute(ctx, "confirm_action", {"action_id": 1}, user_initiated=False)
    assert failed


def test_docs_are_generated_from_the_catalogue():
    docs = pathlib.Path(os.getenv("RELAY_DOCS") or pathlib.Path(__file__).resolve().parents[2] / "docs") / "CONNECTORS.md"
    if not docs.exists():
        pytest.skip("没有挂载 docs 目录")
    assert docs.read_text(encoding="utf-8") == catalog.render_markdown(), "docs/CONNECTORS.md 过期了：运行 python -m app.connectors.catalog"


def test_conversation_quality_is_compared_by_prompt_version():
    from datetime import UTC, datetime

    from app.api.quality import by_prompt

    def turn(version, outcome, tools, errors):
        return SimpleNamespace(created_at=datetime.now(UTC), detail={
            "prompt": version, "outcome": outcome, "tool_calls": len(tools), "tools": tools, "tool_errors": errors})

    groups = by_prompt([turn(None, "answered", ["search_docs"], []), turn("abc12345", "answered", ["search_docs", "read_mail"], ["limit"]),
                        turn("abc12345", "no_answer", [], [])])
    old, new = groups
    assert old["version"] == "旧版（未记录）" and old["turns"] == 1
    assert new["turns"] == 2 and new["no_answer"]["numerator"] == 1 and new["tool_error"]["numerator"] == 1
    assert new["error_codes"] == {"limit": 1}
