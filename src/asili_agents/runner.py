"""ADK Runner integration for executing agents.

This module provides the actual agent execution layer using Google ADK's
InMemoryRunner. It replaces the scripted demo with real LLM agent runs.
"""

import os
import re
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
from asili_agents.data.repository import CatalogRepository, set_catalog_repository
from asili_agents.tools import cost
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
    *,
    repository: CatalogRepository | None = None,
    use_mcp: bool | None = None,
) -> InMemoryRunner:
    """Create an ADK InMemoryRunner with the operations manager agent.

    Args:
        seller: The seller entity.
        products: List of products for the catalog.
        policy: Business policy settings.
        repository: Active catalog repository. When provided (e.g. a
            ``MongoCatalogRepository``), the deterministic pricing tool reads
            from it; otherwise a static repository is built from ``products``.
        use_mcp: Route the specialist agents' catalog reads through the MongoDB
            MCP server (defaults to settings.use_mcp).

    Returns:
        Configured InMemoryRunner ready to execute.
    """
    # Configure API credentials
    _configure_api_credentials()

    # Initialize the data source the tools read from.
    if repository is not None:
        set_catalog_repository(repository)
    else:
        set_product_store(products)
        set_pricing_context(products, policy)
    clear_decision_log()

    # Create the multi-agent system
    agent = create_operations_manager(
        seller_name=seller.name,
        brand_voice=seller.brand_voice,
        lane=seller.lane,
        margin_floor=policy.margin_floor,
        use_mcp=use_mcp,
        seller_category=seller.category,
    )

    return InMemoryRunner(agent=agent)


def create_baseline_runner(
    seller: Seller,
    products: list[Product],
) -> InMemoryRunner:
    """Create an ADK InMemoryRunner with the baseline (single) agent.

    The baseline is a *fair* control: it gets the full catalog snapshot (stock,
    cost, the 45% rule) in its prompt and a careful instruction to answer
    accurately. It has no tools — no live grounding and no deterministic pricing
    engine — so the team-vs-baseline delta measures architecture, not a data
    handicap.

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
        seller_category=seller.category,
    )

    return InMemoryRunner(agent=agent)


def _new_ids(user_id: str | None, session_id: str | None) -> tuple[str, str]:
    return (
        user_id or f"user_{uuid.uuid4().hex[:8]}",
        session_id or f"session_{uuid.uuid4().hex[:8]}",
    )


def _ingest_event(
    event: Event,
    steps: list[AgentStep],
    raw_events: list[dict[str, Any]],
) -> str | None:
    """Record an event's raw form + tool-call steps; return draft text if final."""
    raw_events.append(_event_to_dict(event))

    # Best-effort cost metering: when the model returns usage metadata, price the
    # real tokens against the tier the authoring agent runs on. Fully guarded so a
    # missing/renamed attribute (ADK version drift) can never break a run.
    usage = getattr(event, "usage_metadata", None)
    if usage is not None:
        inp = getattr(usage, "prompt_token_count", 0) or 0
        out = getattr(usage, "candidates_token_count", 0) or 0
        if inp or out:
            cost.record_call(cost.tier_for_agent(event.author), int(inp), int(out))

    tool_calls = event.get_function_calls()
    if tool_calls:
        for fc in tool_calls:
            steps.append(
                AgentStep(
                    id=f"step_{uuid.uuid4().hex[:8]}",
                    agent_name=event.author or "unknown",
                    agent_role="tool_call",
                    step_type="tool",
                    reasoning_trace=f"Calling {fc.name}",
                    tool_calls=[{"name": fc.name, "args": dict(fc.args) if fc.args else {}}],
                )
            )

    draft: str | None = None
    if event.is_final_response() and event.content:
        for part in event.content.parts or []:
            if part.text:
                draft = part.text
    return draft


def _finalize_run(
    steps: list[AgentStep],
    draft: str | None,
    raw_events: list[dict[str, Any]],
) -> RunResult:
    """Append decision-log steps + grounded facts/sources into a successful RunResult."""
    draft_sources: list[str] = []
    for decision in get_decision_log():
        if decision.grounded_facts:
            draft_sources.extend(decision.grounded_facts)
        steps.append(
            AgentStep(
                id=str(decision.id),
                agent_name=decision.agent_name,
                agent_role=decision.agent_role,
                step_type=decision.step_type,
                reasoning_trace=decision.reasoning_trace,
                grounded_facts=decision.grounded_facts,
                timestamp=decision.timestamp,
            )
        )

    return RunResult(
        steps=steps,
        draft=draft,
        draft_sources=list(set(draft_sources)),
        facts=_collect_grounded_facts(raw_events),
        raw_events=raw_events,
        success=True,
    )


def _error_result(
    steps: list[AgentStep], raw_events: list[dict[str, Any]], exc: Exception
) -> RunResult:
    return RunResult(
        steps=steps,
        draft=None,
        draft_sources=[],
        facts={},
        raw_events=raw_events,
        success=False,
        error=str(exc),
    )


def run_agent(
    runner: InMemoryRunner,
    message: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> RunResult:
    """Execute the multi-agent team synchronously (local dev / tests).

    For the deployed server, use :func:`run_agent_async`: the MongoDB MCP stdio
    session must share the request's event loop, which this sync path (which
    wraps ``asyncio.run()``) cannot provide.
    """
    import asyncio

    user_id, session_id = _new_ids(user_id, session_id)

    async def _create() -> Any:
        return await runner.session_service.create_session(
            app_name=runner.app_name, user_id=user_id, session_id=session_id
        )

    asyncio.run(_create())
    user_message = types.Content(role="user", parts=[types.Part(text=message)])

    steps: list[AgentStep] = []
    raw_events: list[dict[str, Any]] = []
    draft: str | None = None
    try:
        for event in runner.run(user_id=user_id, session_id=session_id, new_message=user_message):
            d = _ingest_event(event, steps, raw_events)
            if d is not None:
                draft = d
        return _finalize_run(steps, draft, raw_events)
    except Exception as e:
        return _error_result(steps, raw_events, e)


async def run_agent_async(
    runner: InMemoryRunner,
    message: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> RunResult:
    """Execute the multi-agent team on the caller's event loop (MCP-safe).

    Used by the FastAPI endpoints so the MongoDB MCP server's stdio session lives
    in the same loop that drives the agent. The sync runner under a worker thread
    deadlocks the MCP subprocess.
    """
    last_exc: Exception | None = None
    # Retry once. An unregistered/phantom tool call (the model reaching for a
    # tool the prompt named but that isn't registered) or a transient MCP hiccup
    # is non-deterministic, so a single fresh re-invocation usually recovers the
    # run rather than surfacing a hard failure on, e.g., the live demo path.
    for attempt in range(2):
        uid, sid = _new_ids(user_id, session_id if attempt == 0 else None)
        if attempt:
            # Discard the failed attempt's partial decision log so it can't
            # contaminate the retry's grounded facts / sources.
            clear_decision_log()
        await runner.session_service.create_session(
            app_name=runner.app_name, user_id=uid, session_id=sid
        )
        user_message = types.Content(role="user", parts=[types.Part(text=message)])
        steps: list[AgentStep] = []
        raw_events: list[dict[str, Any]] = []
        draft: str | None = None
        try:
            async for event in runner.run_async(
                user_id=uid, session_id=sid, new_message=user_message
            ):
                d = _ingest_event(event, steps, raw_events)
                if d is not None:
                    draft = d
            return _finalize_run(steps, draft, raw_events)
        except Exception as e:
            last_exc = e
    return _error_result([], [], last_exc or RuntimeError("agent run failed"))


def _extract_baseline_text(event: Event, raw_events: list[dict[str, Any]]) -> str | None:
    raw_events.append(_event_to_dict(event))
    if event.is_final_response() and event.content:
        for part in event.content.parts or []:
            if part.text:
                return part.text
    return None


def run_baseline(
    runner: InMemoryRunner,
    message: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Execute the baseline agent synchronously (local dev / tests)."""
    import asyncio

    user_id, session_id = _new_ids(user_id, session_id)

    async def _create() -> Any:
        return await runner.session_service.create_session(
            app_name=runner.app_name, user_id=user_id, session_id=session_id
        )

    asyncio.run(_create())
    user_message = types.Content(role="user", parts=[types.Part(text=message)])

    response_text: str | None = None
    raw_events: list[dict[str, Any]] = []
    for event in runner.run(user_id=user_id, session_id=session_id, new_message=user_message):
        text = _extract_baseline_text(event, raw_events)
        if text is not None:
            response_text = text
    return response_text, raw_events


async def run_baseline_async(
    runner: InMemoryRunner,
    message: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Execute the baseline agent on the caller's event loop (MCP-safe)."""
    user_id, session_id = _new_ids(user_id, session_id)
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
    user_message = types.Content(role="user", parts=[types.Part(text=message)])

    response_text: str | None = None
    raw_events: list[dict[str, Any]] = []
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=user_message
    ):
        text = _extract_baseline_text(event, raw_events)
        if text is not None:
            response_text = text
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
                        {
                            "name": p.function_call.name,
                            "args": dict(p.function_call.args) if p.function_call.args else {},
                        }
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


def _collect_grounded_facts(raw_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Collect grounded business facts for the UI facts panel.

    Prefer STRUCTURED tool outputs — the typed dicts the catalog/pricing tools
    actually returned (captured as ``function_response`` parts in ``raw_events``)
    — so facts are read from real values, not parsed out of free-text reasoning.
    Only fall back to scraping the decision-log prose for a value the structured
    path didn't supply (e.g. the MCP grounding path, whose tool results are raw
    Atlas documents rather than the in-process tool dicts).
    """
    facts: dict[str, Any] = {}

    # 1) Structured: read the tools' own function responses.
    for event in raw_events or []:
        for part in (event.get("content") or {}).get("parts") or []:
            fr = part.get("function_response")
            if not fr:
                continue
            name = fr.get("name")
            resp = fr.get("response")
            # ADK may wrap the tool's return under a "result" key.
            if isinstance(resp, dict) and isinstance(resp.get("result"), dict):
                resp = resp["result"]
            if not isinstance(resp, dict):
                continue
            if name == "check_stock" and resp.get("quantity") is not None:
                facts["stock_quantity"] = resp["quantity"]
                if resp.get("level"):
                    facts["stock_level"] = resp["level"]
            elif name == "compute_bundle_price" and resp.get("bundle_price") is not None:
                facts["bundle_price"] = resp["bundle_price"]
                if resp.get("is_margin_safe") is not None:
                    facts["is_margin_safe"] = resp["is_margin_safe"]

    # 2) Fallback: recover anything still missing from the decision-log prose.
    if "stock_quantity" not in facts or "bundle_price" not in facts:
        for decision in get_decision_log():
            trace = decision.reasoning_trace
            if "stock_quantity" not in facts and "stock" in trace.lower():
                match = re.search(r"Stock:\s*(\d+)\s*units?,\s*(\w+)", trace)
                if match:
                    facts["stock_quantity"] = int(match.group(1))
                    facts["stock_level"] = match.group(2)
            if "bundle_price" not in facts and "bundle" in trace.lower():
                match = re.search(r"\$(\d+\.?\d*)", trace)
                if match:
                    facts["bundle_price"] = float(match.group(1))

    return facts
