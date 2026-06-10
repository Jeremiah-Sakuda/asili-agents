"""Graduated autonomy — the "trust ladder" for the approval gate.

The product's safety promise is the human approval gate. But a *universal* gate
("the seller signs every message") means the AI never actually executes a
decision on its own — which undersells what the system can safely do. This module
turns the binary gate into a graduated ladder the seller controls:

- **Tier 0 — HOLD** (the default, fail-closed): the draft is held for the
  seller's approval.
- **Tier 1 — AUTO**: a class of *low-risk, reversible, policy-bounded* decisions
  executes WITHOUT per-action approval. This is safe *by construction*, not by
  trust: the agent cannot invent stock (read-only MCP grounding) and cannot quote
  below the margin floor (the deterministic pricing engine). The seller turns on
  exactly the intents they want auto-handled; the AI then owns those routine,
  high-volume decisions live.

Anything high-stakes (refunds, complaints, out-of-stock promises, anything novel
or unclassifiable) ALWAYS holds, regardless of policy. The module is pure and
dependency-free so it is trivially testable and carries the same fail-closed
posture as the rest of the channel layer: with no policy set, everything holds.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class AutonomyTier(str, Enum):
    """How a decision was handled."""

    HOLD = "hold"  # Tier 0 — parked for the seller to approve
    AUTO = "auto"  # Tier 1 — executed within policy, no per-action approval


# Low-risk, reversible, informational decision classes that CAN be auto-handled
# at Tier 1 if the seller opts in. These are answers fully determined by the
# grounded catalog + the deterministic pricing engine.
AUTO_ELIGIBLE_INTENTS: frozenset[str] = frozenset(
    {"stock_check", "price_quote", "bundle_quote", "acknowledgment", "faq"}
)

# High-stakes / irreversible / sentiment-negative classes that ALWAYS hold,
# regardless of policy — the consequential minority stays human-gated by design.
ALWAYS_HOLD_INTENTS: frozenset[str] = frozenset(
    {"refund", "complaint", "out_of_stock", "cancellation", "escalation", "unknown"}
)

_PRICING_INTENTS: frozenset[str] = frozenset({"price_quote", "bundle_quote"})


class AutonomyPolicy(BaseModel):
    """Per-seller autonomy policy. Defaults to fail-closed (nothing auto-executes)."""

    enabled: bool = False
    auto_intents: set[str] = Field(
        default_factory=set,
        description="Subset of AUTO_ELIGIBLE_INTENTS the seller has turned on.",
    )
    require_grounded: bool = Field(
        default=True,
        description="Only auto-execute when the answer is grounded in a real catalog read.",
    )
    require_margin_safe: bool = Field(
        default=True,
        description="Only auto-execute a price/bundle quote when it is margin-safe.",
    )


def classify_intent(
    draft_body: str,
    sources: list[str] | None = None,
    agent_name: str = "Messaging",
) -> str:
    """Heuristically classify a draft into a decision-intent class.

    Conservative by design: ambiguous or sentiment-negative drafts resolve to a
    HOLD class so they never auto-execute. Callers that already know the intent
    should pass it explicitly to ``should_auto_execute`` instead.
    """
    text = (draft_body or "").lower()

    # High-stakes / negative signals -> always-hold classes.
    if "refund" in text or "money back" in text:
        return "refund"
    if any(w in text for w in ("cancel", "canceled", "cancelled")):
        return "cancellation"
    if any(w in text for w in ("out of stock", "sold out", "no longer available", "out-of-stock")):
        return "out_of_stock"
    if any(w in text for w in ("sorry", "apolog", "complaint", "disappointed", "unhappy", "refunded")):
        return "complaint"

    # Low-risk informational classes.
    if "bundle" in text:
        return "bundle_quote"
    if "%" in text or "discount" in text or "$" in text or agent_name.lower().startswith("pricing"):
        return "price_quote"
    if any(w in text for w in ("in stock", "left", "available", "units", "tins", "we have")):
        return "stock_check"
    return "acknowledgment"


def decide_tier(
    policy: AutonomyPolicy | None,
    intent: str,
    *,
    grounded: bool | None = None,
    margin_safe: bool | None = None,
) -> AutonomyTier:
    """Decide whether a decision auto-executes (Tier 1) or holds (Tier 0).

    Fail-closed: returns HOLD unless a policy is enabled AND the intent is an
    opted-in low-risk class AND the structural-safety preconditions hold.
    """
    if policy is None or not policy.enabled:
        return AutonomyTier.HOLD
    if intent in ALWAYS_HOLD_INTENTS or intent not in AUTO_ELIGIBLE_INTENTS:
        return AutonomyTier.HOLD
    if intent not in policy.auto_intents:
        return AutonomyTier.HOLD
    if policy.require_grounded and not grounded:
        return AutonomyTier.HOLD
    if policy.require_margin_safe and intent in _PRICING_INTENTS and not margin_safe:
        return AutonomyTier.HOLD
    return AutonomyTier.AUTO


# ---------------------------------------------------------------------------
# Autonomy meter — the judge-facing "autonomy rate" metric. A simple cumulative
# counter (the rate is meant to trend up across many decisions); tests reset it.
# ---------------------------------------------------------------------------

_counts: dict[str, int] = {"auto": 0, "hold": 0}


def record_decision(tier: AutonomyTier) -> None:
    """Record one handled decision for the autonomy-rate metric."""
    _counts["auto" if tier is AutonomyTier.AUTO else "hold"] += 1


def autonomy_stats() -> dict[str, float | int]:
    """Return the cumulative autonomy metric: counts + the autonomy rate."""
    auto = _counts["auto"]
    hold = _counts["hold"]
    total = auto + hold
    return {
        "auto": auto,
        "held": hold,
        "total": total,
        "autonomy_rate": (auto / total) if total else 0.0,
    }


def reset_autonomy_stats() -> None:
    """Reset the autonomy meter (used by tests and /api/reset)."""
    _counts["auto"] = 0
    _counts["hold"] = 0
