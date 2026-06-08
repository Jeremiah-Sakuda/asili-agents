"""Additional demo tenants for the Asili Agents multi-seller showcase.

This module adds two more demo sellers alongside Mahaba Tea Co. so the
multi-agent system can be demonstrated as multi-tenant:

- Mama Ngozi Foods: Nigerian shea butter + palm-oil seller (NG → US)
- Ti Piment: Haitian hot-sauce maker (HT → US)

Each tenant mirrors the structure of ``asili_agents.data.seed`` and uses the
exact same pydantic models (Seller, Product, Policy). All data is grounded,
with realistic price/cost/stock (some items intentionally low stock) and a
45% margin floor so the deterministic pricing engine has room to work.
"""

from decimal import Decimal
from uuid import UUID

from asili_agents.data.models import Policy, Product, Seller
from asili_agents.data.seed import get_demo_seller

# Fixed UUIDs for consistent demo data (distinct from Mahaba's 1111.../aaaa...)
MAMA_NGOZI_ID = UUID("33333333-3333-3333-3333-333333333333")
TI_PIMENT_ID = UUID("44444444-4444-4444-4444-444444444444")


def create_mama_ngozi_seller() -> Seller:
    """Create the Mama Ngozi Foods seller."""
    return Seller(
        id=MAMA_NGOZI_ID,
        name="Mama Ngozi Foods",
        category="West African shea butter & pantry goods",
        brand_voice=(
            "Warm, motherly, and proud of West African heritage. We speak about "
            "shea and palm with the care of a family kitchen, sharing how each "
            "product is sourced and used. Generous and reassuring, never pushy."
        ),
        origin_country="NG",
        destination_country="US",
        currency="USD",
    )


def create_mama_ngozi_products() -> list[Product]:
    """Create the product catalog for Mama Ngozi Foods.

    Products are based on staple Nigerian shea and palm goods with realistic
    direct-to-consumer pricing. Some items are intentionally low stock.
    """
    return [
        Product(
            id=UUID("a1111111-0000-0000-0000-000000000001"),
            seller_id=MAMA_NGOZI_ID,
            sku="MN-SHB-16",
            name="Raw Unrefined Shea Butter",
            description=(
                "Hand-churned ivory shea butter from northern Nigeria, "
                "unrefined and unscented. Deeply moisturizing for skin and "
                "hair, sourced directly from a women's cooperative."
            ),
            category="Shea Butter",
            origin="Kano, Nigeria",
            price=Decimal("22.00"),
            cost=Decimal("9.00"),
            stock_quantity=5,
            low_stock_threshold=8,
            unit="jar",
        ),
        Product(
            id=UUID("a1111111-0000-0000-0000-000000000002"),
            seller_id=MAMA_NGOZI_ID,
            sku="MN-WSB-8",
            name="Whipped Shea Body Butter",
            description=(
                "Light, fluffy whipped shea blended with a touch of coconut "
                "oil. Absorbs quickly with a soft, natural finish. Perfect "
                "for daily moisture without greasiness."
            ),
            category="Shea Butter",
            origin="Kano, Nigeria",
            price=Decimal("18.00"),
            cost=Decimal("7.20"),
            stock_quantity=14,
            low_stock_threshold=8,
            unit="jar",
        ),
        Product(
            id=UUID("a1111111-0000-0000-0000-000000000003"),
            seller_id=MAMA_NGOZI_ID,
            sku="MN-RPO-500",
            name="Red Palm Oil",
            description=(
                "Traditional unrefined red palm oil, cold-pressed and rich "
                "in carotenoids. The authentic base for Nigerian soups and "
                "stews, with a deep color and earthy flavor."
            ),
            category="Cooking Oil",
            origin="Cross River, Nigeria",
            price=Decimal("16.00"),
            cost=Decimal("6.50"),
            stock_quantity=9,
            low_stock_threshold=8,
            unit="bottle",
        ),
        Product(
            id=UUID("a1111111-0000-0000-0000-000000000004"),
            seller_id=MAMA_NGOZI_ID,
            sku="MN-ABS-200",
            name="African Black Soap",
            description=(
                "Handmade dudu-osun-style black soap from plantain ash, "
                "cocoa pod, and shea. Gently cleanses and balances skin. "
                "Cut and wrapped by hand in small batches."
            ),
            category="Soap",
            origin="Lagos, Nigeria",
            price=Decimal("12.00"),
            cost=Decimal("4.80"),
            stock_quantity=20,
            low_stock_threshold=8,
            unit="bar",
        ),
        Product(
            id=UUID("a1111111-0000-0000-0000-000000000005"),
            seller_id=MAMA_NGOZI_ID,
            sku="MN-GFT-2",
            name="Shea & Black Soap Gift Set",
            description=(
                "A gift-ready pairing of raw shea butter and African black "
                "soap in a kraft box. A warm introduction to West African "
                "skincare for friends and family."
            ),
            category="Gift Set",
            origin="Nigeria",
            price=Decimal("30.00"),
            cost=Decimal("13.00"),
            stock_quantity=4,
            low_stock_threshold=5,
            unit="set",
        ),
    ]


def create_mama_ngozi_policy() -> Policy:
    """Create business policies for Mama Ngozi Foods."""
    return Policy(
        id=UUID("a1111111-9999-9999-9999-999999999999"),
        seller_id=MAMA_NGOZI_ID,
        margin_floor=0.45,
        bundle_discount_percent=0.05,
        max_bundle_discount_percent=0.10,
        shipping_note=(
            "Ships within 3-4 business days from our US warehouse. "
            "Free shipping on orders over $60."
        ),
        free_shipping_threshold=Decimal("60.00"),
        returns_note=(
            "30-day returns for unopened items. Because our products are "
            "natural and handmade, slight variations in color and scent are "
            "normal — reach out if anything isn't right."
        ),
    )


def create_ti_piment_seller() -> Seller:
    """Create the Ti Piment seller."""
    return Seller(
        id=TI_PIMENT_ID,
        name="Ti Piment",
        category="Haitian hot sauces & pantry goods",
        brand_voice=(
            "Bold, playful, and proudly Haitian. We talk heat with a wink — "
            "honest about how spicy each sauce really is and how to use it. "
            "Energetic and welcoming, like a friend handing you a plate."
        ),
        origin_country="HT",
        destination_country="US",
        currency="USD",
    )


def create_ti_piment_products() -> list[Product]:
    """Create the product catalog for Ti Piment.

    Products are based on classic Haitian condiments with realistic
    direct-to-consumer pricing. Some items are intentionally low stock.
    """
    return [
        Product(
            id=UUID("a2222222-0000-0000-0000-000000000001"),
            seller_id=TI_PIMENT_ID,
            sku="TP-PIK-5",
            name="Pikliz Hot Sauce",
            description=(
                "Our take on Haiti's beloved pikliz: crunchy pickled cabbage, "
                "carrot, and Scotch bonnet with a bright, vinegary bite. The "
                "perfect tangy heat for griot, fritay, and rice."
            ),
            category="Hot Sauce",
            origin="Port-au-Prince, Haiti",
            price=Decimal("11.00"),
            cost=Decimal("4.40"),
            stock_quantity=7,
            low_stock_threshold=8,
            unit="bottle",
        ),
        Product(
            id=UUID("a2222222-0000-0000-0000-000000000002"),
            seller_id=TI_PIMENT_ID,
            sku="TP-SCB-5",
            name="Scotch Bonnet Sauce",
            description=(
                "A fiery, fruit-forward sauce built on Haitian Scotch bonnet "
                "peppers, garlic, and lime. Serious heat with real flavor — "
                "a few drops wake up any dish."
            ),
            category="Hot Sauce",
            origin="Les Cayes, Haiti",
            price=Decimal("12.00"),
            cost=Decimal("4.80"),
            stock_quantity=16,
            low_stock_threshold=8,
            unit="bottle",
        ),
        Product(
            id=UUID("a2222222-0000-0000-0000-000000000003"),
            seller_id=TI_PIMENT_ID,
            sku="TP-EPI-8",
            name="Epis Green Seasoning",
            description=(
                "Epis is the soul of Haitian cooking: a vibrant blend of bell "
                "pepper, parsley, garlic, thyme, and scallion. Marinate meats "
                "or stir into rice and beans for instant depth."
            ),
            category="Seasoning",
            origin="Cap-Haïtien, Haiti",
            price=Decimal("13.00"),
            cost=Decimal("5.50"),
            stock_quantity=11,
            low_stock_threshold=8,
            unit="jar",
        ),
        Product(
            id=UUID("a2222222-0000-0000-0000-000000000004"),
            seller_id=TI_PIMENT_ID,
            sku="TP-MGH-5",
            name="Mango Habanero Sauce",
            description=(
                "Sweet Haitian mango meets habanero heat in a smooth, glossy "
                "sauce. Great on grilled chicken, plantains, or anything that "
                "needs a sweet-hot finish."
            ),
            category="Hot Sauce",
            origin="Jacmel, Haiti",
            price=Decimal("12.00"),
            cost=Decimal("4.90"),
            stock_quantity=5,
            low_stock_threshold=8,
            unit="bottle",
        ),
        Product(
            id=UUID("a2222222-0000-0000-0000-000000000005"),
            seller_id=TI_PIMENT_ID,
            sku="TP-TRO-3",
            name="Heat Lovers Trio Gift Set",
            description=(
                "Three of our boldest sauces — Pikliz, Scotch Bonnet, and "
                "Mango Habanero — in a gift-ready box. A guided tour of "
                "Haitian heat for the spice lover in your life."
            ),
            category="Gift Set",
            origin="Haiti",
            price=Decimal("32.00"),
            cost=Decimal("14.00"),
            stock_quantity=9,
            low_stock_threshold=5,
            unit="set",
        ),
    ]


def create_ti_piment_policy() -> Policy:
    """Create business policies for Ti Piment."""
    return Policy(
        id=UUID("a2222222-9999-9999-9999-999999999999"),
        seller_id=TI_PIMENT_ID,
        margin_floor=0.45,
        bundle_discount_percent=0.05,
        max_bundle_discount_percent=0.10,
        shipping_note=(
            "Ships within 2-3 business days from our US fulfillment center. "
            "Free shipping on orders over $45."
        ),
        free_shipping_threshold=Decimal("45.00"),
        returns_note=(
            "30-day returns for unopened bottles. If a sauce isn't your kind "
            "of heat, let us know and we'll make it right."
        ),
    )


def get_mama_ngozi_seller() -> tuple[Seller, list[Product], Policy]:
    """Get all demo data for Mama Ngozi Foods.

    Returns:
        Tuple of (seller, products, policy)
    """
    return (
        create_mama_ngozi_seller(),
        create_mama_ngozi_products(),
        create_mama_ngozi_policy(),
    )


def get_ti_piment_seller() -> tuple[Seller, list[Product], Policy]:
    """Get all demo data for Ti Piment.

    Returns:
        Tuple of (seller, products, policy)
    """
    return (
        create_ti_piment_seller(),
        create_ti_piment_products(),
        create_ti_piment_policy(),
    )


def get_all_sellers() -> list[tuple[Seller, list[Product], Policy]]:
    """Get demo data for every tenant, Mahaba Tea Co. first.

    Returns:
        List of (seller, products, policy) tuples for all demo tenants.
    """
    return [
        get_demo_seller(),
        get_mama_ngozi_seller(),
        get_ti_piment_seller(),
    ]
