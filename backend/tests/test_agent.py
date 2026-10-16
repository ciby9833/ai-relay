from datetime import UTC, datetime, timedelta

import pytest

from app.agent.loop import sanitize_history
from app.agent.tools import tool_specs
from app.llm.anthropic_provider import to_anthropic_messages
from app.llm.gemini_provider import to_gemini_contents
from app.llm.openai_provider import to_openai_messages
from app.scheduler.schedule import ScheduleError, next_cron_run, parse_run_at, validate_cron


def text(role, value):
    return {"role": role, "content": [{"type": "text", "text": value}]}


CALL = {
    "role": "assistant",
    "content": [
        {"type": "text", "text": "我记一下"},
        {"type": "tool_use", "id": "call_1", "name": "remember", "input": {"content": "x"}},
    ],
}
RESULT = {
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": "call_1",
            "name": "remember",
            "content": "已记住",
            "is_error": False,
        }
    ],
}
HISTORY = [text("user", "你好"), CALL, RESULT, text("assistant", "好了")]


def test_sanitize_drops_orphaned_head_and_dangling_tail():
    # 窗口正好从工具结果开始、以未完成的工具调用结束
    assert sanitize_history([RESULT, text("assistant", "好了"), text("user", "再来"), CALL]) == [
        text("user", "再来")
    ]
    assert sanitize_history(HISTORY) == HISTORY


def test_anthropic_conversion():
    messages = to_anthropic_messages(HISTORY)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1]["content"][1]["type"] == "tool_use"
    assert messages[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "call_1",
        "content": "已记住",
    }


def test_anthropic_replays_raw_turn_untouched():
    raw = [object()]
    messages = to_anthropic_messages([{**CALL, "raw": raw, "raw_provider": "anthropic"}])
    assert messages[0]["content"] is raw


def test_openai_conversion():
    messages = to_openai_messages("sys", HISTORY)
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "assistant"]
    assert messages[2]["tool_calls"][0]["function"]["arguments"] == '{"content": "x"}'
    assert messages[3]["tool_call_id"] == "call_1"


def test_gemini_conversion():
    contents = to_gemini_contents(HISTORY)
    assert [c.role for c in contents] == ["user", "model", "user", "model"]
    assert contents[1].parts[1].function_call.name == "remember"
    assert contents[2].parts[0].function_response.response == {"result": "已记住"}


def test_context_block_marker_is_not_sent_to_models():
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "<context>…</context>", "meta": "context"},
            {"type": "text", "text": "hi"},
        ],
    }
    assert all("meta" not in block for block in to_anthropic_messages([message])[0]["content"])


def test_tool_specs_are_stable_and_closed():
    specs = tool_specs()
    assert [s["name"] for s in specs] == sorted(s["name"] for s in specs)
    assert all(s["input_schema"]["additionalProperties"] is False for s in specs)


def test_cron_runs_in_user_timezone():
    after = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)  # 雅加达 07:00
    assert next_cron_run("0 9 * * *", "Asia/Jakarta", after) == datetime(
        2026, 10, 14, 2, 0, tzinfo=UTC
    )


def test_cron_rejects_too_frequent_and_invalid():
    with pytest.raises(ScheduleError):
        validate_cron("* * * * *", "Asia/Jakarta")
    with pytest.raises(ScheduleError):
        validate_cron("not a cron", "Asia/Jakarta")


def test_run_at_naive_uses_user_timezone_and_must_be_future():
    future = datetime.now(UTC) + timedelta(days=1)
    local = future.astimezone().replace(tzinfo=None)
    assert parse_run_at(future.isoformat(), "Asia/Jakarta") == future
    assert parse_run_at(local.isoformat(), "UTC").tzinfo is not None
    with pytest.raises(ScheduleError):
        parse_run_at("2020-01-01T09:00", "Asia/Jakarta")


class _ApprovalFeishu:
    def __init__(self, form, tasks):
        self.form, self.tasks = form, tasks

    async def tenant_api(self, method, path, **kwargs):
        return {"approval_name": "需求申请", "form": self.form, "task_list": self.tasks}


async def test_approval_needing_input_must_go_to_feishu():
    from app.sources.approval import instance_detail, needs_input

    filled = '[{"name": "需求描述", "type": "textarea", "value": "对接凭证号"}, {"name": "说明", "type": "text", "value": ""}]'
    empty_handler = '[{"name": "需求描述", "type": "textarea", "value": "对接凭证号"}, {"name": "IT 处理人", "type": "contact", "value": []}]'
    me = [{"status": "PENDING", "open_id": "ou_me", "node_name": "部门负责人审批"}]
    assign_node = [{"status": "PENDING", "open_id": "ou_me", "node_name": "IT 分配处理人"}]

    simple = await instance_detail(_ApprovalFeishu(filled, me), "I1", "ou_me")
    assert not needs_input(simple)  # 说明文字控件为空不算待填

    empty = await instance_detail(_ApprovalFeishu(empty_handler, me), "I1", "ou_me")
    assert needs_input(empty) and empty["input_hint"] == "IT 处理人"

    by_node = await instance_detail(_ApprovalFeishu(filled, assign_node), "I1", "ou_me")
    assert needs_input(by_node) and "IT 分配处理人" in by_node["input_hint"]

    assert needs_input(None)  # 拿不到明细时保守处理


def test_dm_keeps_mentioned_names_and_drops_bot():
    import json as _json

    from app.feishu.events import mentioned_people, text_with_names

    message = {
        "message_type": "text",
        "content": _json.dumps({"text": "@_user_1 帮我约 @_user_2 和 @_user_3 下周五开会"}),
        "mentions": [
            {"key": "@_user_1", "id": {"open_id": "ou_bot"}, "name": "Cargo AI"},
            {"key": "@_user_2", "id": {"open_id": "ou_a"}, "name": "Andrew（陈春华）"},
            {"key": "@_user_3", "id": {"open_id": "ou_n"}, "name": "Nikki（皮雪峰）"},
        ],
    }
    assert text_with_names(message, {"ou_bot"}) == "帮我约 @Andrew（陈春华） 和 @Nikki（皮雪峰） 下周五开会"
    assert ("ou_a", "Andrew（陈春华）", "mention") in mentioned_people(message)


def test_name_variants_cover_both_languages():
    from app.sources.people import _variants

    assert set(_variants("@Andrew（陈春华）")) >= {"Andrew（陈春华）", "陈春华", "Andrew"}
    assert set(_variants("Jeffrey (郭敬贤)")) >= {"郭敬贤", "Jeffrey"}


async def test_login_requests_scopes_the_app_actually_has():
    from app.config import get_settings
    from app.feishu.client import FeishuClient

    class _Client(FeishuClient):
        async def tenant_api(self, method, path, **kwargs):
            assert path == "/application/v6/scopes"
            return {"scopes": [
                {"scope_name": "offline_access", "scope_type": "user", "grant_status": 1},
                {"scope_name": "calendar:calendar.event:create", "scope_type": "user", "grant_status": 1},
                {"scope_name": "task:task:write", "scope_type": "user", "grant_status": 2},  # 未开通
                {"scope_name": "im:message", "scope_type": "tenant", "grant_status": 1},  # 应用身份，登录不申请
            ]}

    client = _Client(get_settings(), http=None)
    assert await client.granted_user_scopes() == ["calendar:calendar.event:create", "offline_access"]
    assert "calendar%3Acalendar.event%3Acreate+offline_access" in client.authorize_url("s", await client.granted_user_scopes())


async def test_find_person_prefers_chinese_name_and_reports_ambiguity():
    from app.sources import people

    class _Session:
        async def execute(self, statement):
            class _Result:
                def scalars(self_inner):
                    class _Scalars(list):
                        def all(self):
                            return list(self)
                    return _Scalars()
            return _Result()

    class _Feishu:
        def __init__(self):
            self.queries = []

        async def user_api(self, user, method, path, **kwargs):
            q = kwargs["params"]["query"]
            self.queries.append(q)
            return {"users": {
                "陈春华": [{"name": "Andrew（陈春华）", "open_id": "ou_right"}],
                "Andrew": [{"name": "Andrew Lee", "open_id": "ou_1"}, {"name": "Andrew Tan", "open_id": "ou_2"}],
                "Kevin": [{"name": "Kevin A", "open_id": "ou_k1"}, {"name": "Kevin B", "open_id": "ou_k2"}],
            }.get(q, [])}

    async def no_remember(session, rows):
        pass

    people.remember, original = no_remember, people.remember
    try:
        feishu = _Feishu()
        found = await people.find(_Session(), feishu, "Andrew（陈春华）", user=object())
        assert found[0]["open_id"] == "ou_right" and feishu.queries[0] == "陈春华"
        try:
            await people.find(_Session(), _Feishu(), "Kevin", user=object())
            raise AssertionError("应该提示同名")
        except people.Ambiguous as exc:
            assert {c["name"] for c in exc.candidates} == {"Kevin A", "Kevin B"}
    finally:
        people.remember = original


def test_reply_all_cc_excludes_self_and_sender_and_dedupes():
    import base64 as _b64
    import email as _email
    import email.policy as _policy

    from app.sources.mail import build_reply, reply_all_cc

    mail = {
        "subject": "报价确认", "from_address": "a@client.com", "smtp_message_id": "<m1@client.com>",
        "to_addresses": [{"name": "阿明", "mail_address": "Me@co.com"}, {"name": "Bob", "mail_address": "bob@client.com"}],
        "cc_addresses": [{"name": "客户A", "mail_address": "a@client.com"}, {"name": "Lily", "mail_address": "lily@co.com"},
                         {"name": "Bob", "mail_address": "BOB@client.com"}],
    }
    cc = reply_all_cc(mail, {"me@co.com"})
    assert [c["mail_address"] for c in cc] == ["bob@client.com", "lily@co.com"]

    class _User:
        name, email = "阿明", "me@co.com"

    eml = _email.message_from_bytes(_b64.urlsafe_b64decode(build_reply(_User(), mail, "好的", cc) + "=="), policy=_policy.default)
    assert eml["To"] == "a@client.com" and "bob@client.com" in eml["Cc"] and "lily@co.com" in eml["Cc"]
    assert "me@co.com" not in eml["Cc"].lower() and eml["In-Reply-To"] == "<m1@client.com>"
    only_sender = _email.message_from_bytes(_b64.urlsafe_b64decode(build_reply(_User(), mail, "好的") + "=="), policy=_policy.default)
    assert only_sender["Cc"] is None
