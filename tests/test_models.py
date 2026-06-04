"""Tests for data models."""

from decimal import Decimal
from uuid import UUID

from asili_agents.data.models import (
    MessageDirection,
    Product,
    StockLevel,
)


class TestSeller:
    """Tests for the Seller model."""

    def test_seller_creation(self, demo_seller):
        """Test basic seller creation."""
        assert demo_seller.name == "Mahaba Tea Co."
        assert demo_seller.origin_country == "KE"
        assert demo_seller.destination_country == "US"

    def test_seller_lane_computed(self, demo_seller):
        """Test the lane computed property."""
        assert demo_seller.lane == "KE → US"

    def test_seller_has_brand_voice(self, demo_seller):
        """Test that seller has a brand voice defined."""
        assert len(demo_seller.brand_voice) > 0
        assert "tea" in demo_seller.brand_voice.lower()


class TestProduct:
    """Tests for the Product model."""

    def test_product_creation(self, purple_tea):
        """Test basic product creation."""
        assert purple_tea.name == "Purple Tea"
        assert purple_tea.sku == "MH-PRP-50"
        assert purple_tea.price == Decimal("18.00")
        assert purple_tea.cost == Decimal("7.40")

    def test_product_margin_computed(self, purple_tea):
        """Test margin calculation."""
        # Margin = price - cost = 18.00 - 7.40 = 10.60
        assert purple_tea.margin == Decimal("10.60")

    def test_product_margin_percent_computed(self, purple_tea):
        """Test margin percentage calculation."""
        # Margin percent = 10.60 / 18.00 ≈ 0.589
        assert 0.58 < purple_tea.margin_percent < 0.60

    def test_product_stock_level_low(self, purple_tea):
        """Test stock level detection for low stock."""
        # Purple tea has 6 units, threshold is 8
        assert purple_tea.stock_level == StockLevel.LOW

    def test_product_is_in_stock(self, purple_tea):
        """Test in stock detection."""
        assert purple_tea.is_in_stock is True

    def test_product_out_of_stock(self):
        """Test out of stock detection."""
        product = Product(
            seller_id=UUID("11111111-1111-1111-1111-111111111111"),
            sku="TEST-001",
            name="Test Product",
            description="A test product",
            price=Decimal("10.00"),
            cost=Decimal("5.00"),
            stock_quantity=0,
        )
        assert product.stock_level == StockLevel.OUT_OF_STOCK
        assert product.is_in_stock is False


class TestPolicy:
    """Tests for the Policy model."""

    def test_policy_margin_floor(self, demo_policy):
        """Test margin floor is set correctly."""
        assert demo_policy.margin_floor == 0.45  # 45%

    def test_policy_bundle_discount(self, demo_policy):
        """Test bundle discount is set."""
        assert demo_policy.bundle_discount_percent == 0.05  # 5%

    def test_policy_max_bundle_discount(self, demo_policy):
        """Test max bundle discount is set."""
        assert demo_policy.max_bundle_discount_percent == 0.10  # 10%


class TestConversation:
    """Tests for the Conversation model."""

    def test_conversation_creation(self, demo_conversation):
        """Test basic conversation creation."""
        assert demo_conversation.customer_name == "Dana R."
        assert demo_conversation.customer_initials == "DR"
        assert demo_conversation.channel == "Storefront chat"

    def test_conversation_has_initial_message(self, demo_conversation):
        """Test that demo conversation has the initial message."""
        assert len(demo_conversation.messages) == 1
        msg = demo_conversation.messages[0]
        assert msg.direction == MessageDirection.INBOUND
        assert "purple tea" in msg.body.lower()

    def test_add_message(self, demo_conversation):
        """Test adding a message to conversation."""
        demo_conversation.add_message(
            direction=MessageDirection.OUTBOUND,
            sender_name="Messaging Agent",
            body="Yes, we have Purple Tea in stock!",
        )
        assert len(demo_conversation.messages) == 2
        assert demo_conversation.messages[1].direction == MessageDirection.OUTBOUND
