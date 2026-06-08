"""Seed data for the Asili Agents demo.

This module provides realistic demo data for Mahaba Tea Co., a Kenyan
specialty tea seller. All data is designed to showcase the multi-agent
system's capabilities:

1. Grounding: Products with real details (origin, description)
2. Stock management: Some items low stock to trigger warnings
3. Pricing: Clear margins to demonstrate margin-safe calculations
4. Policies: Defined margin floor for the pricing agent
"""

from decimal import Decimal
from uuid import UUID

from asili_agents.data.models import (
    Conversation,
    ConversationStatus,
    MessageDirection,
    Policy,
    Product,
    Seller,
)

# Fixed UUIDs for consistent demo data
MAHABA_TEA_ID = UUID("11111111-1111-1111-1111-111111111111")
DEMO_CONVERSATION_ID = UUID("22222222-2222-2222-2222-222222222222")


def create_mahaba_tea_seller() -> Seller:
    """Create the Mahaba Tea Co. seller."""
    return Seller(
        id=MAHABA_TEA_ID,
        name="Mahaba Tea Co.",
        category="specialty tea",
        brand_voice=(
            "Warm and knowledgeable about tea. We share the story behind each product "
            "and help customers find their perfect cup. Friendly but professional, "
            "like a trusted tea shop owner."
        ),
        origin_country="KE",
        destination_country="US",
        currency="USD",
    )


def create_mahaba_tea_products() -> list[Product]:
    """Create the product catalog for Mahaba Tea Co.

    Products are based on real Kenyan tea varieties with realistic
    pricing for direct-to-consumer specialty tea.
    """
    return [
        Product(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            seller_id=MAHABA_TEA_ID,
            sku="MH-PRP-50",
            name="Purple Tea",
            description=(
                "Rare purple-leaf tea from the Nandi Hills of Kenya. "
                "Rich in anthocyanins with a smooth, slightly sweet flavor "
                "and beautiful violet infusion. Hand-picked at high altitude."
            ),
            category="Specialty Tea",
            origin="Nandi Hills, Kenya",
            price=Decimal("18.00"),
            cost=Decimal("7.40"),
            stock_quantity=6,
            low_stock_threshold=8,
            unit="tin",
        ),
        Product(
            id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            seller_id=MAHABA_TEA_ID,
            sku="MH-GRN-50",
            name="Kenyan Green Tea",
            description=(
                "Fresh, vegetal green tea from the highlands of Kericho. "
                "Delicate flavor with grassy notes and a clean finish. "
                "Steamed and rolled in small batches."
            ),
            category="Green Tea",
            origin="Kericho, Kenya",
            price=Decimal("15.00"),
            cost=Decimal("6.20"),
            stock_quantity=12,
            low_stock_threshold=8,
            unit="tin",
        ),
        Product(
            id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            seller_id=MAHABA_TEA_ID,
            sku="MH-BLK-50",
            name="Kenya Black Tea",
            description=(
                "Bold, full-bodied black tea from the famous tea estates "
                "of the Kenyan highlands. Bright copper liquor with malty "
                "notes and a brisk finish. Perfect with or without milk."
            ),
            category="Black Tea",
            origin="Limuru, Kenya",
            price=Decimal("14.00"),
            cost=Decimal("5.80"),
            stock_quantity=8,
            low_stock_threshold=8,
            unit="tin",
        ),
        Product(
            id=UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
            seller_id=MAHABA_TEA_ID,
            sku="MH-WHT-50",
            name="Silver Needle White Tea",
            description=(
                "Exquisite white tea made from tender buds only. "
                "Subtle, honey-like sweetness with floral undertones. "
                "Limited harvest from select Kenyan tea gardens."
            ),
            category="White Tea",
            origin="Nandi Hills, Kenya",
            price=Decimal("24.00"),
            cost=Decimal("10.50"),
            stock_quantity=4,
            low_stock_threshold=5,
            unit="tin",
        ),
        Product(
            id=UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
            seller_id=MAHABA_TEA_ID,
            sku="MH-CHA-100",
            name="Kenyan Chai Masala",
            description=(
                "Traditional chai spice blend with Kenyan black tea, "
                "cardamom, cinnamon, ginger, and cloves. Ready to brew "
                "with milk for authentic masala chai."
            ),
            category="Chai",
            origin="Kenya Blend",
            price=Decimal("16.00"),
            cost=Decimal("6.80"),
            stock_quantity=15,
            low_stock_threshold=10,
            unit="tin",
        ),
        Product(
            id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            seller_id=MAHABA_TEA_ID,
            sku="MH-SAM-3",
            name="Tea Discovery Sampler",
            description=(
                "Explore Kenyan tea with this curated sampler: "
                "Purple Tea, Green Tea, and Black Tea. Three 25g tins "
                "in a gift-ready box. Perfect for tea lovers."
            ),
            category="Gift Set",
            origin="Kenya",
            price=Decimal("28.00"),
            cost=Decimal("11.50"),
            stock_quantity=10,
            low_stock_threshold=5,
            unit="set",
        ),
    ]


def create_mahaba_tea_policy() -> Policy:
    """Create business policies for Mahaba Tea Co."""
    return Policy(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        seller_id=MAHABA_TEA_ID,
        margin_floor=0.45,  # 45% minimum margin
        bundle_discount_percent=0.05,  # 5% off for bundles
        max_bundle_discount_percent=0.10,  # Max 10% bundle discount
        shipping_note=(
            "Ships within 2-3 business days from our US fulfillment center. "
            "Free shipping on orders over $50."
        ),
        free_shipping_threshold=Decimal("50.00"),
        returns_note=(
            "30-day returns for unopened items. "
            "We want you to love your tea — contact us if you're not satisfied."
        ),
    )


def create_demo_conversation() -> Conversation:
    """Create a sample conversation for the demo."""
    conversation = Conversation(
        id=DEMO_CONVERSATION_ID,
        seller_id=MAHABA_TEA_ID,
        customer_name="Dana R.",
        customer_initials="DR",
        channel="Storefront chat",
        status=ConversationStatus.AWAITING_REPLY,
    )

    # Add the initial customer message
    conversation.add_message(
        direction=MessageDirection.INBOUND,
        sender_name="Dana R.",
        body="Do you have the purple tea in stock? Can you do a bundle?",
    )

    return conversation


def get_demo_seller() -> tuple[Seller, list[Product], Policy]:
    """Get all demo data for Mahaba Tea Co.

    Returns:
        Tuple of (seller, products, policy)
    """
    seller = create_mahaba_tea_seller()
    products = create_mahaba_tea_products()
    policy = create_mahaba_tea_policy()
    return seller, products, policy


def seed_demo_data() -> dict:
    """Seed all demo data and return it as a dictionary.

    Returns:
        Dictionary containing all seeded entities.
    """
    seller, products, policy = get_demo_seller()
    conversation = create_demo_conversation()

    return {
        "seller": seller,
        "products": products,
        "policy": policy,
        "conversation": conversation,
    }


# Convenience accessors for the demo
def get_product_by_sku(products: list[Product], sku: str) -> Product | None:
    """Find a product by SKU."""
    for product in products:
        if product.sku == sku:
            return product
    return None


def get_product_by_name(products: list[Product], name: str) -> Product | None:
    """Find a product by name (case-insensitive partial match)."""
    name_lower = name.lower()
    for product in products:
        if name_lower in product.name.lower():
            return product
    return None
