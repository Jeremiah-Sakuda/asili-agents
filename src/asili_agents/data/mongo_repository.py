"""MongoDB-backed catalog repository (the application's read path to Atlas).

This is the system-of-record read path used by the API for grounded facts, the
Trust Scorecard ground truth, and the web UI. The *agents* read the same Atlas
data through the MongoDB MCP server (``asili_agents.agents.mcp_tools``); this
class points at the identical collections so customer-facing answers can never
drift from the database.

Decimal money fields are stored as strings in Mongo to preserve exact precision
and converted back to :class:`decimal.Decimal` on read.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from asili_agents.data.models import Policy, Product

if TYPE_CHECKING:
    from pymongo.collection import Collection

PRODUCTS_COLLECTION = "products"
POLICY_COLLECTION = "policy"


def _as_uuid(value: Any) -> UUID:
    """Coerce a value to a UUID, generating one if absent/invalid."""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return uuid4()


def _ci_exact(value: str) -> dict[str, str]:
    """Case-insensitive exact-match regex for a single field."""
    return {"$regex": f"^{re.escape(value)}$", "$options": "i"}


class MongoCatalogRepository:
    """Read access to a seller's catalog/policy stored in MongoDB Atlas."""

    def __init__(
        self,
        uri: str,
        database: str = "asili",
        *,
        products_collection: str = PRODUCTS_COLLECTION,
        policy_collection: str = POLICY_COLLECTION,
    ) -> None:
        from pymongo import MongoClient

        # Bounded timeouts so an unreachable Atlas fails fast (~5s) at startup
        # rather than stalling the PyMongo default of 30s inside a request.
        self._client: MongoClient[dict[str, Any]] = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        self._db = self._client[database]
        self._products: Collection[dict[str, Any]] = self._db[products_collection]
        self._policy_col: Collection[dict[str, Any]] = self._db[policy_collection]

    # -- mapping ------------------------------------------------------------

    def _to_product(self, doc: dict[str, Any]) -> Product:
        return Product(
            id=_as_uuid(doc.get("id") or doc.get("_id")),
            seller_id=_as_uuid(doc.get("seller_id")),
            sku=str(doc["sku"]),
            name=str(doc["name"]),
            description=str(doc.get("description", "")),
            category=str(doc.get("category", "")),
            origin=str(doc.get("origin", "")),
            price=Decimal(str(doc["price"])),
            cost=Decimal(str(doc["cost"])),
            stock_quantity=int(doc.get("stock_quantity", 0)),
            low_stock_threshold=int(doc.get("low_stock_threshold", 8)),
            unit=str(doc.get("unit", "unit")),
            is_active=bool(doc.get("is_active", True)),
        )

    def _to_policy(self, doc: dict[str, Any]) -> Policy:
        free_shipping = doc.get("free_shipping_threshold")
        return Policy(
            id=_as_uuid(doc.get("id") or doc.get("_id")),
            seller_id=_as_uuid(doc.get("seller_id")),
            margin_floor=float(doc.get("margin_floor", 0.45)),
            bundle_discount_percent=float(doc.get("bundle_discount_percent", 0.05)),
            max_bundle_discount_percent=float(doc.get("max_bundle_discount_percent", 0.10)),
            shipping_note=str(doc.get("shipping_note", "")),
            free_shipping_threshold=(
                Decimal(str(free_shipping)) if free_shipping is not None else None
            ),
            returns_note=str(doc.get("returns_note", "")),
        )

    # -- CatalogRepository protocol ----------------------------------------

    def search_products(self, query: str) -> list[Product]:
        rx = {"$regex": re.escape(query), "$options": "i"}
        cursor = self._products.find(
            {
                "$or": [
                    {"name": rx},
                    {"description": rx},
                    {"category": rx},
                    {"origin": rx},
                ]
            }
        )
        return [self._to_product(doc) for doc in cursor]

    def get_product(self, identifier: str) -> Product | None:
        doc = self._products.find_one(
            {
                "$or": [
                    {"id": identifier},
                    {"_id": identifier},
                    {"sku": _ci_exact(identifier)},
                    {"name": _ci_exact(identifier)},
                ]
            }
        )
        return self._to_product(doc) if doc else None

    def get_policy(self) -> Policy | None:
        doc = self._policy_col.find_one({})
        return self._to_policy(doc) if doc else None

    def all_products(self) -> list[Product]:
        return [self._to_product(doc) for doc in self._products.find({})]
