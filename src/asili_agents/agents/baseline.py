"""Monolithic Baseline Agent for comparison.

This agent demonstrates what happens when you use a single LLM
without grounding or tools. It's designed to fail in predictable
ways — hallucinating stock and quoting below-margin prices.

The baseline is essential for the demo: it proves that the
multi-agent system provides real value over a naive approach.
"""

from google.adk.agents import LlmAgent

from asili_agents.config import get_settings


BASELINE_INSTRUCTION = """You are a helpful assistant for {seller_name}, a specialty tea seller.

Answer customer questions about products and pricing.

## Product Catalog

Here is our catalog:
{catalog_dump}

## Guidelines

- Be helpful and friendly
- Answer questions about products
- Offer bundle deals when appropriate
- Be confident in your responses

Note: You do not have access to real-time inventory or pricing tools.
Use your best judgment based on the catalog information above.
"""


def create_baseline_agent(
    seller_name: str = "Mahaba Tea Co.",
    catalog_dump: str = "",
) -> LlmAgent:
    """Create the monolithic baseline agent.

    This agent has NO tools — it must rely entirely on the catalog
    dump in its context and its own (unreliable) reasoning.

    Expected failure modes:
    1. Hallucinating stock levels (no check_stock tool)
    2. Calculating unsafe prices (no compute_bundle_price tool)
    3. Inventing product details (no catalog_search tool)

    Args:
        seller_name: Name of the seller business.
        catalog_dump: Raw text dump of the catalog (simulating
            a naive approach of stuffing context with data).

    Returns:
        Configured LlmAgent without any tools.
    """
    settings = get_settings()

    return LlmAgent(
        name="baseline_agent",
        model=settings.gemini_model,
        description=(
            "A single-agent baseline for comparison. No tools, no grounding, "
            "just raw LLM responses. Used to demonstrate failure modes."
        ),
        instruction=BASELINE_INSTRUCTION.format(
            seller_name=seller_name,
            catalog_dump=catalog_dump or _get_default_catalog_dump(),
        ),
        tools=[],  # Intentionally empty — this is the point
    )


def _get_default_catalog_dump() -> str:
    """Generate a basic catalog dump for the baseline.

    This simulates stuffing product info into the prompt —
    a common but unreliable approach.
    """
    return """
Purple Tea - $18.00/tin
  Rare purple-leaf tea from Nandi Hills, Kenya.
  Rich in anthocyanins, smooth and slightly sweet.

Kenyan Green Tea - $15.00/tin
  Fresh green tea from Kericho highlands.
  Delicate flavor with grassy notes.

Kenya Black Tea - $14.00/tin
  Bold black tea from Limuru.
  Bright copper liquor, malty notes.

Silver Needle White Tea - $24.00/tin
  Exquisite white tea from tender buds.
  Subtle honey sweetness with floral notes.

Kenyan Chai Masala - $16.00/tin
  Traditional chai blend with black tea and spices.
  Perfect for masala chai.

Tea Discovery Sampler - $28.00/set
  Three 25g tins: Purple, Green, and Black tea.
  Gift-ready presentation.

Bundle Policy: We offer 5-10% discounts on bundles.
"""


def generate_catalog_dump_from_products(products: list) -> str:
    """Generate a catalog dump from actual product data.

    Args:
        products: List of Product models.

    Returns:
        Text dump of the catalog for the baseline agent.
    """
    lines = []
    for p in products:
        lines.append(f"{p.name} - ${p.price:.2f}/{p.unit}")
        lines.append(f"  {p.description}")
        lines.append("")

    lines.append("Bundle Policy: We offer 5-10% discounts on bundles.")

    return "\n".join(lines)
