"""Pricing tools for margin-safe calculations.

The compute_bundle_price tool is DETERMINISTIC — it uses plain Python
arithmetic, not LLM generation. This ensures prices are always
calculated correctly and respect the margin floor.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel

from asili_agents.data.models import Policy, Product
from asili_agents.data.repository import (
    StaticCatalogRepository,
    get_catalog_repository,
    set_catalog_repository,
)


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

    # Get discount limits from policy
    bundle_discount = 0.05  # Default 5%
    max_discount = 0.10  # Default 10%
    if policy is not None:
        bundle_discount = policy.bundle_discount_percent
        max_discount = policy.max_bundle_discount_percent

    # Calculate totals
    total_regular = Decimal("0")
    total_cost = Decimal("0")
    resolved_items: list[dict[str, Any]] = []
    errors: list[str] = []

    for item in items:
        product_id = item.get("product_id", "")
        quantity = item.get("quantity", 1)

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

    # Calculate discounted price (regular discount)
    discounted_price = total_regular * Decimal(str(1 - bundle_discount))

    # The bundle price is the maximum of:
    # 1. The discounted price (what we'd like to charge)
    # 2. The minimum price for margin safety
    bundle_price = max(discounted_price, min_price_for_margin)

    # Round to nearest cent
    bundle_price = bundle_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Ensure we don't exceed max discount
    max_discount_price = total_regular * Decimal(str(1 - max_discount))
    if bundle_price < max_discount_price:
        bundle_price = max_discount_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Calculate actual metrics
    actual_discount = total_regular - bundle_price
    actual_discount_percent = float(actual_discount / total_regular) if total_regular else 0
    actual_margin = bundle_price - total_cost
    actual_margin_percent = float(actual_margin / bundle_price) if bundle_price else 0
    is_margin_safe = actual_margin_percent >= effective_margin_floor

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
