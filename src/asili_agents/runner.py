"""ADK Runner integration for executing agents.

This module provides the actual agent execution layer using Google ADK's
InMemoryRunner. It replaces the scripted demo with real LLM agent runs.
"""

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from google.adk.runners import Event, InMemoryRunner
from google.genai import types

from asili_agents.agents.baseline import create_baseline_agent, generate_catalog_dump_from_products
from asili_agents.agents.operations_manager import create_operations_manager
from asili_agents.config import get_settings
from asili_agents.data.models import Policy, Product, Seller
from asili_agents.tools.catalog import set_product_store
from asili_agents.tools.logging import clear_decision_log, get_decision_log
from asili_agents.tools.pricing import set_pricing_context


def _configure_api_credentials() -> None:
    """Configure Google API credentials from settings.

    Supports two authentication methods:
    1. GOOGLE_API_KEY - Direct Gemini API access (simpler for local dev)
    2. GOOGLE_APPLICATION_CREDENTIALS - GCP service account (Vertex AI)

    ADK will use whichever is available.
    """
    settings = get_settings()

    # Set API key if provided
    if settings.google_api_key and not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = settings.google_api_key

    # Set service account credentials if provided
    if settings.google_application_credentials and not os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS"
    ):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials


@dataclass
class AgentStep:
    """A step in the agent execution trace."""

    id: str
    agent_name: str
    agent_role: str
    step_type: str
    reasoning_trace: str
    grounded_facts: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RunResult:
    """Result from running the agent system."""

    steps: list[AgentStep]
    draft: str | None
    draft_sources: list[str]
    facts: dict[str, Any]
    raw_events: list[dict[str, Any]]
    success: bool
    error: str | None = None


def create_runner(
    seller: Seller,
    products: list[Product],
    policy: Policy,
) -> InMemoryRunner:
    """Create an ADK InMemoryRunner with the operations manager agent.

    Args:
        seller: The seller entity.
        products: List of products for the catalog.
        policy: Business policy settings.

    Returns:
        Configured InMemoryRunner ready to execute.
    """
    # Configure API credentials
    _configure_api_credentials()

    # Initialize tool stores
    set_product_store(products)
    set_pricing_context(products, policy)
    clear_decision_log()

    # Create the multi-agent system
    agent = create_operations_manager(
        seller_name=seller.name,
        brand_voice=seller.brand_voice,
        lane=seller.lane,
        margin_floor=policy.margin_floor,
    )

    return InMemoryRunner(agent=agent)


def create_baseline_runner(
    seller: Seller,
    products: list[Product],
) -> InMemoryRunner:
    """Create an ADK InMemoryRunner with the baseline (single) agent.

    The baseline agent has no tools - it relies entirely on the catalog
    dump in its context. This is designed to fail in predictable ways.

    Args:
        seller: The seller entity.
        products: List of products for catalog dump.

    Returns:
        Configured InMemoryRunner for baseline comparison.
    """
    # Configure API credentials
    _configure_api_credentials()

    catalog_dump = generate_catalog_dump_from_products(products)

    agent = create_baseline_agent(
        seller_name=seller.name,
        catalog_dump=catalog_dump,
    )

    return InMemoryRunner(agent=agent)


def run_agent(
    runner: InMemoryRunner,
    message: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> RunResult:
    """Execute the agent on a customer message.

    Args:
        runner: The configured InMemoryRunner.
        message: The customer message to process.
        user_id: Optional user identifier (defaults to generated).
        session_id: Optional session identifier (defaults to generated).

    Returns:
        RunResult with steps, draft, facts, and raw events.
    """
    import asyncio

    user_id = user_id or f"user_{uuid.uuid4().hex[:8]}"
    session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"

    # Create session first (required by InMemoryRunner)
    async def create_session():
        return await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id,
        )

    asyncio.run(create_session())

    # Create the user message
    user_message = types.Content(
        role="user",
        parts=[types.Part(text=message)],
    )

    steps: list[AgentStep] = []
    raw_events: list[dict[str, Any]] = []
    draft: str | None = None
    draft_sources: list[str] = []

    try:
        # Run the agent and collect events
        for event in runner.run(
            user_id=user_id,
            session_id=session_id,
            new_message=user_message,
        ):
            event_data = _event_to_dict(event)
            raw_events.append(event_data)

            # Track tool calls
            tool_calls = event.get_function_calls()
            if tool_calls:
                for fc in tool_calls:
                    step = AgentStep(
                        id=f"step_{uuid.uuid4().hex[:8]}",
                        agent_name=event.author or "unknown",
                        agent_role="tool_call",
                        step_type="tool",
                        reasoning_trace=f"Calling {fc.name}",
                        tool_calls=[{"name": fc.name, "args": dict(fc.args) if fc.args else {}}],
                    )
                    steps.append(step)

            # Capture final response
            if event.is_final_response() and event.content:
                for part in event.content.parts or []:
                    if part.text:
                        draft = part.text
                        # Extract sources from the decision log
                        decisions = get_decision_log()
                        for d in decisions:
                            if d.grounded_facts:
                                draft_sources.extend(d.grounded_facts)

        # Convert decision log to steps
        for decision in get_decision_log():
            step = AgentStep(
                id=str(decision.id),
                agent_name=decision.agent_name,
                agent_role=decision.agent_role,
                step_type=decision.step_type,
                reasoning_trace=decision.reasoning_trace,
                grounded_facts=decision.grounded_facts,
                timestamp=decision.timestamp,
            )
            steps.append(step)

        # Collect grounded facts
        facts = _collect_grounded_facts()

        return RunResult(
            steps=steps,
            draft=draft,
            draft_sources=list(set(draft_sources)),
            facts=facts,
            raw_events=raw_events,
            success=True,
        )

    except Exception as e:
        return RunResult(
            steps=steps,
            draft=None,
            draft_sources=[],
            facts={},
            raw_events=raw_events,
            success=False,
            error=str(e),
        )


def run_baseline(
    runner: InMemoryRunner,
    message: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Execute the baseline agent on a customer message.

    Args:
        runner: The configured baseline InMemoryRunner.
        message: The customer message to process.
        user_id: Optional user identifier.
        session_id: Optional session identifier.

    Returns:
        Tuple of (response_text, raw_events).
    """
    import asyncio

    user_id = user_id or f"user_{uuid.uuid4().hex[:8]}"
    session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"

    # Create session first (required by InMemoryRunner)
    async def create_session():
        return await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id,
        )

    asyncio.run(create_session())

    user_message = types.Content(
        role="user",
        parts=[types.Part(text=message)],
    )

    response_text: str | None = None
    raw_events: list[dict[str, Any]] = []

    for event in runner.run(
        user_id=user_id,
        session_id=session_id,
        new_message=user_message,
    ):
        raw_events.append(_event_to_dict(event))

        if event.is_final_response() and event.content:
            for part in event.content.parts or []:
                if part.text:
                    response_text = part.text

    return response_text, raw_events


def _event_to_dict(event: Event) -> dict[str, Any]:
    """Convert an ADK Event to a serializable dictionary."""
    result: dict[str, Any] = {
        "id": event.id,
        "author": event.author,
        "timestamp": event.timestamp,
        "partial": event.partial,
        "turn_complete": event.turn_complete,
        "is_final": event.is_final_response(),
    }

    if event.content:
        result["content"] = {
            "role": event.content.role,
            "parts": [
                {
                    "text": p.text if p.text else None,
                    "function_call": (
                        {"name": p.function_call.name, "args": dict(p.function_call.args)}
                        if p.function_call
                        else None
                    ),
                    "function_response": (
                        {"name": p.function_response.name, "response": p.function_response.response}
                        if p.function_response
                        else None
                    ),
                }
                for p in (event.content.parts or [])
            ],
        }

    if event.error_message:
        result["error"] = event.error_message

    return result


def _collect_grounded_facts() -> dict[str, Any]:
    """Collect grounded business facts from the decision log."""
    facts: dict[str, Any] = {}

    for decision in get_decision_log():
        # Extract facts from reasoning traces
        if "stock" in decision.reasoning_trace.lower():
            # Parse stock info from trace
            import re

            match = re.search(r"Stock:\s*(\d+)\s*units?,\s*(\w+)", decision.reasoning_trace)
            if match:
                facts["stock_quantity"] = int(match.group(1))
                facts["stock_level"] = match.group(2)

        if "bundle" in decision.reasoning_trace.lower():
            # Parse bundle price from trace
            import re

            match = re.search(r"\$(\d+\.?\d*)", decision.reasoning_trace)
            if match:
                facts["bundle_price"] = float(match.group(1))

    return facts
