"""Tests for the model-tiering cost meter."""

import pytest

from asili_agents.tools import cost
from asili_agents.tools.cost import ModelTier, estimate_cost, tier_for_agent


@pytest.fixture(autouse=True)
def _reset():
    cost.reset_cost()
    yield
    cost.reset_cost()


def test_routine_is_strictly_cheaper_than_complex():
    # The load-bearing property: routing routine volume to the cheap tier saves money.
    r = estimate_cost(ModelTier.ROUTINE, 1000, 1000)
    c = estimate_cost(ModelTier.COMPLEX, 1000, 1000)
    assert r < c


def test_tier_for_agent_routing():
    assert tier_for_agent("messaging_agent") is ModelTier.ROUTINE
    assert tier_for_agent("pricing_agent") is ModelTier.ROUTINE
    assert tier_for_agent("operations_manager") is ModelTier.COMPLEX
    assert tier_for_agent("baseline_agent") is ModelTier.COMPLEX
    assert tier_for_agent(None) is ModelTier.COMPLEX


def test_record_and_aggregate_stats():
    cost.record_call(ModelTier.ROUTINE, 1000, 500, seller_id="seller_a")
    cost.record_call(ModelTier.COMPLEX, 2000, 800, seller_id="seller_b")
    agg = cost.cost_stats()
    assert agg["total_calls"] == 2
    assert agg["total_cost"] > 0
    assert set(agg["by_seller"].keys()) == {"seller_a", "seller_b"}


def test_per_seller_cost_curve():
    for _ in range(3):
        cost.record_call(ModelTier.ROUTINE, 500, 200, seller_id="amara")
    s = cost.cost_stats("amara")
    assert s["calls"] == 3
    assert s["cost_per_call"] > 0
    # A seller with no calls reads as zero, not an error.
    assert cost.cost_stats("nobody")["calls"] == 0


def test_current_seller_attribution():
    cost.set_current_seller("kofi")
    cost.record_call(ModelTier.ROUTINE, 100, 100)  # no explicit seller_id
    assert "kofi" in cost.cost_stats()["by_seller"]


def test_cheaper_tier_bends_the_curve():
    # Same token volume, routine tier => lower cost-per-call than complex.
    cost.record_call(ModelTier.ROUTINE, 1000, 1000, seller_id="r")
    cost.record_call(ModelTier.COMPLEX, 1000, 1000, seller_id="c")
    assert cost.cost_stats("r")["cost_per_call"] < cost.cost_stats("c")["cost_per_call"]
