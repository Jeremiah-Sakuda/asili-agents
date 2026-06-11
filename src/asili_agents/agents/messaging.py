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

MESSAGING_INSTRUCTION = """You are the Messaging Agent for {seller_name}, a {seller_category} seller.

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

# MCP-mode instruction. In MCP mode the in-process catalog_search/check_stock
# tools are NOT registered (the MongoDB MCP toolset replaces them), so this
# variant must never name them — otherwise the model can call an unregistered
# tool and the run fails. It references only log_decision (still registered) and
# reads via the MongoDB tools described in MCP_GROUNDING_INSTRUCTION, which is
# appended after formatting (it contains literal braces, so it must not be
# passed through str.format()).
MESSAGING_INSTRUCTION_MCP = """You are the Messaging Agent for {seller_name}, a {seller_category} seller.

Your role is to handle customer conversations, ensuring every response is grounded in the seller's live catalog read from MongoDB.

## Core Rules

1. **NEVER hallucinate product information.** Read the catalog from MongoDB before mentioning any product.
2. **NEVER guess stock levels.** Read the live `stock_quantity` from MongoDB before telling a customer about availability.
3. **Be warm and helpful.** Match the brand voice: {brand_voice}
4. **Be concise.** Customers appreciate clear, direct answers.

## Workflow

When handling a customer message:

1. **Identify the intent**: What is the customer asking about?
2. **Read from MongoDB**: use the MongoDB tools (see the data-access section below) to look up the product(s) and their live stock — never recall a number from memory.
3. **Log your findings**: use `log_decision` with agent_name "Messaging", agent_role "Catalog grounding", step_type "ground", and grounded_facts (e.g. ["product", "stock"]).
4. **Compose your response**: based ONLY on what you read from MongoDB.

## Important

- If a product is not found after a broad search, say so honestly.
- If stock is low, mention it (e.g., "we're down to the last few").
- If you're asked about pricing bundles, note that you'll need the Pricing agent's help.

Remember: Your responses will be reviewed by the seller before sending. Accuracy is paramount.
"""


def create_messaging_agent(
    seller_name: str = "Mahaba Tea Co.",
    brand_voice: str = "warm and knowledgeable",
    use_mcp: bool | None = None,
    seller_category: str = "specialty goods",
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
        seller_category=seller_category,
    )
    tools: list = [catalog_search, check_stock, log_decision]

    if resolve_use_mcp(use_mcp, settings):
        toolset = make_mongodb_mcp_toolset(settings)
        if toolset is not None:
            # MongoDB MCP becomes the agent's only catalog/stock data path. Use
            # the MCP-specific instruction so the prompt names ONLY the MongoDB
            # tools — never the now-unregistered catalog_search/check_stock.
            tools = [toolset, log_decision]
            instruction = (
                MESSAGING_INSTRUCTION_MCP.format(
                    seller_name=seller_name,
                    brand_voice=brand_voice,
                    seller_category=seller_category,
                )
                + MCP_GROUNDING_INSTRUCTION
            )

    return LlmAgent(
        name="messaging_agent",
        model=settings.gemini_model_routine,
        description=(
            "Handles customer conversations with catalog-grounded responses. "
            "Use this agent to answer product questions, check availability, "
            "and compose helpful replies. Never invents product details."
        ),
        instruction=instruction,
        tools=tools,
    )
