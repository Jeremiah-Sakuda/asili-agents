"""Tests for the Telegram channel integration."""

import uuid

import pytest
from fastapi.testclient import TestClient

from asili_agents.api import main as main_module
from asili_agents.api.main import app
from asili_agents.data.models import Conversation, ConversationStatus
from asili_agents.integrations.telegram import initials_of, parse_update
from asili_agents.runner import RunResult


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class FakeTelegram:
    """Records outbound calls instead of hitting the Telegram API."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))
        return {"ok": True, "result": {"message_id": 1}}

    async def send_chat_action(self, chat_id, action="typing"):
        self.actions.append((chat_id, action))
        return {"ok": True}


class TestParseUpdate:
    def test_text_message(self):
        msg = parse_update(
            {
                "message": {
                    "message_id": 7,
                    "from": {"first_name": "Dana", "last_name": "R"},
                    "chat": {"id": 555},
                    "text": "hi",
                }
            }
        )
        assert msg is not None
        assert msg.chat_id == "555"
        assert msg.text == "hi"
        assert msg.sender_name == "Dana R"
        assert msg.message_id == 7

    def test_no_message(self):
        assert parse_update({"update_id": 1}) is None

    def test_callback_only_is_ignored(self):
        assert parse_update({"callback_query": {"id": "x"}}) is None

    def test_initials(self):
        assert initials_of("Dana R") == "DR"
        assert initials_of("Dana") == "DA"
        assert initials_of("") == "C"


class TestWebhook:
    def test_rejects_bad_secret(self, client, monkeypatch):
        monkeypatch.setitem(main_module._state, "telegram_secret", "topsecret")
        r = client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": 1}, "text": "hi"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert r.status_code == 401

    def test_non_text_update_skipped(self, client):
        r = client.post("/api/telegram/webhook", json={"update_id": 1})
        assert r.status_code == 200
        assert r.json()["skipped"] is True

    def test_creates_pending_draft_without_sending(self, client, monkeypatch):
        async def fake_run(runner, message, **kwargs):
            return RunResult(
                steps=[],
                draft="Yes, 6 tins in stock.",
                draft_sources=["stock"],
                facts={},
                raw_events=[],
                success=True,
            )

        monkeypatch.setattr(main_module, "create_runner", lambda *a, **k: object())
        monkeypatch.setattr(main_module, "run_agent_async", fake_run)
        fake_tg = FakeTelegram()
        monkeypatch.setitem(main_module._state, "telegram", fake_tg)

        payload = {
            "message": {
                "message_id": 1,
                "from": {"first_name": "Dana"},
                "chat": {"id": 555},
                "text": "Is purple tea in stock?",
            }
        }
        r = client.post("/api/telegram/webhook", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pending"] is True
        assert body["conversation_id"] == "tg:555"

        pending = main_module._state["pending_drafts"].get("tg:555")
        assert pending is not None
        assert pending["channel"] == "telegram"
        assert pending["chat_id"] == "555"

        # The approval gate holds: nothing was sent to the customer yet.
        assert fake_tg.sent == []
        # A typing indicator was acknowledged.
        assert fake_tg.actions and fake_tg.actions[0][0] == "555"
        # Only the inbound message is on the conversation.
        conv = main_module._state["conversations"]["tg:555"]
        assert len(conv.messages) == 1
        assert conv.messages[0].direction.value == "in"


class TestApproveDelivers:
    def test_approve_sends_to_telegram(self, client, monkeypatch):
        fake_tg = FakeTelegram()
        monkeypatch.setitem(main_module._state, "telegram", fake_tg)
        conv = Conversation(
            seller_id=uuid.uuid4(),
            customer_name="Dana",
            customer_initials="D",
            channel="Telegram",
            status=ConversationStatus.AWAITING_REPLY,
        )
        cid = "tg:777"
        monkeypatch.setitem(main_module._state["conversations"], cid, conv)
        monkeypatch.setitem(
            main_module._state["pending_drafts"],
            cid,
            {
                "draft_id": "d",
                "body": "Yes, 6 tins.",
                "sources": ["stock"],
                "status": "pending",
                "channel": "telegram",
                "chat_id": "777",
            },
        )
        r = client.post("/api/approve", json={"conversation_id": cid, "action": "approve"})
        assert r.status_code == 200, r.text
        assert fake_tg.sent == [("777", "Yes, 6 tins.")]
