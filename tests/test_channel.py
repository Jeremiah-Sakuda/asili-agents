"""Tests for the human-approval gate (fail-closed behavior)."""

from asili_agents.tools import channel as channel_module
from asili_agents.tools.channel import channel_send, send_for_approval, set_auto_approve


def _clear_callback() -> None:
    channel_module._approval_callback = None


def test_channel_send_fails_closed_without_callback():
    """With no send callback wired, channel_send must NOT simulate a successful
    send — it fails closed so nothing silently looks delivered."""
    channel_module._send_callback = None
    result = channel_send("telegram", "Yes, 6 tins in stock.")
    assert result["success"] is False
    assert result["message_id"] is None
    assert "no send callback" in (result["error"] or "")


def test_fail_closed_pending_without_callback():
    """With no approval callback wired, drafts stay PENDING — never auto-sent."""
    _clear_callback()
    set_auto_approve(False)
    result = send_for_approval("Yes, 6 tins in stock.")
    assert result["status"] == "pending"
    assert result["body"] == "Yes, 6 tins in stock."


def test_explicit_auto_approve_opt_in():
    """Auto-approve only happens when explicitly enabled (e.g. the CLI demo)."""
    _clear_callback()
    set_auto_approve(True)
    try:
        result = send_for_approval("Yes, 6 tins.")
        assert result["status"] == "approved"
    finally:
        set_auto_approve(False)
