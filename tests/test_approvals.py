"""Tests for the approval-outcome meter (ladder instrumentation)."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from asili_agents.api import main as main_module
from asili_agents.api.main import app
from asili_agents.data.models import Conversation, ConversationStatus
from asili_agents.tools import approvals
from asili_agents.tools.approvals import normalized_edit_distance


@pytest.fixture(autouse=True)
def _reset():
    approvals.reset_approval_stats()
    yield
    approvals.reset_approval_stats()


class TestEditDistance:
    def test_identical_is_zero(self):
        assert normalized_edit_distance("Yes, 6 tins left.", "Yes, 6 tins left.") == 0.0

    def test_total_rewrite_is_one(self):
        assert normalized_edit_distance("abc", "xyz") == 1.0

    def test_empty_vs_text_is_one(self):
        assert normalized_edit_distance("", "hello") == 1.0
        assert normalized_edit_distance("hello", "") == 1.0

    def test_small_edit_is_small(self):
        d = normalized_edit_distance(
            "Yes, 6 tins left — want me to set two aside?",
            "Yes! 6 tins left — want me to set two aside?",
        )
        assert 0.0 < d < 0.1

    def test_symmetric(self):
        a, b = "purple tea bundle", "purple tea bundles"
        assert normalized_edit_distance(a, b) == normalized_edit_distance(b, a)


class TestMeter:
    def test_rates_and_aggregates(self):
        approvals.record_outcome("approve", time_to_send_s=30, seller_id="amara")
        approvals.record_outcome("approve", time_to_send_s=10, seller_id="amara")
        approvals.record_outcome("edit", edit_distance=0.2, time_to_send_s=50, seller_id="amara")
        approvals.record_outcome("reject", seller_id="amara")
        s = approvals.approval_stats()
        assert s["total"] == 4
        assert s["approval_rate"] == 0.75  # 3 of 4 sent
        assert s["unedited_rate"] == 0.5  # 2 of 4 verbatim
        assert s["avg_edit_distance"] == 0.2
        assert s["median_time_to_send_s"] == 30
        by_seller = s["by_seller"]
        assert isinstance(by_seller, dict)
        assert by_seller["amara"]["total"] == 4

    def test_per_seller_isolation(self):
        approvals.record_outcome("approve", seller_id="a")
        approvals.record_outcome("reject", seller_id="b")
        s = approvals.approval_stats()
        by_seller = s["by_seller"]
        assert isinstance(by_seller, dict)
        assert by_seller["a"]["approval_rate"] == 1.0
        assert by_seller["b"]["approval_rate"] == 0.0

    def test_empty_stats_are_zero(self):
        s = approvals.approval_stats()
        assert s["total"] == 0 and s["approval_rate"] == 0.0


class TestApproveEndpointInstrumentation:
    def _seed(self, client_unused, action_body: str = "Yes, 6 tins left."):
        conv = Conversation(
            seller_id=uuid.uuid4(),
            customer_name="Dana",
            customer_initials="D",
            channel="Telegram",
            status=ConversationStatus.AWAITING_REPLY,
        )
        cid = "tg:approvals-test"
        main_module._state["conversations"][cid] = conv
        main_module._state["pending_drafts"][cid] = {
            "draft_id": "d1",
            "body": action_body,
            "sources": ["stock"],
            "status": "pending",
            "created_at": time.time() - 42.0,
        }
        return cid, conv

    def test_approve_records_time_to_send(self):
        with TestClient(app) as client:
            cid, conv = self._seed(client)
            r = client.post("/api/approve", json={"conversation_id": cid, "action": "approve"})
            assert r.status_code == 200
            s = approvals.approval_stats()
            assert s["approved"] == 1
            tts = s["median_time_to_send_s"]
            assert isinstance(tts, float) and 40 <= tts <= 60

    def test_edit_records_distance(self):
        with TestClient(app) as client:
            cid, conv = self._seed(client, "Yes, 6 tins left.")
            r = client.post(
                "/api/approve",
                json={
                    "conversation_id": cid,
                    "action": "edit",
                    "edited_body": "Yes! 6 tins left, friend.",
                },
            )
            assert r.status_code == 200
            s = approvals.approval_stats()
            assert s["edited"] == 1
            avg_dist = s["avg_edit_distance"]
            assert isinstance(avg_dist, float) and 0.0 < avg_dist < 1.0

    def test_reject_recorded(self):
        with TestClient(app) as client:
            cid, conv = self._seed(client)
            r = client.post("/api/approve", json={"conversation_id": cid, "action": "reject"})
            assert r.status_code == 200
            s = approvals.approval_stats()
            assert s["rejected"] == 1 and s["approval_rate"] == 0.0

    def test_metrics_endpoint_exposes_approvals(self):
        with TestClient(app) as client:
            cid, conv = self._seed(client)
            client.post("/api/approve", json={"conversation_id": cid, "action": "approve"})
            body = client.get("/api/metrics").json()
            assert "approvals" in body
            assert body["approvals"]["approved"] == 1
            assert str(conv.seller_id) in body["approvals"]["by_seller"]


class TestPasteConversation:
    """Tier-0 channel fallback: paste a DM, get a conversation to draft against."""

    def test_paste_creates_conversation_with_inbound(self):
        with TestClient(app) as client:
            r = client.post(
                "/api/conversations/paste",
                json={
                    "text": "Hi! Do you still have the shea butter in the 8oz jar?",
                    "customer_name": "Imani",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["customer_name"] == "Imani"
            assert body["channel"] == "Instagram DM"
            assert len(body["messages"]) == 1
            assert body["messages"][0]["direction"] == "in"
            assert "shea butter" in body["messages"][0]["body"]
            # It lands in the inbox and is retrievable by id.
            conv = client.get(f"/api/conversations/{body['id']}").json()
            assert conv["customer_name"] == "Imani"

    def test_paste_defaults_and_truncation(self):
        with TestClient(app) as client:
            r = client.post("/api/conversations/paste", json={"text": "x" * 3000})
            assert r.status_code == 200
            body = r.json()
            assert body["customer_name"] == "Customer"
            # Inbound text is capped at MAX_INBOUND_CHARS like every other channel.
            assert len(body["messages"][0]["body"]) == main_module.MAX_INBOUND_CHARS

    def test_paste_rejects_empty_text(self):
        with TestClient(app) as client:
            r = client.post("/api/conversations/paste", json={"text": ""})
            assert r.status_code == 422
