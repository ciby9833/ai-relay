"""Web UI descriptors keep translated chrome separate from stored business content."""
from types import SimpleNamespace

import pytest

from app.proactive.cards import ask_ui


def item(**patch):
    return SimpleNamespace(status="open", owner="me", kind="reply", next_step=None, waiting_on=None, **patch)


@pytest.mark.parametrize("status", ["accept", "tentative", "decline"])
def test_invitation_descriptor_preserves_recommendation(status):
    action = SimpleNamespace(status="pending", kind="calendar_rsvp", payload={"status": status})
    assert ask_ui(item(), action) == {"key": f"ask.rsvp.{status}"}


def test_draft_and_followup_descriptors():
    action = SimpleNamespace(status="pending", kind="send_mail", summary="Reply")
    assert ask_ui(item(), action) == {"key": "ask.draft"}
    action.summary = "跟进订单"
    assert ask_ui(item(), action) == {"key": "ask.followup"}


def test_dynamic_content_is_never_rewritten():
    row = item()
    row.next_step = "原始业务要求 — original instructions"
    assert ask_ui(row, None) is None
    assert row.next_step == "原始业务要求 — original instructions"
    action = SimpleNamespace(status="pending", kind="approval_decision", summary="原始审批摘要")
    assert ask_ui(row, action) == {"key": "ask.confirm", "values": {"summary": "原始审批摘要"}}
    row.status = "done"
    assert ask_ui(row, action) is None


def test_waiting_and_default_descriptors():
    row = item()
    assert ask_ui(row, None) == {"key": "ask.handle"}
    row.kind = "approval"
    assert ask_ui(row, None) == {"key": "ask.approval"}
    row.owner = "others"
    assert ask_ui(row, None) == {"key": "ask.waitingUnknown"}
    row.waiting_on = "王五 / Andrew"
    assert ask_ui(row, None) == {"key": "ask.waiting", "values": {"person": "王五 / Andrew"}}
