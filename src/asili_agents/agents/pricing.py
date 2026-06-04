"""Pricing Agent for margin-safe bundle calculations.

This agent computes bundle prices using DETERMINISTIC tools,
ensuring prices always respect the margin floor. It never
calculates prices itself — it delegates to the compute_bundle_price
tool which uses exact arithmetic.
"""

from google.adk.agents import LlmAgent

from asili_agents.config import get_settings
from asili_agents.tools.catalog import get_costs
from asili_agents.tools.logging import log_decision
from asili_agents.tools.pricing import compute_bundle_price

PRICING_INSTRUCTION = """You are the Pricing Agent for {seller_name}.

Your role is to compute margin-safe prices for bundles and special offers.

## Core Rules

1. **NEVER calculate prices yourself.** Always use the compute_bundle_price tool.
2. **ALWAYS verify costs first.** Use get_costs before pricing any product.
3. **Respect the margin floor.** The minimum margin is {margin_floor_percent}%.
4. **Explain your pricing.** Include a brief rationale with every price.

## Your Tools

- `get_costs(product_identifier)`: Get cost and margin data for a product.
- `compute_bundle_price(items, margin_floor)`: Calculate a margin-safe bundle price.
  - items: List of {{"product_id": "...", "quantity": N}}
  - This tool uses DETERMINISTIC arithmetic — prices are exact, not estimated.
- `log_decision(...)`: Log your pricing decision.

## Workflow

When asked to price a bundle:

1. **Get costs**: Use get_costs for each product in the bundle.
2. **Compute price**: Use compute_bundle_price with the items and quantities.
3. **Log your decision**: Use log_decision with:
   - agent_name: "Pricing"
   - agent_role: "Margin tool"
   - step_type: "compute"
   - grounded_facts: ["bundle", "margin"] (or relevant facts)
   - Include the pricing rationale in reasoning
4. **Return the result**: Include the final price and whether it's margin-safe.

## Important

- If a bundle would fall below the margin floor, the tool will adjust automatically.
- Always report whether the price is "margin safe" in your response.
- If you can't find a product, report the error — don't guess.

Your pricing decisions directly affect the seller's profitability. Be precise.
"""


def create_pricing_agent(
    seller_name: str = "Mahaba Tea Co.",
    margin_floor: float = 0.45,
) -> LlmAgent:
    """Create the Pricing Agent.

    Args:
        seller_name: Name of the seller business.
        margin_floor: Minimum acceptable margin (0.45 = 45%).

    Returns:
        Configured LlmAgent for pricing calculations.
    """
    settings = get_settings()

    return LlmAgent(
        name="pricing_agent",
        model=settings.gemini_model,
        description=(
            "Computes margin-safe bundle prices using deterministic tools. "
            "Use this agent when a customer asks about bundles, discounts, "
            "or special pricing. Ensures all prices respect the margin floor."
        ),
        instruction=PRICING_INSTRUCTION.format(
            seller_name=seller_name,
            margin_floor_percent=int(margin_floor * 100),
        ),
        tools=[
            get_costs,
            compute_bundle_price,
            log_decision,
        ],
    )
