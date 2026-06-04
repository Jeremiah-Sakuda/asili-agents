"""Agent definitions for the Asili Operations Team.

This module provides the three-agent system:
1. Operations Manager - Root orchestrator
2. Messaging Agent - Catalog grounding and customer communication
3. Pricing Agent - Margin-safe bundle pricing

Plus the monolithic baseline for comparison.
"""

from asili_agents.agents.baseline import create_baseline_agent
from asili_agents.agents.messaging import create_messaging_agent
from asili_agents.agents.operations_manager import create_operations_manager
from asili_agents.agents.pricing import create_pricing_agent

__all__ = [
    "create_messaging_agent",
    "create_pricing_agent",
    "create_operations_manager",
    "create_baseline_agent",
]
