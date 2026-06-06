"""Run the Trust Scorecard: score the team and the baseline on every scenario.

The core (`score_system`) is pure and takes a ``reply_fn`` so it can be unit
tested without an LLM. `run_scorecard` wires the real ADK runners as the reply
functions for the live ``/api/eval`` endpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from asili_agents.data.models import Policy, Product, Seller
from asili_agents.eval.scenarios import SCENARIOS, Scenario
from asili_agents.eval.scoring import aggregate, evaluate_reply

# A reply function returns either the reply text, or a dict
# {"text": str, "retrieved": bool} so the scorer knows whether the catalog was
# actually consulted (used to distinguish "grounded" from a lucky guess).
ReplyFn = Callable[[str], Any]


def score_system(
    scenarios: list[Scenario],
    products: list[Product],
    policy: Policy | None,
    reply_fn: ReplyFn,
) -> dict[str, Any]:
    """Score one system (team or baseline) across all scenarios."""
    by_sku = {p.sku: p for p in products}
    scenario_results: list[dict[str, Any]] = []
    scores = []

    for scenario in scenarios:
        product = by_sku.get(scenario.target_sku)
        raw = reply_fn(scenario.prompt)
        if isinstance(raw, dict):
            reply = raw.get("text")
            retrieved = raw.get("retrieved")
        else:
            reply = raw
            retrieved = None
        if product is None:
            continue
        score = evaluate_reply(reply, product=product, policy=policy, retrieved=retrieved)
        scores.append(score)
        scenario_results.append(
            {
                "id": scenario.id,
                "prompt": scenario.prompt,
                "kind": scenario.kind,
                "passed": score.passed,
                "grounded": score.grounded,
                "retrieved": retrieved,
                "issues": score.issues,
                "reply": reply,
            }
        )

    rates = aggregate(scores)
    return {**rates, "scenarios": scenario_results}


def run_scorecard(
    products: list[Product],
    policy: Policy | None,
    *,
    team_reply_fn: ReplyFn,
    baseline_reply_fn: ReplyFn,
    scenarios: list[Scenario] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run the full scorecard: team vs baseline across the scenarios."""
    selected = scenarios if scenarios is not None else SCENARIOS
    if limit is not None:
        selected = selected[:limit]

    team = score_system(selected, products, policy, team_reply_fn)
    baseline = score_system(selected, products, policy, baseline_reply_fn)
    return {"team": team, "baseline": baseline, "summary": _summary(team, baseline)}


def _summary(team: dict[str, Any], baseline: dict[str, Any]) -> str:
    def line(label: str, data: dict[str, Any]) -> str:
        return (
            f"{label}: {round(data['grounded_rate'] * 100)}% grounded, "
            f"{round(data['margin_safe_rate'] * 100)}% margin-safe, "
            f"{round(data['hallucination_rate'] * 100)}% hallucination"
        )

    return f"{line('Asili team', team)}. {line('Baseline', baseline)}."


def build_live_reply_fns(
    seller: Seller,
    products: list[Product],
    policy: Policy,
    *,
    repository: Any | None = None,
    use_mcp: bool | None = None,
) -> tuple[ReplyFn, ReplyFn]:
    """Build reply functions backed by the real ADK runners (for /api/eval).

    Each call spins up a fresh runner so scenarios don't share conversation
    state. This issues real Gemini calls, so it requires API credentials and is
    intended for the deployed/graded path, not CI. When ``repository``/``use_mcp``
    are supplied, the team reads through MongoDB + the MongoDB MCP server.
    """
    from asili_agents.runner import (
        create_baseline_runner,
        create_runner,
        run_agent,
        run_baseline,
    )

    # Precise set of read tools (in-process + MongoDB MCP). retrieved is based on
    # an ACTUAL call to one of these, not a substring of the reasoning trace.
    read_tools = {
        "catalog_search",
        "check_stock",
        "get_costs",
        "find",
        "aggregate",
        "count",
        "list-collections",
        "collection-schema",
    }

    def team_reply(prompt: str) -> dict[str, Any]:
        runner = create_runner(seller, products, policy, repository=repository, use_mcp=use_mcp)
        result = run_agent(runner, prompt)
        # The team retrieved iff it actually invoked a catalog/stock read tool
        # (or logged grounded facts) — not merely mentioned one in prose.
        retrieved = any(
            bool(step.grounded_facts)
            or any((tc.get("name") in read_tools) for tc in (step.tool_calls or []))
            for step in result.steps
        )
        return {"text": result.draft, "retrieved": retrieved}

    def baseline_reply(prompt: str) -> dict[str, Any]:
        runner = create_baseline_runner(seller, products)
        text, _ = run_baseline(runner, prompt)
        # The baseline has no tools, so it can never retrieve.
        return {"text": text, "retrieved": False}

    return team_reply, baseline_reply


# ---------------------------------------------------------------------------
# Async variants (used by the FastAPI /api/eval endpoint so the MongoDB MCP
# stdio session shares the request's event loop).
# ---------------------------------------------------------------------------

_READ_TOOLS = {
    "catalog_search",
    "check_stock",
    "get_costs",
    "find",
    "aggregate",
    "count",
    "list-collections",
    "collection-schema",
}


async def score_system_async(
    scenarios: list[Scenario],
    products: list[Product],
    policy: Policy | None,
    reply_fn: Any,
) -> dict[str, Any]:
    """Async counterpart of :func:`score_system` (awaits each reply)."""
    by_sku = {p.sku: p for p in products}
    scenario_results: list[dict[str, Any]] = []
    scores = []

    for scenario in scenarios:
        product = by_sku.get(scenario.target_sku)
        raw = await reply_fn(scenario.prompt)
        reply = raw.get("text") if isinstance(raw, dict) else raw
        retrieved = raw.get("retrieved") if isinstance(raw, dict) else None
        if product is None:
            continue
        score = evaluate_reply(reply, product=product, policy=policy, retrieved=retrieved)
        scores.append(score)
        scenario_results.append(
            {
                "id": scenario.id,
                "prompt": scenario.prompt,
                "kind": scenario.kind,
                "passed": score.passed,
                "grounded": score.grounded,
                "retrieved": retrieved,
                "issues": score.issues,
                "reply": reply,
            }
        )

    return {**aggregate(scores), "scenarios": scenario_results}


async def run_scorecard_async(
    products: list[Product],
    policy: Policy | None,
    *,
    team_reply_fn: Any,
    baseline_reply_fn: Any,
    scenarios: list[Scenario] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Async counterpart of :func:`run_scorecard`."""
    selected = scenarios if scenarios is not None else SCENARIOS
    if limit is not None:
        selected = selected[:limit]
    team = await score_system_async(selected, products, policy, team_reply_fn)
    baseline = await score_system_async(selected, products, policy, baseline_reply_fn)
    return {"team": team, "baseline": baseline, "summary": _summary(team, baseline)}


def build_live_reply_fns_async(
    seller: Seller,
    products: list[Product],
    policy: Policy,
    *,
    repository: Any | None = None,
    use_mcp: bool | None = None,
) -> tuple[Any, Any]:
    """Async reply functions backed by the async ADK runners (MCP-safe)."""
    from asili_agents.runner import (
        create_baseline_runner,
        create_runner,
        run_agent_async,
        run_baseline_async,
    )

    async def team_reply(prompt: str) -> dict[str, Any]:
        runner = create_runner(seller, products, policy, repository=repository, use_mcp=use_mcp)
        result = await run_agent_async(runner, prompt)
        retrieved = any(
            bool(step.grounded_facts)
            or any((tc.get("name") in _READ_TOOLS) for tc in (step.tool_calls or []))
            for step in result.steps
        )
        return {"text": result.draft, "retrieved": retrieved}

    async def baseline_reply(prompt: str) -> dict[str, Any]:
        runner = create_baseline_runner(seller, products)
        text, _ = await run_baseline_async(runner, prompt)
        return {"text": text, "retrieved": False}

    return team_reply, baseline_reply
