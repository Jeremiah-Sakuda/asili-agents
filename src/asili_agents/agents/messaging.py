"""Messaging Agent for customer communication.

This agent handles customer conversations, grounded in the seller's catalog
and policies. It uses catalog_search and check_stock tools to ensure
responses are factually accurate — never hallucinating inventory.
"""

from google.adk.agents import LlmAgent

from asili_agents.agents.mcp_tools import (
    MCP_GROUNDING_INSTRUCTION,
    make_mongodb_mcp_toolset,
    resolve_use_mcp,
)
from asili_agents.config import get_settings
from asili_agents.tools.catalog import catalog_search, check_stock
from asili_agents.tools.logging import log_decision

MESSAGING_INSTRUCTION = """You are the Messaging Agent for {seller_name}, a specialty tea seller.

Your role is to handle customer conversations, ensuring every response is grounded in real catalog data.

## Core Rules

1. **NEVER hallucinate product information.** Always use the catalog_search tool before mentioning any product.
2. **NEVER guess stock levels.** Always use the check_stock tool before telling a customer about availability.
3. **Be warm and helpful.** Match the brand voice: {brand_voice}
4. **Be concise.** Customers appreciate clear, direct answers.

## Your Tools

- `catalog_search(query)`: Search for products. Use this before mentioning any product.
- `check_stock(product_identifier)`: Check real stock levels. Use this before discussing availability.
- `log_decision(...)`: Log your reasoning for observability.

## Workflow

When handling a customer message:

1. **Identify the intent**: What is the customer asking about?
2. **Search the catalog**: Use catalog_search to find relevant products.
3. **Check stock**: Use check_stock for any products you'll mention.
4. **Log your findings**: Use log_decision with:
   - agent_name: "Messaging"
   - agent_role: "Catalog grounding"
   - step_type: "ground"
   - grounded_facts: List the fact IDs you verified (e.g., ["product", "stock"])
5. **Compose your response**: Based ONLY on verified data.

## Important

- If a product is not found, say so honestly.
- If stock is low, mention it (e.g., "we're down to the last few").
- If you're asked about pricing bundles, note that you'll need the Pricing agent's help.

Remember: Your responses will be reviewed by the seller before sending. Accuracy is paramount.
"""


def create_messaging_agent(
    seller_name: str = "Mahaba Tea Co.",
    brand_voice: str = "warm and knowledgeable about tea",
    use_mcp: bool | None = None,
) -> LlmAgent:
    """Create the Messaging Agent.

    Args:
        seller_name: Name of the seller business.
        brand_voice: Tone/style guide for responses.
        use_mcp: When True (or when settings.use_mcp is True), the agent reads
            the catalog through the MongoDB MCP server instead of the in-process
            catalog tools. Falls back to the in-process tools if MongoDB is not
            configured.

    Returns:
        Configured LlmAgent for customer messaging.
    """
    settings = get_settings()
    instruction = MESSAGING_INSTRUCTION.format(
        seller_name=seller_name,
        brand_voice=brand_voice,
    )
    tools: list = [catalog_search, check_stock, log_decision]

    if resolve_use_mcp(use_mcp, settings):
        toolset = make_mongodb_mcp_toolset(settings)
        if toolset is not None:
            # MongoDB MCP becomes the agent's only catalog/stock data path.
            tools = [toolset, log_decision]
            instruction = instruction + MCP_GROUNDING_INSTRUCTION

    return LlmAgent(
        name="messaging_agent",
        model=settings.gemini_model,
        description=(
            "Handles customer conversations with catalog-grounded responses. "
            "Use this agent to answer product questions, check availability, "
            "and compose helpful replies. Never invents product details."
        ),
        instruction=instruction,
        tools=tools,
    )
