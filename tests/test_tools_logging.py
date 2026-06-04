"""Tests for decision logging tools."""

import pytest

from asili_agents.tools.logging import (
    log_decision,
    get_decision_log,
    clear_decision_log,
)


class TestLogDecision:
    """Tests for the log_decision tool."""

    def test_log_basic_decision(self):
        """Test logging a basic decision."""
        result = log_decision(
            agent_name="Operations Manager",
            reasoning="Routing: product question.",
            agent_role="Orchestrator",
            step_type="route",
        )

        assert "id" in result
        assert result["agent_name"] == "Operations Manager"
        assert result["reasoning_trace"] == "Routing: product question."

    def test_log_with_grounded_facts(self):
        """Test logging a decision with grounded facts."""
        result = log_decision(
            agent_name="Messaging",
            reasoning="Found Purple Tea. Stock: 6 units.",
            grounded_facts=["product", "stock"],
            agent_role="Catalog grounding",
            step_type="ground",
        )

        assert result["grounded_facts"] == ["product", "stock"]

    def test_get_decision_log(self):
        """Test retrieving the decision log."""
        # Log a decision
        log_decision(
            agent_name="Test Agent",
            reasoning="Test reasoning.",
        )

        decisions = get_decision_log()
        assert len(decisions) >= 1

        # Find our decision
        test_decision = next(
            (d for d in decisions if d.agent_name == "Test Agent"),
            None,
        )
        assert test_decision is not None

    def test_clear_decision_log(self):
        """Test clearing the decision log."""
        # Log something
        log_decision(agent_name="Test", reasoning="Test")

        # Clear
        clear_decision_log()

        # Should be empty
        decisions = get_decision_log()
        assert len(decisions) == 0

    def test_log_multiple_decisions(self):
        """Test logging multiple decisions in sequence."""
        clear_decision_log()

        log_decision(agent_name="Agent 1", reasoning="Step 1")
        log_decision(agent_name="Agent 2", reasoning="Step 2")
        log_decision(agent_name="Agent 1", reasoning="Step 3")

        decisions = get_decision_log()
        assert len(decisions) == 3

        # Check order
        assert decisions[0].agent_name == "Agent 1"
        assert decisions[1].agent_name == "Agent 2"
        assert decisions[2].agent_name == "Agent 1"
