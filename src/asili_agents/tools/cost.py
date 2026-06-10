"""Cost meter — the substrate for the "cost-per-seller-served" viability metric.

Model tiering routes routine turns (intent classification, in-stock answers,
acknowledgments, tool selection) to a cheaper model and reserves the larger
model for complex composition; the deterministic pricing core costs zero LLM
tokens. This module prices each model call by tier and accumulates spend per
seller, so the cost-per-seller curve can be populated from real production usage
and shown to trend down as routine volume grows — the cheaper tiers plus the
zero-cost deterministic core absorb the marginal message while the subscription
price is flat, so gross margin expands with scale.

Pure + dependency-free so it is trivially testable. Token capture in the runner
is best-effort and guarded: when the model returns usage metadata we price the
real tokens; when it doesn't, nothing is recorded (we never fabricate numbers).
"""

from __future__ import annotations

from contextvars import ContextVar
from enum import Enum


class ModelTier(str, Enum):
    """Which model tier served a turn."""

    ROUTINE = "routine"  # cheap/fast model — the high-volume routine turns
    COMPLEX = "complex"  # larger model — composition / orchestration


# USD per 1M tokens, (input, output). Approximate Gemini 2.5 list pricing. The
# load-bearing property is the RELATIVE ordering — routine is strictly cheaper
# than complex — which is what makes "route routine volume to the cheap tier"
# bend the cost-per-message curve down.
_PRICE_PER_M: dict[ModelTier, tuple[float, float]] = {
    ModelTier.ROUTINE: (0.10, 0.40),  # flash-lite class
    ModelTier.COMPLEX: (0.30, 2.50),  # flash class
}

# Agents whose turns are routine (cheap tier). The Operations Manager
# (composition/orchestration) and the baseline run on the complex tier.
_ROUTINE_AGENTS: frozenset[str] = frozenset({"messaging_agent", "pricing_agent"})


def estimate_cost(tier: ModelTier, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost of one model call at a tier."""
    inp, out = _PRICE_PER_M[tier]
    return (input_tokens / 1_000_000) * inp + (output_tokens / 1_000_000) * out


def tier_for_agent(author: str | None) -> ModelTier:
    """Map an event's author (agent name) to the model tier it runs on."""
    return ModelTier.ROUTINE if (author or "").lower() in _ROUTINE_AGENTS else ModelTier.COMPLEX


# Current-seller attribution for per-seller cost. Optional: defaults to a shared
# bucket when the caller hasn't set a seller (the metric is still valid in
# aggregate + per-tier).
_current_seller: ContextVar[str] = ContextVar("cost_current_seller", default="_default")


def set_current_seller(seller_id: str | None) -> None:
    """Attribute subsequent recorded cost to this seller (per-seller curve)."""
    _current_seller.set(seller_id or "_default")


# Per-seller accumulating meter.
_spend: dict[str, dict[str, float]] = {}


def record_call(
    tier: ModelTier,
    input_tokens: int,
    output_tokens: int,
    seller_id: str | None = None,
) -> float:
    """Record one priced model call against a seller; returns its cost."""
    cost = estimate_cost(tier, input_tokens, output_tokens)
    key = seller_id or _current_seller.get()
    s = _spend.setdefault(
        key, {"cost": 0.0, "input_tokens": 0.0, "output_tokens": 0.0, "calls": 0.0}
    )
    s["cost"] += cost
    s["input_tokens"] += input_tokens
    s["output_tokens"] += output_tokens
    s["calls"] += 1
    return cost


def cost_stats(seller_id: str | None = None) -> dict[str, float | dict[str, dict[str, float]]]:
    """Cost metric. With a seller_id: that seller's totals + cost-per-call.
    Without: aggregate totals + a per-seller breakdown for the cost curve.
    """
    if seller_id is not None:
        s = _spend.get(
            seller_id, {"cost": 0.0, "calls": 0.0, "input_tokens": 0.0, "output_tokens": 0.0}
        )
        calls = s["calls"]
        return {
            "seller_id_cost": round(s["cost"], 6),
            "calls": calls,
            "cost_per_call": round(s["cost"] / calls, 6) if calls else 0.0,
        }
    total_cost = sum(s["cost"] for s in _spend.values())
    total_calls = sum(s["calls"] for s in _spend.values())
    return {
        "total_cost": round(total_cost, 6),
        "total_calls": total_calls,
        "cost_per_call": round(total_cost / total_calls, 6) if total_calls else 0.0,
        "by_seller": {
            k: {"cost": round(v["cost"], 6), "calls": v["calls"]} for k, v in _spend.items()
        },
    }


def reset_cost() -> None:
    """Reset the cost meter (used by tests and /api/reset)."""
    _spend.clear()
    _current_seller.set("_default")
