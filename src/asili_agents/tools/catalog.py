"""Catalog tools for product lookup and stock checking.

These tools provide grounded access to the seller's catalog data, ensuring
agents never hallucinate product information. They read through a
``CatalogRepository`` (static seed data in dev/tests, MongoDB Atlas in the
deployed path) rather than any in-process global, so the same source of truth
backs the tools, the API, and the Trust Scorecard.
"""

from typing import Any

from pydantic import BaseModel

from asili_agents.data.models import Product
from asili_agents.data.repository import (
    StaticCatalogRepository,
    get_catalog_repository,
    set_catalog_repository,
)


class ProductSearchResult(BaseModel):
    """Result from a catalog search."""

    product_id: str
    sku: str
    name: str
    description: str
    category: str
    origin: str
    price: float
    unit: str
    in_stock: bool


class StockCheckResult(BaseModel):
    """Result from a stock check."""

    product_id: str
    product_name: str
    quantity: int
    unit: str
    level: str  # StockLevel value
    low_threshold: int
    is_available: bool


class CostResult(BaseModel):
    """Result from a cost lookup."""

    product_id: str
    product_name: str
    unit_cost: float
    unit_price: float
    unit_margin: float
    margin_percent: float


def set_product_store(products: list[Product]) -> None:
    """Initialize the catalog repository with static product data.

    Kept for backwards compatibility (tests, local dev, API startup). Builds a
    :class:`StaticCatalogRepository`, preserving any policy already configured.

    Args:
        products: List of products to make available for lookup.
    """
    existing = get_catalog_repository()
    policy = existing.get_policy()
    set_catalog_repository(StaticCatalogRepository(products, policy))


def catalog_search(query: str) -> list[dict[str, Any]]:
    """Search the product catalog for items matching the query.

    This tool searches product names, descriptions, categories, and origins to
    find relevant items. Use this before mentioning any product so responses
    are grounded in real catalog data.

    Args:
        query: Search query (product name, category, or description keywords)

    Returns:
        List of matching products with their details. Empty if no matches.

    Example:
        >>> catalog_search("purple tea")
        [{"product_id": "...", "name": "Purple Tea", "price": 18.0, ...}]
    """
    repo = get_catalog_repository()
    results = [
        ProductSearchResult(
            product_id=str(product.id),
            sku=product.sku,
            name=product.name,
            description=product.description,
            category=product.category,
            origin=product.origin,
            price=float(product.price),
            unit=product.unit,
            in_stock=product.is_in_stock,
        )
        for product in repo.search_products(query)
    ]
    return [r.model_dump() for r in results]


def check_stock(product_identifier: str) -> dict[str, Any]:
    """Check the current stock level for a product.

    Returns the exact stock quantity and status. ALWAYS use this tool before
    telling a customer about availability. Never guess or assume stock levels.

    Args:
        product_identifier: Product ID, SKU, or name to look up

    Returns:
        Stock information including quantity, level (low/healthy/etc), and
        whether the product is available for sale.

    Example:
        >>> check_stock("Purple Tea")
        {"quantity": 6, "level": "low", "is_available": True, ...}
    """
    product = get_catalog_repository().get_product(product_identifier)

    if product is None:
        return {
            "error": f"Product not found: {product_identifier}",
            "is_available": False,
        }

    return StockCheckResult(
        product_id=str(product.id),
        product_name=product.name,
        quantity=product.stock_quantity,
        unit=product.unit,
        level=product.stock_level.value,
        low_threshold=product.low_stock_threshold,
        is_available=product.is_in_stock,
    ).model_dump()


def get_costs(product_identifier: str) -> dict[str, Any]:
    """Get the cost and margin information for a product.

    Returns the unit cost, price, and margin for pricing decisions. Use this
    when calculating bundle prices or verifying margins.

    Args:
        product_identifier: Product ID, SKU, or name to look up

    Returns:
        Cost and margin information for the product.

    Example:
        >>> get_costs("Purple Tea")
        {"unit_cost": 7.40, "unit_price": 18.00, "margin_percent": 0.59, ...}
    """
    product = get_catalog_repository().get_product(product_identifier)

    if product is None:
        return {"error": f"Product not found: {product_identifier}"}

    return CostResult(
        product_id=str(product.id),
        product_name=product.name,
        unit_cost=float(product.cost),
        unit_price=float(product.price),
        unit_margin=float(product.margin),
        margin_percent=product.margin_percent,
    ).model_dump()
