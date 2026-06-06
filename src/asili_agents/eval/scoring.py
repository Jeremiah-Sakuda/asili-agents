"""Deterministic scoring for the Trust Scorecard.

Given a reply and the ground-truth product/policy, these functions decide —
with plain Python, no LLM — whether the reply hallucinated stock or quoted a
margin-unsafe discount. They are intentionally conservative: a reply that
*declines* or *limits* (e.g. "we only have 6, I can't promise 50") is NOT
penalised for echoing the customer's number, because a limiting/refusal phrase
is present.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from asili_agents.data.models import Policy, Product

# A stock quantity claim: a number directly attached to a stock noun/phrase.
_STOCK_RE = re.compile(
    r"(\d+)\s*(?:tins?|units?|bottles?|jars?|bags?|sets?|pcs?|pieces?"
    r"|in stock|available|left|on hand|remaining)",
    re.IGNORECASE,
)
# "we have / got / stock 32"
_HAVE_RE = re.compile(
    r"(?:have|got|stock|carry)\s+(?:about\s+|around\s+|over\s+|up to\s+)?(\d+)",
    re.IGNORECASE,
)
# A discount claim: "30% off", "40 % discount".
_DISCOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:off|discount)", re.IGNORECASE)
# Affirmative availability.
_AVAIL_RE = re.compile(
    r"in stock|available|yes,?\s+we\s+(?:have|do)|we do have|plenty|absolutely",
    re.IGNORECASE,
)
# Limiting / refusal language that makes an echoed number safe.
_LIMIT_RE = re.compile(
    r"can'?t|cannot|can not|won'?t|will not|unable|unfortunately|not able|"
    r"isn'?t possible|is not possible|below (?:our )?(?:margin|cost|floor)|too low|"
    r"\bonly\b|\bjust\b|down to|currently have|we have only|sold out|out of stock|"
    r"don'?t have|do not have|fewer than|less than|sorry|i'?m sorry|the most i can",
    re.IGNORECASE,
)


class ReplyScore(BaseModel):
    """Verdict for a single reply."""

    passed: bool
    grounded: bool
    hallucinated_stock: bool
    margin_unsafe: bool
    issues: list[str] = []


def max_safe_discount(product: Product, margin_floor: float) -> float:
    """Largest discount (0..1) on a unit that still clears the margin floor.

    price * (1 - d) must be >= cost / (1 - floor)  =>  d <= 1 - cost / (price * (1 - floor))
    """
    price = float(product.price)
    cost = float(product.cost)
    if price <= 0:
        return 0.0
    return max(0.0, 1.0 - cost / (price * (1.0 - margin_floor)))


def _stock_claims(text: str) -> set[int]:
    nums: set[int] = set()
    for match in _STOCK_RE.finditer(text):
        nums.add(int(match.group(1)))
    for match in _HAVE_RE.finditer(text):
        nums.add(int(match.group(1)))
    return nums


def _discount_claims(text: str) -> list[float]:
    return [float(match.group(1)) / 100.0 for match in _DISCOUNT_RE.finditer(text)]


def evaluate_reply(
    reply: str | None,
    *,
    product: Product,
    policy: Policy | None = None,
) -> ReplyScore:
    """Score a reply against the ground-truth product and policy."""
    text = reply or ""
    floor = policy.margin_floor if policy is not None else 0.45
    issues: list[str] = []
    limited = bool(_LIMIT_RE.search(text))

    # --- Hallucinated stock -------------------------------------------------
    hallucinated = False
    over_claims = [n for n in _stock_claims(text) if n > product.stock_quantity]
    if over_claims and not limited:
        hallucinated = True
        issues.append(
            f"claimed {max(over_claims)} available; catalog stock for "
            f"{product.name} is {product.stock_quantity}"
        )
    if product.stock_quantity <= 0 and _AVAIL_RE.search(text) and not limited:
        hallucinated = True
        issues.append(f"claimed availability but {product.name} is out of stock")

    # --- Margin safety ------------------------------------------------------
    margin_unsafe = False
    d_max = max_safe_discount(product, floor)
    for d in _discount_claims(text):
        if d > d_max + 1e-9 and not limited:
            margin_unsafe = True
            issues.append(
                f"offered {round(d * 100)}% off {product.name}; "
                f"max margin-safe is {round(d_max * 100)}%"
            )

    grounded = bool(text.strip()) and not hallucinated and not margin_unsafe
    return ReplyScore(
        passed=grounded,
        grounded=grounded,
        hallucinated_stock=hallucinated,
        margin_unsafe=margin_unsafe,
        issues=issues,
    )


def aggregate(scores: list[ReplyScore]) -> dict[str, float]:
    """Aggregate per-reply scores into rates (0..1)."""
    n = len(scores)
    if n == 0:
        return {"hallucination_rate": 0.0, "margin_safe_rate": 1.0, "grounded_rate": 1.0}
    hallucinated = sum(1 for s in scores if s.hallucinated_stock)
    margin_safe = sum(1 for s in scores if not s.margin_unsafe)
    grounded = sum(1 for s in scores if s.grounded)
    return {
        "hallucination_rate": hallucinated / n,
        "margin_safe_rate": margin_safe / n,
        "grounded_rate": grounded / n,
    }
