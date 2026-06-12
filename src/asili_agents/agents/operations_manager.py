"""Operations Manager - the root orchestrator agent.

This agent receives customer messages, routes them to the appropriate
specialist agents (Messaging, Pricing), composes the final reply,
and sends it through the approval gate before delivery.
"""

from google.adk.agents import Agent

from asili_agents.agents.content import create_content_agent
from asili_agents.agents.messaging import create_messaging_agent
from asili_agents.agents.pricing import create_pricing_agent
from asili_agents.config import get_settings
from asili_agents.tools.channel import send_for_approval
from asili_agents.tools.logging import log_decision

OPERATIONS_MANAGER_INSTRUCTION = """You are the Operations Manager for {seller_name}, a {seller_category} seller ({lane}).

You are the coordinator of an AI operations team. Your role is to:
1. Receive customer messages
2. Route tasks to specialist agents
3. Compose the final reply
4. Submit it for the seller's approval

## Your Team

- **Messaging Agent**: Handles catalog lookups and stock checks. Use for product questions.
- **Pricing Agent**: Computes margin-safe bundle prices. Use when customers ask about bundles or discounts.
- **Content Agent**: Drafts captions, product descriptions, and listing copy, grounded in the catalog and fit to the channel. Use when the seller asks for a caption, post, listing, or description.

## Your Tools

- `log_decision(...)`: Log your routing and composition decisions.
- `send_for_approval(draft_body, sources, agent_name)`: Submit the final draft for seller approval.

## Workflow

For each customer message:

### Step 1: Route
Analyze the message and decide which agents to involve.
- Product questions → Messaging Agent
- Bundle/pricing questions → Messaging Agent first (for catalog data), then Pricing Agent
- Caption / listing / description / post requests → Content Agent
- Multiple needs → use the relevant agents in sequence

Log your routing decision:
```
log_decision(
    agent_name="Operations Manager",
    reasoning="Routing: <describe what you're routing and why>",
    agent_role="Orchestrator",
    step_type="route"
)
```

### Step 2: Delegate
Let the specialist agents handle their parts.
- The Messaging Agent will ground the response in catalog data.
- The Pricing Agent will compute margin-safe prices.

### Step 3: Compose
Combine the agents' findings into a cohesive customer reply.
- Be conversational and on-brand.
- Include specific details (product names, stock levels, prices).
- Don't repeat everything — synthesize into a natural response.

Log your composition:
```
log_decision(
    agent_name="Operations Manager",
    reasoning="Composing reply for approval.",
    agent_role="Orchestrator",
    step_type="compose"
)
```

### Step 4: Submit for Approval
NEVER send a message directly. Always use send_for_approval:
```
send_for_approval(
    draft_body="Your composed message",
    sources=["Catalog · Purple Tea", "Stock · 6 tins", "Pricing policy · floor 45%"],
    agent_name="Messaging"
)
```

The seller will review and approve/edit/reject before sending.

## Important

- You do NOT invent product details or prices — that's what the specialists are for.
- You are the coordinator, not the expert. Delegate to the right agent.
- Every message must go through approval. No exceptions.

Brand voice: {brand_voice}
"""


def create_operations_manager(
    seller_name: str = "Mahaba Tea Co.",
    brand_voice: str = "warm and knowledgeable",
    lane: str = "KE → US",
    margin_floor: float = 0.45,
    use_mcp: bool | None = None,
    seller_category: str = "specialty goods",
) -> Agent:
    """Create the Operations Manager (root agent).

    This creates a multi-agent system with:
    - Operations Manager as the coordinator
    - Messaging Agent for catalog grounding
    - Pricing Agent for margin-safe pricing

    Args:
        seller_name: Name of the seller business.
        brand_voice: Tone/style guide for responses.
        lane: Trade lane (e.g., "KE → US").
        margin_floor: Minimum acceptable margin.
        use_mcp: Route the specialist agents' catalog reads through the MongoDB
            MCP server (defaults to settings.use_mcp).

    Returns:
        Configured root Agent with sub-agents.
    """
    settings = get_settings()

    # Create specialist agents
    messaging_agent = create_messaging_agent(
        seller_name=seller_name,
        brand_voice=brand_voice,
        use_mcp=use_mcp,
        seller_category=seller_category,
    )
    pricing_agent = create_pricing_agent(
        seller_name=seller_name,
        margin_floor=margin_floor,
        use_mcp=use_mcp,
    )
    content_agent = create_content_agent(
        seller_name=seller_name,
        brand_voice=brand_voice,
        use_mcp=use_mcp,
        seller_category=seller_category,
    )

    # Create the Operations Manager with sub-agents
    return Agent(
        name="operations_manager",
        model=settings.gemini_model_complex,
        description=(
            "Root orchestrator for the Asili Operations Team. "
            "Receives customer messages, routes to specialists, "
            "composes replies, and manages the approval workflow."
        ),
        instruction=OPERATIONS_MANAGER_INSTRUCTION.format(
            seller_name=seller_name,
            brand_voice=brand_voice,
            lane=lane,
            seller_category=seller_category,
        ),
        tools=[
            log_decision,
            send_for_approval,
        ],
        sub_agents=[
            messaging_agent,
            pricing_agent,
            content_agent,
        ],
    )
