"""Tests for agent creation and execution.

These tests verify that:
1. Agents can be created with the correct structure
2. The runner infrastructure works
3. Integration tests (when credentials available) verify real execution
"""

import os

import pytest

from asili_agents.agents.baseline import create_baseline_agent, generate_catalog_dump_from_products
from asili_agents.agents.messaging import create_messaging_agent
from asili_agents.agents.operations_manager import create_operations_manager
from asili_agents.agents.pricing import create_pricing_agent
from asili_agents.data.seed import get_demo_seller
from asili_agents.runner import create_baseline_runner, create_runner


class TestAgentCreation:
    """Test that agents can be created with correct structure."""

    def test_create_operations_manager(self):
        """Operations manager should have sub-agents and tools."""
        agent = create_operations_manager()

        assert agent.name == "operations_manager"
        assert agent.sub_agents is not None
        assert len(agent.sub_agents) == 2  # messaging and pricing
        assert agent.tools is not None
        assert len(agent.tools) == 2  # log_decision and send_for_approval

    def test_create_messaging_agent(self):
        """Messaging agent should have catalog tools."""
        agent = create_messaging_agent()

        assert agent.name == "messaging_agent"
        assert agent.tools is not None
        # Should have catalog_search, check_stock, and log_decision
        tool_names = [t.__name__ if hasattr(t, "__name__") else str(t) for t in agent.tools]
        assert len(tool_names) == 3

    def test_create_pricing_agent(self):
        """Pricing agent should have pricing tools."""
        agent = create_pricing_agent()

        assert agent.name == "pricing_agent"
        assert agent.tools is not None
        # Should have get_costs, compute_bundle_price, and log_decision
        tool_names = [t.__name__ if hasattr(t, "__name__") else str(t) for t in agent.tools]
        assert len(tool_names) == 3

    def test_create_baseline_agent(self):
        """Baseline agent should have no tools."""
        agent = create_baseline_agent()

        assert agent.name == "baseline_agent"
        assert agent.tools is not None
        assert len(agent.tools) == 0  # Intentionally no tools

    def test_baseline_catalog_dump(self):
        """Catalog dump should contain product info."""
        _, products, _ = get_demo_seller()
        dump = generate_catalog_dump_from_products(products)

        assert "Purple Tea" in dump
        assert "$18.00" in dump
        assert "Bundle Policy" in dump


class TestRunnerCreation:
    """Test that runners can be created."""

    def test_create_ops_runner(self):
        """Should create a runner with the operations manager."""
        seller, products, policy = get_demo_seller()
        runner = create_runner(seller, products, policy)

        assert runner is not None
        assert runner.agent is not None
        assert runner.agent.name == "operations_manager"

    def test_create_baseline_runner(self):
        """Should create a runner with the baseline agent."""
        seller, products, _ = get_demo_seller()
        runner = create_baseline_runner(seller, products)

        assert runner is not None
        assert runner.agent is not None
        assert runner.agent.name == "baseline_agent"


# Integration tests - require GOOGLE_API_KEY
@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set - skipping integration test",
)
class TestAgentExecution:
    """Integration tests that run actual agents.

    These tests require GOOGLE_API_KEY to be set.
    Run with: GOOGLE_API_KEY=your-key pytest tests/test_agents.py -v
    """

    def test_run_operations_manager(self):
        """Smoke test: run the operations manager on demo message."""
        from asili_agents.runner import run_agent
        from asili_agents.tools.logging import clear_decision_log, get_decision_log

        seller, products, policy = get_demo_seller()
        runner = create_runner(seller, products, policy)
        clear_decision_log()

        # Run on the demo customer message
        result = run_agent(
            runner,
            "Do you have the purple tea in stock? Can you do a bundle?",
        )

        # Should succeed
        assert result.success, f"Agent failed: {result.error}"

        # Should have captured events
        assert len(result.raw_events) > 0

        # Should have a draft response
        assert result.draft is not None
        assert len(result.draft) > 0

        # Decision log may have entries from tool calls
        # (The exact number depends on agent behavior)
        _ = get_decision_log()  # Verify it doesn't error

        # Should have called tools (check via raw events for function calls)
        tool_calls = []
        for event in result.raw_events:
            content = event.get("content", {})
            for part in content.get("parts", []):
                if part.get("function_call"):
                    tool_calls.append(part["function_call"]["name"])

        # Expect catalog and pricing tools to be called
        assert any("stock" in tc.lower() or "catalog" in tc.lower() for tc in tool_calls), (
            f"Expected stock/catalog tool call, got: {tool_calls}"
        )

    def test_run_baseline_agent(self):
        """Smoke test: run the baseline agent on demo message."""
        from asili_agents.runner import run_baseline

        seller, products, _ = get_demo_seller()
        runner = create_baseline_runner(seller, products)

        response, events = run_baseline(
            runner,
            "Do you have the purple tea in stock? Can you do a bundle?",
        )

        # Should get a response
        assert response is not None
        assert len(response) > 0

        # Should have events
        assert len(events) > 0
