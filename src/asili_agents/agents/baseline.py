"""Single-agent baseline for comparison.

This is a *fair* control: a single LLM that is given the full catalog snapshot —
including stock and cost — and the 45% margin rule, then asked to answer
accurately. It is not starved of data; what it lacks is the team's structural
advantages: live read-only grounding (so it recalls stock instead of reading it)
and a deterministic pricing tool (so it does margin arithmetic in its head). The
team-vs-baseline delta therefore measures *architecture*, not an information gap.
"""

from google.adk.agents import LlmAgent

from asili_agents.config import get_settings

BASELINE_INSTRUCTION = """You are the customer-service assistant for {seller_name}, a specialty tea seller.

Answer customer questions about products, availability, and pricing as accurately and helpfully as you can.

## Product catalog (current snapshot — name, price, cost, stock, description)

{catalog_dump}

## Pricing policy

- Keep a minimum **45% gross margin** on every sale. Margin = (price - cost) / price.
- Bundles may take a small discount (around 5%), but never below the 45% margin floor.

## Guidelines

- Be helpful, friendly, and accurate.
- Use the snapshot above to answer about availability and to work out any bundle price.
- Give the customer a clear, confident answer.

(You are a single assistant working from the snapshot above — you have no live
database lookups or calculator tools, so reason carefully from what's given.)
"""


def create_baseline_agent(
    seller_name: str = "Mahaba Tea Co.",
    catalog_dump: str = "",
) -> LlmAgent:
    """Create the single-agent baseline.

    The agent has NO tools — it answers from the catalog snapshot in its prompt
    and its own reasoning. It has the same facts the team can read (stock, cost,
    margin rule); it simply lacks live grounding and the deterministic pricing
    engine, which is the whole point of the comparison.

    Typical failure modes despite having the data:
    1. Recalling a stock number incorrectly (no live ``check_stock``).
    2. Doing margin arithmetic in its head and slipping below the floor
       (no deterministic ``compute_bundle_price``).

    Args:
        seller_name: Name of the seller business.
        catalog_dump: Catalog snapshot (name/price/cost/stock/description).

    Returns:
        Configured LlmAgent without any tools.
    """
    settings = get_settings()

    return LlmAgent(
        name="baseline_agent",
        model=settings.gemini_model,
        description=(
            "A single-agent baseline for comparison: full catalog in the prompt "
            "but no live grounding and no deterministic pricing tool."
        ),
        instruction=BASELINE_INSTRUCTION.format(
            seller_name=seller_name,
            catalog_dump=catalog_dump or _get_default_catalog_dump(),
        ),
        tools=[],  # Intentionally empty — this is the point.
    )


def _get_default_catalog_dump() -> str:
    """Catalog snapshot fallback (mirrors the Mahaba Tea Co. seed)."""
    return """
Purple Tea — $18.00/tin (cost $7.40, stock 6 tins)
  Rare purple-leaf tea from Nandi Hills, Kenya. Smooth and slightly sweet.

Kenyan Green Tea — $15.00/tin (cost $6.20, stock 12 tins)
  Fresh green tea from Kericho highlands. Delicate, grassy notes.

Kenya Black Tea — $14.00/tin (cost $5.80, stock 8 tins)
  Bold black tea from Limuru. Bright copper liquor, malty notes.

Silver Needle White Tea — $24.00/tin (cost $10.50, stock 4 tins)
  Exquisite white tea from tender buds. Subtle honey sweetness.

Kenyan Chai Masala — $16.00/tin (cost $6.80, stock 15 tins)
  Traditional chai blend with black tea and spices.

Tea Discovery Sampler — $28.00/set (cost $11.50, stock 10 sets)
  Three 25g tins: Purple, Green, and Black tea. Gift-ready.

Pricing policy: keep a minimum 45% gross margin; bundle discounts ~5% but never below the floor.
"""


def generate_catalog_dump_from_products(products: list) -> str:
    """Generate a catalog snapshot (incl. stock + cost) from product data.

    Args:
        products: List of Product models.

    Returns:
        Text snapshot of the catalog for the baseline agent — the same facts the
        grounded team can read, so the comparison is fair.
    """
    lines = []
    for p in products:
        lines.append(
            f"{p.name} — ${p.price:.2f}/{p.unit} "
            f"(cost ${p.cost:.2f}, stock {p.stock_quantity} {p.unit}s)"
        )
        lines.append(f"  {p.description}")
        lines.append("")

    lines.append(
        "Pricing policy: keep a minimum 45% gross margin; "
        "bundle discounts ~5% but never below the floor."
    )

    return "\n".join(lines)
