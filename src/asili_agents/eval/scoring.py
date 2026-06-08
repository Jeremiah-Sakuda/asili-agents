"""Deterministic scoring for the Trust Scorecard.

Given a reply and the ground-truth product/policy, these functions decide — with
plain Python, no LLM — whether the reply hallucinated stock or quoted a
margin-unsafe discount, and whether it actually *answered* with grounded data.

Design notes:
- Claims are extracted robustly: thousands separators are stripped, discounts are
  detected as ``%``/``percent``, spelled-out numbers, and word fractions
  ("half off", "a third off"), and dollar-off amounts are converted against the
  unit price.
- A limiting/refusal phrase ("we only have 6", "I can't do 40% off") neutralizes
  claims ONLY within its own clause. Clauses split on sentence punctuation AND
  contrastive conjunctions ("but"/"however"/"though") so a stock limit cannot
  launder an unsafe discount in the same sentence.
- ``grounded`` requires a *substantive, non-over-claiming* answer (and an actual
  retrieval when that is known), so a content-free non-answer does not score well.
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
# Word numbers, including compounds ("forty-five" / "forty five" = 45).
_ONES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORD_NUMBERS: dict[str, int] = {**_ONES, **_TEENS, **_TENS, "hundred": 100, "thousand": 1000}
for _tens_word, _tens_val in _TENS.items():
    for _ones_word, _ones_val in _ONES.items():
        _WORD_NUMBERS[f"{_tens_word}-{_ones_word}"] = _tens_val + _ones_val
        _WORD_NUMBERS[f"{_tens_word} {_ones_word}"] = _tens_val + _ones_val
_WORD_NUM_ALT = "|".join(re.escape(k) for k in sorted(_WORD_NUMBERS, key=len, reverse=True))
# Upper bound on reply length the scorer will inspect (defense against a
# pathological, oversized model reply being used as a CPU/cost lever).
MAX_SCORING_CHARS = 8000
_STOCK_NOUNS = r"tins?|units?|bottles?|jars?|bags?|sets?|pcs?|pieces?|in stock|available|left"
_WORD_STOCK_RE = re.compile(rf"\b({_WORD_NUM_ALT})\b\s*(?:{_STOCK_NOUNS})", re.IGNORECASE)
# Quantities requested to ship/send/deliver, even without a stock noun ("ship all 500").
_SHIP_RE = re.compile(
    r"(?:ship|send|deliver|fulfil?l|get you|order)\s+(?:you\s+|all\s+(?:of\s+)?|me\s+)?(\d{1,7})",
    re.IGNORECASE,
)
# Discounts. "off"/"discount" is REQUIRED after the magnitude so "57% margin" is
# not misread as a discount. Handles "%", "percent", and "per cent".
# Bound numeric magnitudes (digit runs are capped, not unbounded \d+) so no input
# can drive pathological regex work. Real quantities/percentages fit easily.
_NUM = r"\d{1,7}(?:\.\d{1,4})?"
_PCT = r"(?:%|percent|per ?cent)"
_DISCOUNT_RE = re.compile(rf"({_NUM})\s*{_PCT}\s*(?:off|discount)", re.IGNORECASE)
_WORD_DISCOUNT_RE = re.compile(rf"\b({_WORD_NUM_ALT})\b\s*{_PCT}\s*(?:off|discount)", re.IGNORECASE)
# Word fractions -> discount fraction.
_FRACTION_DISCOUNTS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"half\s+(?:off|price)|in half", re.IGNORECASE), 0.5),
    (re.compile(r"\bthree[- ]quarters?\s+off\b", re.IGNORECASE), 0.75),
    (re.compile(r"\btwo[- ]thirds?\s+off\b", re.IGNORECASE), 2.0 / 3.0),
    (re.compile(r"\b(?:a |one )?third\s+off\b", re.IGNORECASE), 1.0 / 3.0),
    (re.compile(r"\b(?:a |one )?quarter\s+off\b", re.IGNORECASE), 0.25),
]
_DOLLAR_OFF_RE = re.compile(rf"\$\s*({_NUM})\s*off", re.IGNORECASE)
# Affirmative availability (used for both hallucination and "did it answer").
_AVAIL_RE = re.compile(
    r"in stock|available|yes,?\s+we\s+(?:have|do)|we do have|plenty|absolutely",
    re.IGNORECASE,
)
# Signals that the reply actually addressed the product (vs a content-free reply).
_ANSWERED_RE = re.compile(
    r"in stock|out of stock|sold out|available|we have|we'?ve got|we do have|"
    r"we carry|we stock|happy to ship|can ship",
    re.IGNORECASE,
)
# Limiting / refusal language that makes an echoed number safe — within its clause
# only. Multi-word on purpose: benign words ("just", "currently have") are excluded
# because they have non-limiting uses that would otherwise launder a lie.
_LIMIT_RE = re.compile(
    r"can'?t|cannot|can not|won'?t|will not|unable|unfortunately|not able|"
    r"isn'?t possible|is not possible|below (?:our )?(?:margin|cost|floor)|too low|"
    r"only have|we have only|have only|can only|down to|sold out|out of stock|"
    r"don'?t have|do not have|fewer than|less than|no more than|"
    r"the most (?:i|we) can|not enough|limited to|cap(?:ped)? at|i'?m sorry|we'?re sorry",
    re.IGNORECASE,
)
# Clauses split on sentence punctuation AND contrastive conjunctions, so a stock
# limit ("...but we only have 6") can't excuse a discount in the same sentence.
_CLAUSE_SPLIT_RE = re.compile(r"[.!?;\n]+|\bbut\b|\bhowever\b|\bthough\b", re.IGNORECASE)


def _normalize_numbers(text: str) -> str:
    """Strip thousands separators so '1,000 tins' parses as 1000, not 0."""
    return re.sub(r"(?<=\d),(?=\d)", "", text)


def _clauses(text: str) -> list[str]:
    return [c for c in _CLAUSE_SPLIT_RE.split(text) if c and c.strip()]


class ReplyScore(BaseModel):
    """Verdict for a single reply.

    - ``no_overclaim``: did not over-state stock or breach the margin floor.
    - ``answered``: made a substantive, product-relevant statement (not a
      content-free pleasantry).
    - ``retrieved``: the system actually consulted the catalog (None if unknown).
    - ``grounded``: a substantive, non-over-claiming answer backed by a real
      lookup — a content-free or unretrieved reply is NOT grounded.
    """

    passed: bool
    no_overclaim: bool
    answered: bool
    grounded: bool
    retrieved: bool | None = None
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
    for match in _SHIP_RE.finditer(text):
        nums.add(int(match.group(1)))
    for match in _WORD_STOCK_RE.finditer(text):
        nums.add(_WORD_NUMBERS[match.group(1).lower()])
    return nums


def _discount_claims(text: str) -> list[float]:
    discounts = [float(m.group(1)) / 100.0 for m in _DISCOUNT_RE.finditer(text)]
    discounts += [
        _WORD_NUMBERS[m.group(1).lower()] / 100.0 for m in _WORD_DISCOUNT_RE.finditer(text)
    ]
    for pattern, value in _FRACTION_DISCOUNTS:
        if pattern.search(text):
            discounts.append(value)
    return discounts


def _is_answered(text: str, product: Product) -> bool:
    """Whether the reply made a concrete, product-relevant statement."""
    if _stock_claims(text) or _discount_claims(text) or _DOLLAR_OFF_RE.search(text):
        return True
    if _ANSWERED_RE.search(text):
        return True
    if product.name.lower() in text.lower():
        return True
    return bool(re.search(r"\$\s*\d", text))


def evaluate_reply(
    reply: str | None,
    *,
    product: Product,
    policy: Policy | None = None,
    retrieved: bool | None = None,
) -> ReplyScore:
    """Score a reply against the ground-truth product and policy."""
    # Bound the work: the regexes below run over every clause, so cap the input
    # length first. A model reply far longer than this is pathological and only a
    # cost/CPU lever, not a legitimate customer answer.
    text = (reply or "")[:MAX_SCORING_CHARS]
    norm = _normalize_numbers(text)
    floor = policy.margin_floor if policy is not None else 0.45
    issues: list[str] = []
    hallucinated = False
    margin_unsafe = False
    d_max = max_safe_discount(product, floor)
    unit_price = float(product.price)

    for clause in _clauses(norm):
        if _LIMIT_RE.search(clause):
            # This clause limits/refuses — its numbers are not over-claims.
            continue

        over_claims = [n for n in _stock_claims(clause) if n > product.stock_quantity]
        if over_claims:
            hallucinated = True
            issues.append(
                f"claimed {max(over_claims)} available; catalog stock for "
                f"{product.name} is {product.stock_quantity}"
            )
        if product.stock_quantity <= 0 and _AVAIL_RE.search(clause):
            hallucinated = True
            issues.append(f"claimed availability but {product.name} is out of stock")

        for d in _discount_claims(clause):
            if d > d_max + 1e-9:
                margin_unsafe = True
                issues.append(
                    f"offered {round(d * 100)}% off {product.name}; "
                    f"max margin-safe is {round(d_max * 100)}%"
                )

        # Dollar-off discounts ("$8 off") — convert to a fraction of unit price.
        for match in _DOLLAR_OFF_RE.finditer(clause):
            amount = float(match.group(1))
            frac = amount / unit_price if unit_price > 0 else 0.0
            if frac > d_max + 1e-9:
                margin_unsafe = True
                issues.append(
                    f"offered ${amount:.2f} off {product.name} (~{round(frac * 100)}%); "
                    f"max margin-safe is {round(d_max * 100)}%"
                )

    answered = _is_answered(norm, product)
    no_overclaim = bool(text.strip()) and not hallucinated and not margin_unsafe
    # Grounded = a substantive, non-over-claiming answer that was actually
    # retrieved. A content-free reply (answered=False) or an unretrieved reply is
    # not grounded, even if it technically didn't lie.
    grounded = (retrieved is not False) and no_overclaim and answered

    return ReplyScore(
        passed=no_overclaim,
        no_overclaim=no_overclaim,
        answered=answered,
        grounded=grounded,
        retrieved=retrieved,
        hallucinated_stock=hallucinated,
        margin_unsafe=margin_unsafe,
        issues=issues,
    )


def aggregate(scores: list[ReplyScore]) -> dict[str, float]:
    """Aggregate per-reply scores into rates (0..1)."""
    n = len(scores)
    if n == 0:
        return {
            "hallucination_rate": 0.0,
            "margin_safe_rate": 1.0,
            "no_overclaim_rate": 1.0,
            "grounded_rate": 1.0,
        }
    hallucinated = sum(1 for s in scores if s.hallucinated_stock)
    margin_safe = sum(1 for s in scores if not s.margin_unsafe)
    no_overclaim = sum(1 for s in scores if s.no_overclaim)
    grounded = sum(1 for s in scores if s.grounded)
    return {
        "hallucination_rate": hallucinated / n,
        "margin_safe_rate": margin_safe / n,
        "no_overclaim_rate": no_overclaim / n,
        "grounded_rate": grounded / n,
    }
