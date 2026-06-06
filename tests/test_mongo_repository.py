"""Tests for MongoCatalogRepository document<->model mapping (no live DB needed).

MongoClient construction is lazy in pymongo, and these tests only exercise the
pure mapping methods, so no MongoDB server is required.
"""

from decimal import Decimal

from asili_agents.data.mongo_repository import MongoCatalogRepository


def _repo() -> MongoCatalogRepository:
    return MongoCatalogRepository("mongodb://localhost:27017", "asili_test")


class TestProductMapping:
    def test_maps_full_document(self):
        doc = {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "seller_id": "11111111-1111-1111-1111-111111111111",
            "sku": "MH-PRP-50",
            "name": "Purple Tea",
            "description": "Rare purple-leaf tea.",
            "category": "Specialty Tea",
            "origin": "Nandi Hills, Kenya",
            "price": "18.00",
            "cost": "7.40",
            "stock_quantity": 6,
            "low_stock_threshold": 8,
            "unit": "tin",
            "is_active": True,
        }
        product = _repo()._to_product(doc)
        assert product.sku == "MH-PRP-50"
        assert product.price == Decimal("18.00")  # money preserved exactly
        assert product.cost == Decimal("7.40")
        assert product.stock_quantity == 6
        assert product.stock_level.value == "low"

    def test_generates_uuid_when_id_missing(self):
        product = _repo()._to_product({"sku": "X", "name": "N", "price": "1.00", "cost": "0.50"})
        assert product.sku == "X"  # missing id/seller_id -> generated, no crash


class TestPolicyMapping:
    def test_maps_policy(self):
        doc = {
            "seller_id": "11111111-1111-1111-1111-111111111111",
            "margin_floor": 0.45,
            "bundle_discount_percent": 0.05,
            "max_bundle_discount_percent": 0.10,
            "shipping_note": "ships in 2-3 days",
            "free_shipping_threshold": "50.00",
            "returns_note": "30-day returns",
        }
        policy = _repo()._to_policy(doc)
        assert policy.margin_floor == 0.45
        assert policy.free_shipping_threshold == Decimal("50.00")

    def test_missing_free_shipping_is_none(self):
        policy = _repo()._to_policy({"margin_floor": 0.5})
        assert policy.free_shipping_threshold is None
