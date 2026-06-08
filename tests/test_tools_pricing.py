"""Tests for pricing tools.

These tests verify that the compute_bundle_price tool produces
correct, deterministic, margin-safe prices.
"""

from decimal import Decimal
from uuid import uuid4

from asili_agents.data.models import Policy, Product
from asili_agents.tools.pricing import compute_bundle_price, set_pricing_context


class TestComputeBundlePrice:
    """Tests for the compute_bundle_price tool."""

    def test_bundle_price_basic(self):
        """Test basic bundle pricing."""
        result = compute_bundle_price(
            items=[{"product_id": "Purple Tea", "quantity": 2}],
            margin_floor=0.45,
        )
        assert "error" not in result
        assert result["is_margin_safe"] is True

    def test_bundle_price_respects_margin_floor(self):
        """Test that bundle price respects margin floor."""
        result = compute_bundle_price(
            items=[{"product_id": "Purple Tea", "quantity": 2}],
            margin_floor=0.45,
        )
        # Margin should be >= 45%
        assert result["margin_percent"] >= 0.45

    def test_bundle_price_calculation(self):
        """Test the actual price calculation.

        Purple Tea: $18.00/tin, cost $7.40/tin
        2-tin bundle regular: $36.00
        With 5% discount: $34.20
        But we round nicely, so expect ~$34.00

        Cost for 2 tins: $14.80
        At $34.00: margin = $19.20, margin% = 56.5%
        """
        result = compute_bundle_price(
            items=[{"product_id": "Purple Tea", "quantity": 2}],
        )

        # Check totals
        assert result["total_regular_price"] == 36.00
        assert result["total_cost"] == 14.80

        # Bundle price should be discounted
        assert result["bundle_price"] < 36.00

        # Margin should still be safe
        assert result["margin_percent"] >= 0.45

    def test_bundle_price_has_rationale(self):
        """Test that pricing includes a rationale."""
        result = compute_bundle_price(
            items=[{"product_id": "Purple Tea", "quantity": 2}],
        )
        assert "rationale" in result
        assert len(result["rationale"]) > 0

    def test_bundle_price_empty_items(self):
        """Test error handling for empty items."""
        result = compute_bundle_price(items=[])
        assert "error" in result
        assert result["is_margin_safe"] is False

    def test_bundle_price_invalid_product(self):
        """Test error handling for invalid product."""
        result = compute_bundle_price(
            items=[{"product_id": "nonexistent", "quantity": 1}],
        )
        assert "error" in result
        assert result["is_margin_safe"] is False

    def test_bundle_price_multiple_products(self):
        """Test bundle with multiple different products."""
        result = compute_bundle_price(
            items=[
                {"product_id": "Purple Tea", "quantity": 1},
                {"product_id": "Kenyan Green Tea", "quantity": 1},
            ],
        )
        assert "error" not in result
        # Regular: $18 + $15 = $33
        assert result["total_regular_price"] == 33.00
        assert result["is_margin_safe"] is True

    def test_bundle_price_deterministic(self):
        """Test that pricing is deterministic (same inputs = same outputs)."""
        items = [{"product_id": "Purple Tea", "quantity": 2}]

        result1 = compute_bundle_price(items=items, margin_floor=0.45)
        result2 = compute_bundle_price(items=items, margin_floor=0.45)

        assert result1["bundle_price"] == result2["bundle_price"]
        assert result1["margin_percent"] == result2["margin_percent"]

    def test_bundle_price_high_margin_floor(self):
        """A high-but-achievable margin floor is respected (price rises to meet it)."""
        result = compute_bundle_price(
            items=[{"product_id": "Purple Tea", "quantity": 2}],
            margin_floor=0.55,  # achievable for Purple Tea (max ~58.9% at list)
        )
        assert result["margin_percent"] >= 0.55
        assert result["is_margin_safe"] is True

    def test_unachievable_margin_floor_is_refused(self):
        """A floor that can't be met under list price refuses, not surcharges."""
        result = compute_bundle_price(
            items=[{"product_id": "Purple Tea", "quantity": 2}],
            margin_floor=0.60,  # > 58.9% max at list -> unachievable without a surcharge
        )
        assert "error" in result
        assert result["is_margin_safe"] is False
        assert "bundle_price" not in result

    def test_bundle_price_items_detail(self):
        """Test that items detail is included in result."""
        result = compute_bundle_price(
            items=[{"product_id": "Purple Tea", "quantity": 2}],
        )
        assert "items" in result
        assert len(result["items"]) == 1

        item = result["items"][0]
        assert item["product_name"] == "Purple Tea"
        assert item["quantity"] == 2
        assert item["unit_price"] == 18.00
        assert item["line_price"] == 36.00


class TestMarginFloorNeverLeaks:
    """P0 regression: rounding must never return a sub-floor price."""

    def test_floor_bound_price_rounds_up_not_down(self):
        # price 1.00 / cost 0.53 previously returned 0.96 at 44.79% (below floor).
        sid = uuid4()
        prod = Product(
            id=uuid4(),
            seller_id=sid,
            sku="X",
            name="Widget",
            description="d",
            price=Decimal("1.00"),
            cost=Decimal("0.53"),
        )
        set_pricing_context([prod], Policy(seller_id=sid, margin_floor=0.45))
        r = compute_bundle_price([{"product_id": "X", "quantity": 1}], margin_floor=0.45)
        assert "error" not in r
        assert r["margin_percent"] >= 0.45
        assert r["is_margin_safe"] is True
        assert r["bundle_price"] >= 0.97

    def test_is_margin_safe_decided_in_decimal_not_float(self):
        """The safety flag must agree with EXACT Decimal margin, not the float
        margin shown for display. We sweep a range of floor-binding cost/price
        pairs; whenever the engine emits a price it must report is_margin_safe
        True, and the exact Decimal margin must truly be at/above the floor — a
        float-space check could wobble to a false-negative at the boundary."""
        floor = Decimal("0.45")
        # cost 0.40 .. 0.55 against a $1.00 list: above 0.55 a 45% floor is
        # unachievable at/below list price, so the engine correctly refuses
        # (covered by TestCostExceedsPrice / the unachievable-floor test).
        for cents in range(40, 56):
            sid = uuid4()
            prod = Product(
                id=uuid4(),
                seller_id=sid,
                sku="B",
                name="Boundary",
                description="d",
                price=Decimal("1.00"),
                cost=Decimal(cents) / Decimal("100"),
            )
            set_pricing_context([prod], Policy(seller_id=sid, margin_floor=0.45))
            r = compute_bundle_price([{"product_id": "B", "quantity": 1}], margin_floor=0.45)
            assert "error" not in r, f"cost {cents}c unexpectedly refused"
            # Recompute the margin in exact Decimal from the emitted price.
            bp = Decimal(str(r["bundle_price"]))
            exact_margin = (bp - (Decimal(cents) / Decimal("100"))) / bp
            assert exact_margin >= floor, f"cost {cents}c: exact margin {exact_margin} below floor"
            # The attesting flag must match the exact-Decimal truth (never a
            # float-rounding false-negative).
            assert r["is_margin_safe"] is True, f"cost {cents}c: safe price flagged unsafe"


class TestCostExceedsPrice:
    """P1 regression: cost >= price must refuse, not emit a surcharge labeled safe."""

    def test_cost_above_price_is_refused(self):
        sid = uuid4()
        prod = Product(
            id=uuid4(),
            seller_id=sid,
            sku="LOSS",
            name="LossLeader",
            description="d",
            price=Decimal("10.00"),
            cost=Decimal("9.00"),
        )
        set_pricing_context([prod], Policy(seller_id=sid, margin_floor=0.45))
        r = compute_bundle_price([{"product_id": "LOSS", "quantity": 1}], margin_floor=0.45)
        assert "error" in r
        assert r["is_margin_safe"] is False
        assert "bundle_price" not in r  # no surcharge emitted


class TestInputValidation:
    """P0 regression: bad inputs must not crash or emit negative prices."""

    def test_string_quantity_is_coerced(self):
        r = compute_bundle_price([{"product_id": "Purple Tea", "quantity": "2"}], margin_floor=0.45)
        assert "error" not in r
        assert r["is_margin_safe"] is True

    def test_negative_quantity_is_rejected(self):
        r = compute_bundle_price([{"product_id": "Purple Tea", "quantity": -5}], margin_floor=0.45)
        assert "error" in r
        assert "bundle_price" not in r  # no negative quote emitted

    def test_zero_quantity_is_rejected(self):
        r = compute_bundle_price([{"product_id": "Purple Tea", "quantity": 0}])
        assert "error" in r

    def test_non_numeric_quantity_is_rejected(self):
        r = compute_bundle_price([{"product_id": "Purple Tea", "quantity": "abc"}])
        assert "error" in r

    def test_missing_product_id_is_rejected(self):
        r = compute_bundle_price([{"quantity": 2}])
        assert "error" in r


class TestMarginFloorBounds:
    """P0 regression: an out-of-range margin floor must not crash or hang.

    margin_floor reaches this tool either from an LLM tool call or from the
    unbounded Policy.margin_floor float. Values >= 1.0 used to either raise a
    DivisionByZero (floor == 1.0) or spin forever in the correction loop
    (floor > 1.0); a negative floor is also nonsensical. All must return the
    structured error dict instead.
    """

    def test_margin_floor_one_returns_error_not_division_by_zero(self):
        # 1 - 1.0 == 0 previously raised decimal.DivisionByZero.
        r = compute_bundle_price(
            [{"product_id": "Purple Tea", "quantity": 2}],
            margin_floor=1.0,
        )
        assert "error" in r
        assert r["is_margin_safe"] is False
        assert "bundle_price" not in r  # no quote emitted on bad input

    def test_margin_floor_above_one_returns_error_not_infinite_loop(self):
        # margin_floor=1.5 previously spun the correction loop forever. If this
        # test returns at all, the loop is bounded.
        r = compute_bundle_price(
            [{"product_id": "Purple Tea", "quantity": 2}],
            margin_floor=1.5,
        )
        assert "error" in r
        assert r["is_margin_safe"] is False
        assert "bundle_price" not in r

    def test_negative_margin_floor_returns_error(self):
        r = compute_bundle_price(
            [{"product_id": "Purple Tea", "quantity": 2}],
            margin_floor=-0.5,
        )
        assert "error" in r
        assert r["is_margin_safe"] is False
        assert "bundle_price" not in r

    def test_unbounded_policy_margin_floor_is_rejected(self):
        # A bad floor coming from Policy (not the LLM arg) must be caught too.
        sid = uuid4()
        prod = Product(
            id=uuid4(),
            seller_id=sid,
            sku="X",
            name="Widget",
            description="d",
            price=Decimal("1.00"),
            cost=Decimal("0.53"),
        )
        set_pricing_context([prod], Policy(seller_id=sid, margin_floor=1.0))
        r = compute_bundle_price([{"product_id": "X", "quantity": 1}])
        assert "error" in r
        assert r["is_margin_safe"] is False
