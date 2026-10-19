"""Gemini 3 会校验历史里函数调用的思考签名：存了就带回，没有就用占位签名。"""
import base64

from app.llm.gemini_provider import SKIP_SIGNATURE, to_gemini_contents


def test_function_calls_carry_saved_or_placeholder_signature():
    saved = base64.b64encode(b"sig-bytes").decode()
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "查一下"}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "a", "name": "read_mail", "input": {"mail_id": "1"}, "signature": saved},
            {"type": "tool_use", "id": "b", "name": "search_mail", "input": {"query": "x"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "name": "read_mail", "content": "ok"},
            {"type": "tool_result", "tool_use_id": "b", "name": "search_mail", "content": "ok"},
        ]},
    ]
    parts = to_gemini_contents(messages)[1].parts
    assert parts[0].thought_signature == b"sig-bytes"
    assert parts[1].thought_signature == SKIP_SIGNATURE
