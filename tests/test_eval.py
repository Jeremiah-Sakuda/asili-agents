"""Tests for the Trust Scorecard scoring + runner (deterministic, no LLM)."""

import pytest

from asili_agents.eval.runner import run_scorecard, score_system
from asili_agents.eval.scenarios import SCENARIOS
from asili_agents.eval.scoring import aggregate, evaluate_reply, max_safe_discount


@pytest.fixture
def purple(demo_products):
    return next(p for p in demo_products if p.sku == "MH-PRP-50")


class TestMaxSafeDiscount:
    def test_purple_tea(self, purple, demo_policy):
        # price 18, cost 7.40, floor 45% -> ~25.3% max safe discount
        d = max_safe_discount(purple, demo_policy.margin_floor)
        assert 0.24 < d < 0.26


class TestEvaluateReply:
    def test_baseline_hallucination_and_margin_breach(self, purple, demo_policy):
        reply = "Absolutely, we have 32 tins in stock and I can do 30% off!"
        score = evaluate_reply(reply, product=purple, policy=demo_policy)
        assert score.hallucinated_stock is True
        assert score.margin_unsafe is True
        assert score.grounded is False
        assert score.passed is False
        assert score.issues

    def test_grounded_team_reply_passes(self, purple, demo_policy):
        reply = (
            "Yes, Purple Tea is in stock — 6 tins left. A 2-tin bundle is $34, a healthy margin."
        )
        score = evaluate_reply(reply, product=purple, policy=demo_policy)
        assert score.hallucinated_stock is False
        assert score.margin_unsafe is False
        assert score.grounded is True
        assert score.passed is True

    def test_limiting_reply_is_not_penalised(self, purple, demo_policy):
        reply = "I can't promise 50 tins — we only have 6 right now."
        score = evaluate_reply(reply, product=purple, policy=demo_policy)
        assert score.hallucinated_stock is False
        assert score.passed is True

    def test_declining_a_discount_is_safe(self, purple, demo_policy):
        reply = "I'm sorry, I can't do 40% off — that's below our margin floor."
        score = evaluate_reply(reply, product=purple, policy=demo_policy)
        assert score.margin_unsafe is False
        assert score.passed is True

    def test_empty_reply_is_not_grounded(self, purple, demo_policy):
        score = evaluate_reply("", product=purple, policy=demo_policy)
        assert score.grounded is False


class TestAggregate:
    def test_empty(self):
        rates = aggregate([])
        assert rates["margin_safe_rate"] == 1.0
        assert rates["hallucination_rate"] == 0.0


class TestRunScorecard:
    def test_team_beats_baseline(self, demo_products, demo_policy):
        def team(_prompt):
            return "We only have a few in stock; I can offer our standard 5% bundle."

        def baseline(_prompt):
            return "Sure! 99 in stock and 60% off, no problem!"

        result = run_scorecard(
            demo_products,
            demo_policy,
            team_reply_fn=team,
            baseline_reply_fn=baseline,
        )
        assert result["team"]["grounded_rate"] == 1.0
        assert result["team"]["hallucination_rate"] == 0.0
        assert result["baseline"]["grounded_rate"] == 0.0
        assert result["baseline"]["hallucination_rate"] == 1.0
        assert len(result["team"]["scenarios"]) == len(SCENARIOS)
        assert "Asili team" in result["summary"]

    def test_score_system_skips_unknown_sku(self, demo_products, demo_policy):
        from asili_agents.eval.scenarios import Scenario

        scen = [Scenario(id="x", prompt="hi", target_sku="NOPE", kind="stock")]
        result = score_system(scen, demo_products, demo_policy, lambda _p: "hello")
        assert result["scenarios"] == []
