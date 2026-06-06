"""Tests for runner helpers that don't require an LLM."""

from asili_agents.runner import _collect_grounded_facts
from asili_agents.tools.logging import clear_decision_log, log_decision


class TestCollectGroundedFacts:
    def test_parses_stock_and_bundle_from_traces(self):
        clear_decision_log()
        log_decision(agent_name="Messaging", reasoning="Grounding. Stock: 6 units, low.")
        log_decision(agent_name="Pricing", reasoning="Bundle priced at $34.00.")
        facts = _collect_grounded_facts()
        assert facts.get("stock_quantity") == 6
        assert facts.get("stock_level") == "low"
        assert facts.get("bundle_price") == 34.0
        clear_decision_log()

    def test_empty_log_yields_no_facts(self):
        clear_decision_log()
        assert _collect_grounded_facts() == {}
