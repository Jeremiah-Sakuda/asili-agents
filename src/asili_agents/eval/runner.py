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

ReplyFn = Callable[[str], str | None]


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
        reply = reply_fn(scenario.prompt)
        if product is None:
            continue
        score = evaluate_reply(reply, product=product, policy=policy)
        scores.append(score)
        scenario_results.append(
            {
                "id": scenario.id,
                "prompt": scenario.prompt,
                "kind": scenario.kind,
                "passed": score.passed,
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

    def team_reply(prompt: str) -> str | None:
        runner = create_runner(seller, products, policy, repository=repository, use_mcp=use_mcp)
        result = run_agent(runner, prompt)
        return result.draft

    def baseline_reply(prompt: str) -> str | None:
        runner = create_baseline_runner(seller, products)
        text, _ = run_baseline(runner, prompt)
        return text

    return team_reply, baseline_reply
