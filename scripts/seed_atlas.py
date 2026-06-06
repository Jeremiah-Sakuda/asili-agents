"""Seed MongoDB Atlas with the demo catalog, policy, and seller(s).

This populates the collections the agents read (via the MongoDB MCP server) and
the app reads (via MongoCatalogRepository): ``products``, ``policy``, ``sellers``.

Usage:
    export MONGODB_URI="mongodb+srv://USER:PASS@cluster.example.mongodb.net/"
    python scripts/seed_atlas.py          # seed Mahaba Tea Co. only (clean demo)
    python scripts/seed_atlas.py --all    # also seed the extra multi-tenant sellers

Money fields (price/cost) are stored as strings to preserve exact precision;
MongoCatalogRepository converts them back to Decimal on read.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from asili_agents.config import get_settings
from asili_agents.data.models import Policy, Product, Seller
from asili_agents.data.seed import get_demo_seller


def _product_doc(p: Product) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "seller_id": str(p.seller_id),
        "sku": p.sku,
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "origin": p.origin,
        "price": str(p.price),
        "cost": str(p.cost),
        "stock_quantity": p.stock_quantity,
        "low_stock_threshold": p.low_stock_threshold,
        "unit": p.unit,
        "is_active": p.is_active,
    }


def _policy_doc(pol: Policy) -> dict[str, Any]:
    return {
        "id": str(pol.id),
        "seller_id": str(pol.seller_id),
        "margin_floor": pol.margin_floor,
        "bundle_discount_percent": pol.bundle_discount_percent,
        "max_bundle_discount_percent": pol.max_bundle_discount_percent,
        "shipping_note": pol.shipping_note,
        "free_shipping_threshold": (
            str(pol.free_shipping_threshold) if pol.free_shipping_threshold is not None else None
        ),
        "returns_note": pol.returns_note,
    }


def _seller_doc(s: Seller) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "brand_voice": s.brand_voice,
        "origin_country": s.origin_country,
        "destination_country": s.destination_country,
        "currency": s.currency,
        "lane": s.lane,
    }


def _tenants(seed_all: bool) -> list[tuple[Seller, list[Product], Policy]]:
    if seed_all:
        try:
            from asili_agents.data.seed_tenants import get_all_sellers

            return get_all_sellers()
        except Exception as exc:  # pragma: no cover - optional module
            print(f"WARN: could not load seed_tenants ({exc}); seeding demo seller only")
    return [get_demo_seller()]


def main() -> int:
    settings = get_settings()
    uri = settings.mongodb_uri or os.environ.get("MONGODB_URI")
    if not uri:
        print("ERROR: set MONGODB_URI (or configure it in .env) before seeding.")
        return 1

    from pymongo import MongoClient

    seed_all = "--all" in sys.argv[1:]
    db = MongoClient(uri)[settings.mongodb_database]

    total_products = 0
    for seller, products, policy in _tenants(seed_all):
        db.sellers.update_one({"id": str(seller.id)}, {"$set": _seller_doc(seller)}, upsert=True)
        for product in products:
            db.products.update_one(
                {"sku": product.sku}, {"$set": _product_doc(product)}, upsert=True
            )
        db.policy.update_one(
            {"seller_id": str(policy.seller_id)}, {"$set": _policy_doc(policy)}, upsert=True
        )
        total_products += len(products)
        print(f"seeded {seller.name}: {len(products)} products, 1 policy")

    print(f"done — {total_products} products across {settings.mongodb_database!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
