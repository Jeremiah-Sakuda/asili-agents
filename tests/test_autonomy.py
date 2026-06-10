"""Tests for the graduated autonomy ladder + its integration with the gate."""

import pytest

from asili_agents.tools import autonomy, channel
from asili_agents.tools.autonomy import (
    AutonomyPolicy,
    AutonomyTier,
    classify_intent,
    decide_tier,
)


@pytest.fixture(autouse=True)
def _reset():
    autonomy.reset_autonomy_stats()
    channel.set_autonomy_policy(None)
    channel._approval_callback = None
    channel.set_auto_approve(False)
    yield
    autonomy.reset_autonomy_stats()
    channel.set_autonomy_policy(None)
    channel._approval_callback = None
    channel.set_auto_approve(False)


class TestClassifyIntent:
    def test_high_stakes_classes_hold(self):
        assert classify_intent("I'm so sorry, here is your refund") == "refund"
        assert classify_intent("We'll cancel that order for you") == "cancellation"
        assert classify_intent("Unfortunately the purple tea is sold out") == "out_of_stock"
        assert classify_intent("So sorry you're disappointed") == "complaint"

    def test_low_risk_classes(self):
        assert classify_intent("Yes, 6 tins left and available") == "stock_check"
        assert classify_intent("I can do a 2-tin bundle for $34") == "bundle_quote"
        assert classify_intent("That would be $18 each", agent_name="Pricing") == "price_quote"
        assert classify_intent("Thanks for reaching out!") == "acknowledgment"


class TestDecideTier:
    def _policy(self, **kw):
        base = {"enabled": True, "auto_intents": {"stock_check", "price_quote", "bundle_quote"}}
        base.update(kw)
        return AutonomyPolicy(**base)

    def test_fail_closed_no_policy(self):
        assert decide_tier(None, "stock_check", grounded=True) is AutonomyTier.HOLD

    def test_disabled_policy_holds(self):
        p = self._policy(enabled=False)
        assert decide_tier(p, "stock_check", grounded=True) is AutonomyTier.HOLD

    def test_always_hold_intent_never_auto(self):
        p = self._policy(auto_intents={"refund", "stock_check"})
        assert decide_tier(p, "refund", grounded=True) is AutonomyTier.HOLD

    def test_intent_not_opted_in_holds(self):
        p = self._policy(auto_intents={"stock_check"})
        assert decide_tier(p, "price_quote", grounded=True, margin_safe=True) is AutonomyTier.HOLD

    def test_requires_grounded(self):
        p = self._policy()
        assert decide_tier(p, "stock_check", grounded=False) is AutonomyTier.HOLD
        assert decide_tier(p, "stock_check", grounded=True) is AutonomyTier.AUTO

    def test_requires_margin_safe_for_pricing(self):
        p = self._policy()
        assert decide_tier(p, "price_quote", grounded=True, margin_safe=False) is AutonomyTier.HOLD
        assert decide_tier(p, "price_quote", grounded=True, margin_safe=True) is AutonomyTier.AUTO

    def test_happy_path_auto(self):
        p = self._policy()
        assert decide_tier(p, "stock_check", grounded=True) is AutonomyTier.AUTO


class TestAutonomyMeter:
    def test_rate_accumulates(self):
        autonomy.record_decision(AutonomyTier.AUTO)
        autonomy.record_decision(AutonomyTier.AUTO)
        autonomy.record_decision(AutonomyTier.HOLD)
        s = autonomy.autonomy_stats()
        assert s["auto"] == 2 and s["held"] == 1 and s["total"] == 3
        assert abs(s["autonomy_rate"] - (2 / 3)) < 1e-9

    def test_empty_rate_is_zero(self):
        assert autonomy.autonomy_stats()["autonomy_rate"] == 0.0


class TestChannelIntegration:
    def test_no_policy_holds_pending(self):
        # Fail-closed default unchanged: no policy -> PENDING.
        r = channel.send_for_approval("Yes, 6 tins left.", sources=["Stock"], intent="stock_check")
        assert r["status"] == "pending"
        assert autonomy.autonomy_stats()["auto"] == 0

    def test_tier1_auto_executes_and_meters(self):
        channel.set_autonomy_policy(
            AutonomyPolicy(enabled=True, auto_intents={"stock_check"})
        )
        r = channel.send_for_approval(
            "Yes, 6 tins left.", sources=["Stock · 6 tins"], intent="stock_check", grounded=True
        )
        assert r["status"] == "approved"
        assert r["approved_by"] == "tier1_autonomy:stock_check"
        assert autonomy.autonomy_stats()["auto"] == 1

    def test_tier1_overrides_human_callback_for_allowed_class(self):
        # Even with a human callback wired, the opted-in low-risk class auto-executes.
        from asili_agents.tools.channel import ApprovalResult, ApprovalStatus

        channel._approval_callback = lambda did, body: ApprovalResult(
            status=ApprovalStatus.PENDING, draft_id=did, body=body
        )
        channel.set_autonomy_policy(AutonomyPolicy(enabled=True, auto_intents={"stock_check"}))
        r = channel.send_for_approval("6 tins left", sources=["Stock"], intent="stock_check", grounded=True)
        assert r["status"] == "approved"

    def test_high_stakes_holds_even_with_policy(self):
        channel._approval_callback = None
        channel.set_autonomy_policy(
            AutonomyPolicy(enabled=True, auto_intents={"stock_check", "refund"})
        )
        r = channel.send_for_approval(
            "I'm sorry, here's your refund.", sources=["x"], intent="refund", grounded=True
        )
        assert r["status"] == "pending"
        assert autonomy.autonomy_stats()["held"] == 1


class TestMetricsEndpoint:
    def test_metrics_endpoint_reflects_meters(self):
        from fastapi.testclient import TestClient

        from asili_agents.api.main import app
        from asili_agents.tools import cost
        from asili_agents.tools.cost import ModelTier

        autonomy.reset_autonomy_stats()
        cost.reset_cost()
        autonomy.record_decision(AutonomyTier.AUTO)
        cost.record_call(ModelTier.ROUTINE, 100, 100, seller_id="amara")
        with TestClient(app) as c:
            body = c.get("/api/metrics").json()
        assert body["autonomy"]["auto"] == 1
        assert body["autonomy"]["autonomy_rate"] == 1.0
        assert body["cost"]["total_calls"] == 1
        autonomy.reset_autonomy_stats()
        cost.reset_cost()
