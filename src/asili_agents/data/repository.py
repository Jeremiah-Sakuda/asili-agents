"""Catalog repository abstraction.

The agents and tools never talk to a data store directly — they go through a
``CatalogRepository``. This gives us one seam with two implementations:

- ``StaticCatalogRepository`` — backed by in-memory seed data. Used for local
  development and the test suite (deterministic, no network).
- ``MongoCatalogRepository`` — backed by MongoDB Atlas (the system of record).
  Used in the deployed/graded path.

In the deployed path the *agents* read catalog/stock through the MongoDB MCP
server (see ``asili_agents.agents.mcp_tools``); this repository is the
*application's* read path to the same Atlas data (for grounded facts, the Trust
Scorecard ground truth, and the web UI). Both point at the same source of truth,
so nothing the customer sees can drift from the database.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from asili_agents.data.models import Policy, Product


@runtime_checkable
class CatalogRepository(Protocol):
    """Read access to a seller's catalog and policy."""

    def search_products(self, query: str) -> list[Product]:
        """Return products whose name/description/category/origin match ``query``."""
        ...

    def get_product(self, identifier: str) -> Product | None:
        """Look up a single product by id, SKU, or name (case-insensitive)."""
        ...

    def get_policy(self) -> Policy | None:
        """Return the seller's business policy, if known."""
        ...

    def all_products(self) -> list[Product]:
        """Return the full catalog."""
        ...


class StaticCatalogRepository:
    """In-memory repository backed by seed data (dev + tests)."""

    def __init__(self, products: list[Product], policy: Policy | None = None) -> None:
        self._products: list[Product] = list(products)
        self._policy: Policy | None = policy
        self._index: dict[str, Product] = {}
        for product in products:
            self._index[str(product.id)] = product
            self._index[product.sku.lower()] = product
            self._index[product.name.lower()] = product

    def search_products(self, query: str) -> list[Product]:
        query_lower = query.lower()
        seen: set[str] = set()
        results: list[Product] = []
        for product in self._products:
            pid = str(product.id)
            if pid in seen:
                continue
            if (
                query_lower in product.name.lower()
                or query_lower in product.description.lower()
                or query_lower in product.category.lower()
                or query_lower in product.origin.lower()
            ):
                results.append(product)
                seen.add(pid)
        return results

    def get_product(self, identifier: str) -> Product | None:
        return self._index.get(identifier.lower()) or self._index.get(identifier)

    def get_policy(self) -> Policy | None:
        return self._policy

    def all_products(self) -> list[Product]:
        return list(self._products)


# ---------------------------------------------------------------------------
# Module-level current repository (the active data source for the tools).
# ---------------------------------------------------------------------------

_current_repository: CatalogRepository | None = None


def set_catalog_repository(repository: CatalogRepository) -> None:
    """Set the active catalog repository used by the tools."""
    global _current_repository
    _current_repository = repository


def get_catalog_repository() -> CatalogRepository:
    """Get the active catalog repository.

    Returns an empty static repository if none has been configured yet, so
    tool calls degrade to "not found" rather than raising.
    """
    if _current_repository is None:
        return StaticCatalogRepository([])
    return _current_repository
