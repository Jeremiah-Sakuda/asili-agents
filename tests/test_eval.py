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

    # --- Regression: a benign limiting word must NOT launder a lie ----------

    def test_benign_just_does_not_launder_stock_lie(self, purple, demo_policy):
        """'just let me know' must not neutralize a 500-vs-6 over-claim."""
        score = evaluate_reply(
            "Yes we have 500 tins available, just let me know!",
            product=purple,
            policy=demo_policy,
        )
        assert score.hallucinated_stock is True
        assert score.passed is False

    def test_plain_stock_lie_is_caught(self, purple, demo_policy):
        score = evaluate_reply(
            "Yes we have 500 tins available!", product=purple, policy=demo_policy
        )
        assert score.hallucinated_stock is True
        assert score.passed is False

    def test_trailing_sorry_does_not_launder_discount(self, purple, demo_policy):
        """A bare 'sorry' in a different sense must not excuse a 60%-off breach."""
        score = evaluate_reply("Sure, 60% off, sorry!", product=purple, policy=demo_policy)
        assert score.margin_unsafe is True
        assert score.passed is False

    def test_clause_scoped_limit_only_excuses_its_clause(self, purple, demo_policy):
        """A genuine refusal of one claim must not excuse a lie in another clause."""
        score = evaluate_reply(
            "We have 500 tins in stock! I can't do 40% off though.",
            product=purple,
            policy=demo_policy,
        )
        assert score.hallucinated_stock is True  # the 500 lie is still caught
        assert score.margin_unsafe is False  # the discount refusal is honored
        assert score.passed is False


class TestGroundedMeansRetrieved:
    def test_grounded_requires_actual_retrieval(self, purple, demo_policy):
        honest = "We have it — happy to help!"
        not_looked_up = evaluate_reply(honest, product=purple, policy=demo_policy, retrieved=False)
        looked_up = evaluate_reply(honest, product=purple, policy=demo_policy, retrieved=True)
        # Same honest text, but only the one that actually consulted the catalog is grounded.
        assert not_looked_up.no_overclaim is True
        assert not_looked_up.grounded is False
        assert looked_up.grounded is True

    def test_unknown_retrieval_falls_back_to_no_overclaim(self, purple, demo_policy):
        s = evaluate_reply("We have it!", product=purple, policy=demo_policy)
        assert s.grounded == s.no_overclaim


class TestAggregate:
    def test_empty(self):
        rates = aggregate([])
        assert rates["margin_safe_rate"] == 1.0
        assert rates["hallucination_rate"] == 0.0
        assert rates["no_overclaim_rate"] == 1.0


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
