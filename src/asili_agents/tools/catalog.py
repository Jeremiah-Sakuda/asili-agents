"""Catalog tools for product lookup and stock checking.

These tools provide grounded access to the seller's catalog data,
ensuring agents never hallucinate product information.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from asili_agents.data.models import Product, StockLevel


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


# In-memory product store (will be populated from seed data)
_product_store: dict[str, Product] = {}


def set_product_store(products: list[Product]) -> None:
    """Initialize the product store with catalog data.

    Args:
        products: List of products to make available for lookup.
    """
    global _product_store
    _product_store = {str(p.id): p for p in products}
    # Also index by SKU and name for flexible lookup
    for p in products:
        _product_store[p.sku.lower()] = p
        _product_store[p.name.lower()] = p


def catalog_search(query: str) -> list[dict[str, Any]]:
    """Search the product catalog for items matching the query.

    This tool searches product names, descriptions, and categories
    to find relevant items. Use this when a customer asks about
    products or when you need to verify product details.

    Args:
        query: Search query (product name, category, or description keywords)

    Returns:
        List of matching products with their details.
        Returns empty list if no matches found.

    Example:
        >>> catalog_search("purple tea")
        [{"product_id": "...", "name": "Purple Tea", "price": 18.0, ...}]
    """
    query_lower = query.lower()
    results: list[ProductSearchResult] = []

    # Search through all products
    seen_ids: set[str] = set()
    for key, product in _product_store.items():
        if str(product.id) in seen_ids:
            continue

        # Check if query matches name, description, category, or origin
        if (
            query_lower in product.name.lower()
            or query_lower in product.description.lower()
            or query_lower in product.category.lower()
            or query_lower in product.origin.lower()
        ):
            results.append(
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
            )
            seen_ids.add(str(product.id))

    return [r.model_dump() for r in results]


def check_stock(product_identifier: str) -> dict[str, Any]:
    """Check the current stock level for a product.

    This tool returns the exact stock quantity and status.
    ALWAYS use this tool before telling a customer about availability.
    Never guess or assume stock levels.

    Args:
        product_identifier: Product ID, SKU, or name to look up

    Returns:
        Stock information including quantity, level (low/healthy/etc),
        and whether the product is available for sale.

    Example:
        >>> check_stock("Purple Tea")
        {"quantity": 6, "level": "low", "is_available": True, ...}
    """
    # Try to find product by ID, SKU, or name
    product = _product_store.get(product_identifier.lower())

    if product is None:
        # Try exact ID match
        product = _product_store.get(product_identifier)

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

    This tool returns the unit cost, price, and margin for pricing decisions.
    Use this when calculating bundle prices or verifying margins.

    Args:
        product_identifier: Product ID, SKU, or name to look up

    Returns:
        Cost and margin information for the product.

    Example:
        >>> get_costs("Purple Tea")
        {"unit_cost": 7.40, "unit_price": 18.00, "margin_percent": 0.59, ...}
    """
    # Try to find product
    product = _product_store.get(product_identifier.lower())

    if product is None:
        product = _product_store.get(product_identifier)

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
