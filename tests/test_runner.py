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

    def _event_with_response(self, name, response):
        """Shape an event the way _event_to_dict serializes function responses."""
        return {"content": {"parts": [{"function_response": {"name": name, "response": response}}]}}

    def test_prefers_structured_tool_responses_over_prose(self):
        """Facts come from the tools' structured function responses, not regex
        over reasoning prose — and the structured value wins even if the prose
        says something else."""
        clear_decision_log()
        # Prose claims 99; the structured check_stock response says 6 — structured wins.
        log_decision(agent_name="Messaging", reasoning="Stock: 99 units, high.")
        raw_events = [
            self._event_with_response("check_stock", {"quantity": 6, "level": "low"}),
            self._event_with_response(
                "compute_bundle_price", {"bundle_price": 34.0, "is_margin_safe": True}
            ),
        ]
        facts = _collect_grounded_facts(raw_events)
        assert facts["stock_quantity"] == 6
        assert facts["stock_level"] == "low"
        assert facts["bundle_price"] == 34.0
        assert facts["is_margin_safe"] is True
        clear_decision_log()

    def test_unwraps_adk_result_envelope(self):
        """ADK may wrap a tool's return under a 'result' key; we unwrap it."""
        clear_decision_log()
        raw_events = [
            self._event_with_response("check_stock", {"result": {"quantity": 4, "level": "low"}})
        ]
        facts = _collect_grounded_facts(raw_events)
        assert facts["stock_quantity"] == 4
        clear_decision_log()

    def test_falls_back_to_prose_when_no_structured_facts(self):
        """The MCP path doesn't surface the in-process tool dicts, so the
        decision-log prose fallback still recovers facts."""
        clear_decision_log()
        log_decision(agent_name="Messaging", reasoning="Grounding. Stock: 6 units, low.")
        log_decision(agent_name="Pricing", reasoning="Bundle priced at $34.00.")
        facts = _collect_grounded_facts(raw_events=[])
        assert facts["stock_quantity"] == 6
        assert facts["bundle_price"] == 34.0
        clear_decision_log()
