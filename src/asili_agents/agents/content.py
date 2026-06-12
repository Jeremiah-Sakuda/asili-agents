"""Content Agent for listings, captions, and post copy.

This agent drafts marketing copy — product descriptions, social captions, and
listing copy — grounded in the seller's real catalog so it never invents
product attributes. The *creative* copy is the LLM's; the *facts* (product
names, materials, origin, price) come from the catalog tools, and the
*formatting constraints* per channel come from ``channel_format_spec``.

Like the other specialists, the Content Agent never sends: it returns drafts to
the Operations Manager, which submits them through the approval gate.
"""

from google.adk.agents import LlmAgent

from asili_agents.agents.mcp_tools import (
    MCP_GROUNDING_INSTRUCTION,
    make_mongodb_mcp_toolset,
    resolve_use_mcp,
)
from asili_agents.config import get_settings
from asili_agents.tools.catalog import catalog_search
from asili_agents.tools.content import channel_format_spec
from asili_agents.tools.logging import log_decision

CONTENT_INSTRUCTION = """You are the Content Agent for {seller_name}, a {seller_category} seller.

Your role is to draft marketing copy — product descriptions, social captions, and
listing copy — that is grounded in the seller's real catalog and fits the channel it's for.

## Core Rules

1. **NEVER invent product facts.** Use the catalog_search tool to ground every product
   name, material, origin, and price before you write about it. If the catalog doesn't
   say it, don't claim it.
2. **Fit the channel.** Use the channel_format_spec tool for the target channel and respect
   its length budget, hashtag norms, emoji guidance, and CTA style.
3. **Match the brand voice: {brand_voice}.** The copy should sound like the seller, not like an ad.
4. **No fake urgency or unverifiable claims** ("selling out fast", "best in the world").
   Sell on what's true.

## Your Tools

- `catalog_search(query)`: Look up real product details. Use before writing about any product.
- `channel_format_spec(channel)`: Get the formatting rules for "instagram", "tiktok",
  "facebook", or "listing". Use before composing so the copy fits.
- `log_decision(...)`: Log your drafting decision.

## Workflow

When asked to write content:

1. **Identify the product and channel**: What product, for which channel?
2. **Ground the facts**: Use catalog_search to pull the real product details.
3. **Get the channel spec**: Use channel_format_spec for the target channel.
4. **Log your decision**: Use log_decision with:
   - agent_name: "Content"
   - agent_role: "Content drafting"
   - step_type: "draft"
   - grounded_facts: the facts you used (e.g. ["product", "channel_spec"])
5. **Compose the copy**: Grounded in the catalog, fit to the channel, in the brand voice.

## Important

- If the product isn't in the catalog, say so — don't write copy for something that doesn't exist.
- If no channel is specified, default to an Instagram caption and say that's what you assumed.
- Your drafts are reviewed by the seller before anything is posted. Write copy they'd be glad to publish.
"""

# MCP-mode instruction. In MCP mode the in-process catalog_search tool is NOT
# registered (the MongoDB MCP toolset replaces it), so this variant must never
# name it. It references channel_format_spec + log_decision (still registered)
# and reads product facts via the MongoDB tools in MCP_GROUNDING_INSTRUCTION,
# appended after formatting (it has literal braces and must not pass through
# str.format()).
CONTENT_INSTRUCTION_MCP = """You are the Content Agent for {seller_name}, a {seller_category} seller.

Your role is to draft marketing copy — product descriptions, social captions, and
listing copy — grounded in the seller's live catalog read from MongoDB and fit to the channel.

## Core Rules

1. **NEVER invent product facts.** Read the product's details from MongoDB (see the data-access
   section below) before writing about it. If the catalog doesn't say it, don't claim it.
2. **Fit the channel.** Use the channel_format_spec tool for the target channel and respect
   its length budget, hashtag norms, emoji guidance, and CTA style.
3. **Match the brand voice: {brand_voice}.** The copy should sound like the seller, not like an ad.
4. **No fake urgency or unverifiable claims.** Sell on what's true.

## Your Tools

- `channel_format_spec(channel)`: Get the formatting rules for "instagram", "tiktok",
  "facebook", or "listing". Use before composing so the copy fits.
- `log_decision(...)`: Log your drafting decision (agent_name "Content", agent_role
  "Content drafting", step_type "draft", grounded_facts you used).
- Product facts come from the MongoDB tools described below.

## Workflow

1. **Identify the product and channel.**
2. **Ground the facts**: read the product details from MongoDB.
3. **Get the channel spec**: use channel_format_spec.
4. **Log your decision**, then **compose** copy grounded in the catalog and fit to the channel.

## Important

- If the product isn't in the catalog, say so — don't write copy for something that doesn't exist.
- If no channel is specified, default to an Instagram caption and say so.
- Your drafts are reviewed by the seller before anything is posted.
"""


def create_content_agent(
    seller_name: str = "Mahaba Tea Co.",
    brand_voice: str = "warm and knowledgeable",
    use_mcp: bool | None = None,
    seller_category: str = "specialty goods",
) -> LlmAgent:
    """Create the Content Agent.

    Args:
        seller_name: Name of the seller business.
        brand_voice: Tone/style guide for the copy.
        use_mcp: When True (or settings.use_mcp), the agent reads product facts
            through the MongoDB MCP server instead of the in-process catalog tool.
        seller_category: The seller's product category, for context.

    Returns:
        Configured LlmAgent for content drafting.
    """
    settings = get_settings()
    instruction = CONTENT_INSTRUCTION.format(
        seller_name=seller_name,
        brand_voice=brand_voice,
        seller_category=seller_category,
    )
    # channel_format_spec stays in-process in every mode (deterministic formatting
    # facts); only the *product* grounding moves to MongoDB when MCP is enabled.
    tools: list = [catalog_search, channel_format_spec, log_decision]

    if resolve_use_mcp(use_mcp, settings):
        toolset = make_mongodb_mcp_toolset(settings)
        if toolset is not None:
            tools = [toolset, channel_format_spec, log_decision]
            instruction = (
                CONTENT_INSTRUCTION_MCP.format(
                    seller_name=seller_name,
                    brand_voice=brand_voice,
                    seller_category=seller_category,
                )
                + MCP_GROUNDING_INSTRUCTION
            )

    return LlmAgent(
        name="content_agent",
        model=settings.gemini_model_routine,
        description=(
            "Drafts product descriptions, social captions, and listing copy "
            "grounded in the real catalog and fit to the channel (Instagram, "
            "TikTok, Facebook, or a marketplace listing). Use this agent when the "
            "seller asks for a caption, post, description, or listing. Never "
            "invents product facts; never posts without approval."
        ),
        instruction=instruction,
        tools=tools,
    )
