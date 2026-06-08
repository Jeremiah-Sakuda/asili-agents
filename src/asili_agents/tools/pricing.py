"""Pricing tools for margin-safe calculations.

The compute_bundle_price tool is DETERMINISTIC — it uses plain Python
arithmetic, not LLM generation. This ensures prices are always
calculated correctly and respect the margin floor.
"""

from decimal import ROUND_CEILING, Decimal
from typing import Any

from pydantic import BaseModel

from asili_agents.data.models import Policy, Product
from asili_agents.data.repository import (
    StaticCatalogRepository,
    get_catalog_repository,
    set_catalog_repository,
)

# A margin of 100% is mathematically unreachable (it implies zero cost at any
# positive price), and a floor at/above 1.0 is actively dangerous: it makes the
# min-price formula divide by zero (1 - 1.0) and lets the belt-and-suspenders
# loop increment forever. Reject anything at/above this ceiling. Floors this
# high are also never a real business policy, so clamping them out is safe.
MAX_MARGIN_FLOOR = 0.99

# Defense-in-depth cap for the margin-correction loop below. The loop only ever
# nudges the price up by rounding error (a cent or two), so this is wildly more
# than enough headroom while still guaranteeing the loop can never wedge.
MAX_MARGIN_LOOP_ITERATIONS = 100_000


class BundleItem(BaseModel):
    """An item in a bundle."""

    product_id: str
    quantity: int


class BundlePriceResult(BaseModel):
    """Result from bundle price calculation."""

    items: list[dict[str, Any]]
    total_regular_price: float
    total_cost: float
    bundle_price: float
    discount_amount: float
    discount_percent: float
    margin_amount: float
    margin_percent: float
    margin_floor: float
    is_margin_safe: bool
    rationale: str


def set_pricing_context(products: list[Product], policy: Policy) -> None:
    """Initialize the pricing context with catalog and policy data.

    Kept for backwards compatibility (tests, local dev, API startup). Builds a
    :class:`StaticCatalogRepository` so the pricing tool and the catalog tools
    share one source of truth.

    Args:
        products: List of products for price lookups.
        policy: Business policy including margin floor.
    """
    set_catalog_repository(StaticCatalogRepository(products, policy))


def _find_product(identifier: str) -> Product | None:
    """Find a product by ID, SKU, or name via the active repository."""
    return get_catalog_repository().get_product(identifier)


def compute_bundle_price(
    items: list[dict[str, Any]],
    margin_floor: float | None = None,
) -> dict[str, Any]:
    """Compute a margin-safe bundle price for multiple items.

    This is a DETERMINISTIC tool — it uses exact arithmetic to calculate
    the bundle price. The price will be the maximum of:
    1. Regular price minus the allowed bundle discount
    2. The minimum price that maintains the margin floor

    ALWAYS use this tool when pricing bundles. Never calculate
    bundle prices yourself — use this tool to ensure margin safety.

    Args:
        items: List of items in the bundle, each with:
            - product_id: Product ID, SKU, or name
            - quantity: Number of units
        margin_floor: Minimum acceptable margin (0.45 = 45%).
            If not provided, uses the seller's policy default.

    Returns:
        Bundle pricing including:
        - bundle_price: The final margin-safe price
        - margin_percent: Actual margin at this price
        - is_margin_safe: Whether the price meets the margin floor
        - rationale: Explanation of the pricing decision

    Example:
        >>> compute_bundle_price([{"product_id": "Purple Tea", "quantity": 2}])
        {"bundle_price": 34.00, "margin_percent": 0.56, "is_margin_safe": True, ...}
    """
    if not items:
        return {
            "error": "No items provided for bundle",
            "is_margin_safe": False,
        }

    # Resolve policy from the active repository.
    policy = get_catalog_repository().get_policy()

    # Use policy margin floor if not specified
    effective_margin_floor = margin_floor
    if effective_margin_floor is None:
        if policy is not None:
            effective_margin_floor = policy.margin_floor
        else:
            effective_margin_floor = 0.45  # Default 45%

    # Validate the margin floor. It comes either from an LLM tool call or from
    # the unbounded Policy.margin_floor float, so it may be non-numeric or out
    # of range. An out-of-range floor would otherwise crash (floor == 1.0 -> a
    # divide-by-zero at min_price_for_margin) or hang the request (floor >= 1.0
    # -> the correction loop can never reach the margin and increments forever).
    # Reject early with the same structured error shape used for other bad input.
    try:
        effective_margin_floor = float(effective_margin_floor)
    except (TypeError, ValueError):
        return {
            "error": f"invalid margin_floor: {effective_margin_floor!r}",
            "is_margin_safe": False,
        }
    if not (0.0 <= effective_margin_floor < MAX_MARGIN_FLOOR):
        return {
            "error": (
                f"margin_floor must be between 0.0 and {MAX_MARGIN_FLOOR} "
                f"(got {effective_margin_floor})"
            ),
            "is_margin_safe": False,
        }

    # Get the bundle discount from policy.
    bundle_discount = 0.05  # Default 5%
    if policy is not None:
        bundle_discount = policy.bundle_discount_percent

    # Calculate totals
    total_regular = Decimal("0")
    total_cost = Decimal("0")
    resolved_items: list[dict[str, Any]] = []
    errors: list[str] = []

    for item in items:
        product_id = item.get("product_id", "")
        if not isinstance(product_id, str) or not product_id.strip():
            errors.append(f"invalid product_id: {product_id!r}")
            continue

        # Coerce quantity — agent/LLM tool calls frequently pass it as a string.
        raw_quantity = item.get("quantity", 1)
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            errors.append(f"invalid quantity {raw_quantity!r} for {product_id}")
            continue
        if quantity <= 0:
            errors.append(f"quantity must be a positive integer for {product_id}")
            continue

        product = _find_product(product_id)
        if product is None:
            errors.append(f"Product not found: {product_id}")
            continue

        item_price = product.price * quantity
        item_cost = product.cost * quantity
        total_regular += item_price
        total_cost += item_cost

        resolved_items.append(
            {
                "product_id": str(product.id),
                "product_name": product.name,
                "quantity": quantity,
                "unit_price": float(product.price),
                "line_price": float(item_price),
                "unit_cost": float(product.cost),
                "line_cost": float(item_cost),
            }
        )

    if errors:
        return {
            "error": "; ".join(errors),
            "is_margin_safe": False,
        }

    if total_regular == 0:
        return {
            "error": "Total price is zero",
            "is_margin_safe": False,
        }

    # Calculate the minimum price to maintain margin floor
    # margin = (price - cost) / price
    # margin * price = price - cost
    # cost = price - margin * price = price * (1 - margin)
    # price = cost / (1 - margin)
    min_price_for_margin = total_cost / Decimal(str(1 - effective_margin_floor))

    # If even the list price can't clear the margin floor (e.g. cost >= price, or
    # an unusually high floor), a "bundle" would be a SURCHARGE above retail, not
    # a discount. Refuse rather than emit a misleading margin-safe surcharge.
    if min_price_for_margin > total_regular:
        return {
            "error": (
                f"cannot meet the {effective_margin_floor:.0%} margin floor without charging "
                f"above list price (cost too high relative to price)"
            ),
            "is_margin_safe": False,
            "total_regular_price": float(total_regular),
            "total_cost": float(total_cost),
        }

    # Calculate discounted price (regular discount)
    discounted_price = total_regular * Decimal(str(1 - bundle_discount))

    # The bundle price is the maximum of:
    # 1. The discounted price (what we'd like to charge)
    # 2. The minimum price for margin safety
    bundle_price = max(discounted_price, min_price_for_margin)

    # Round UP to the cent so the rounding step can never drop us below the
    # margin floor. (ROUND_HALF_UP previously rounded a floor-bound price DOWN —
    # a real leak: price 1.00 / cost 0.53 returned 0.96 at 44.79% < 45%.)
    cent = Decimal("0.01")
    bundle_price = bundle_price.quantize(cent, rounding=ROUND_CEILING)

    # Belt-and-suspenders: never emit a price whose realized margin is below floor.
    # The iteration cap is defense-in-depth — effective_margin_floor is already
    # validated above, but a bounded loop guarantees a thread can never wedge
    # here regardless of future changes.
    floor_dec = Decimal(str(effective_margin_floor))
    iterations = 0
    while (
        bundle_price > 0
        and (bundle_price - total_cost) / bundle_price < floor_dec
        and iterations < MAX_MARGIN_LOOP_ITERATIONS
    ):
        bundle_price += cent
        iterations += 1

    # Calculate actual metrics. The safety flag is decided in EXACT Decimal space
    # against the Decimal floor — never from the float margin below — so the
    # attesting flag carries the same guarantee as the price itself. (A float
    # round-trip here could report margin-unsafe at the exact floor boundary even
    # though the Decimal price is provably safe.) The float casts that follow are
    # for display/serialization only and never feed the safety decision.
    actual_discount = total_regular - bundle_price
    actual_margin = bundle_price - total_cost
    is_margin_safe = bool(bundle_price > 0 and (actual_margin / bundle_price) >= floor_dec)
    actual_discount_percent = float(actual_discount / total_regular) if total_regular else 0
    actual_margin_percent = float(actual_margin / bundle_price) if bundle_price else 0

    # Generate rationale
    if bundle_price == discounted_price:
        rationale = (
            f"Bundle priced at {bundle_discount * 100:.0f}% discount. "
            f"Margin {actual_margin_percent * 100:.0f}% is above the {effective_margin_floor * 100:.0f}% floor."
        )
    else:
        rationale = (
            f"Bundle priced to maintain {effective_margin_floor * 100:.0f}% margin floor. "
            f"Standard discount would have been below margin."
        )

    return BundlePriceResult(
        items=resolved_items,
        total_regular_price=float(total_regular),
        total_cost=float(total_cost),
        bundle_price=float(bundle_price),
        discount_amount=float(actual_discount),
        discount_percent=actual_discount_percent,
        margin_amount=float(actual_margin),
        margin_percent=actual_margin_percent,
        margin_floor=effective_margin_floor,
        is_margin_safe=is_margin_safe,
        rationale=rationale,
    ).model_dump()
