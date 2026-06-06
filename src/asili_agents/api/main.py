"""FastAPI application for the Asili Operations Team.

This API provides:
1. Agent execution endpoints
2. Conversation management
3. Approval workflow
4. Demo runner
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from asili_agents.config import get_settings
from asili_agents.data.models import (
    Conversation,
    MessageDirection,
    MessageStatus,
)
from asili_agents.data.repository import set_catalog_repository
from asili_agents.data.seed import get_demo_seller
from asili_agents.eval.runner import build_live_reply_fns, run_scorecard
from asili_agents.runner import create_baseline_runner, create_runner, run_agent, run_baseline
from asili_agents.tools.catalog import check_stock, get_costs, set_product_store
from asili_agents.tools.channel import ApprovalResult, ApprovalStatus, set_approval_callback
from asili_agents.tools.logging import clear_decision_log, get_decision_log
from asili_agents.tools.pricing import compute_bundle_price, set_pricing_context

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Application state
_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application state on startup.

    If ``MONGODB_URI`` is configured, the catalog/policy come from MongoDB Atlas
    (the system of record) and the agents read through the MongoDB MCP server.
    Otherwise the in-process demo seed is used (local dev + tests). A failure to
    reach Atlas falls back to the demo seed so the service always boots.
    """
    settings = get_settings()
    seller, demo_products, demo_policy = get_demo_seller()
    products, policy = demo_products, demo_policy
    repository = None
    use_mcp = False

    if settings.mongodb_uri:
        try:
            from asili_agents.data.mongo_repository import MongoCatalogRepository

            repository = MongoCatalogRepository(settings.mongodb_uri, settings.mongodb_database)
            mongo_products = repository.all_products()
            mongo_policy = repository.get_policy()
            if mongo_products:
                products = mongo_products
            if mongo_policy is not None:
                policy = mongo_policy
            set_catalog_repository(repository)
            use_mcp = settings.use_mcp
        except Exception:
            # Atlas unreachable/misconfigured — fall back to the demo seed.
            repository = None
            use_mcp = False
            products, policy = demo_products, demo_policy
            set_product_store(products)
            set_pricing_context(products, policy)
    else:
        set_product_store(products)
        set_pricing_context(products, policy)

    _state["seller"] = seller
    _state["products"] = products
    _state["policy"] = policy
    _state["repository"] = repository
    _state["use_mcp"] = use_mcp
    _state["conversations"] = {}
    _state["pending_drafts"] = {}  # conversation_id -> draft info
    _state["runners"] = {}  # conversation_id -> runner

    # Set up approval callback to store pending drafts
    def approval_callback(draft_id: str, body: str) -> ApprovalResult:
        # Store the draft as pending - actual approval happens via /api/approve
        _state["pending_drafts"][draft_id] = {
            "body": body,
            "status": "pending",
        }
        return ApprovalResult(
            status=ApprovalStatus.PENDING,
            draft_id=draft_id,
            body=body,
        )

    set_approval_callback(approval_callback)

    yield

    # Cleanup
    _state.clear()


app = FastAPI(
    title="Asili Operations Team API",
    description="AI-powered multi-agent system for micro-sellers",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the phone-inbox web UI (same-origin static files) at /app/.
if WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


# ============================================================================
# Request/Response Models
# ============================================================================


class SellerResponse(BaseModel):
    """Seller information."""

    id: str
    name: str
    lane: str
    brand_voice: str


class ProductResponse(BaseModel):
    """Product information."""

    id: str
    sku: str
    name: str
    description: str
    price: float
    cost: float
    margin_percent: float
    stock_quantity: int
    stock_level: str
    unit: str


class PolicyResponse(BaseModel):
    """Policy information."""

    margin_floor: float
    bundle_discount_percent: float
    shipping_note: str
    returns_note: str


class MessageResponse(BaseModel):
    """Message in a conversation."""

    id: str
    direction: str
    sender_name: str
    body: str
    status: str
    timestamp: str
    agent_name: str | None = None
    sources: list[str] = []


class ConversationResponse(BaseModel):
    """Conversation details."""

    id: str
    customer_name: str
    customer_initials: str
    channel: str
    status: str
    messages: list[MessageResponse]


class BusinessFactResponse(BaseModel):
    """A grounded business fact for the UI."""

    id: str
    key: str
    value: str
    sub: str
    tone: str = "default"


class AgentStepResponse(BaseModel):
    """An agent decision step for the UI."""

    id: str
    agent_name: str
    agent_role: str
    step_type: str
    reasoning_trace: str
    grounded_facts: list[str]
    timestamp: str


class RunAgentsRequest(BaseModel):
    """Request to run agents on a conversation."""

    conversation_id: str
    message: str | None = None


class RunAgentsResponse(BaseModel):
    """Response from running agents."""

    steps: list[AgentStepResponse]
    draft: dict[str, Any] | None = None
    facts: list[BusinessFactResponse]


class ApprovalRequest(BaseModel):
    """Request to approve/reject a draft."""

    conversation_id: str
    action: str = Field(..., pattern="^(approve|edit|reject)$")
    edited_body: str | None = None


class ApprovalResponse(BaseModel):
    """Response from approval action."""

    status: str
    message: MessageResponse | None = None


# ============================================================================
# API Endpoints
# ============================================================================


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Asili Operations Team",
        "version": "0.1.0",
        "status": "healthy",
    }


@app.get("/api/seller", response_model=SellerResponse)
async def get_seller():
    """Get the current seller information."""
    seller = _state.get("seller")
    if not seller:
        raise HTTPException(status_code=500, detail="Seller not initialized")

    return SellerResponse(
        id=str(seller.id),
        name=seller.name,
        lane=seller.lane,
        brand_voice=seller.brand_voice,
    )


@app.get("/api/products", response_model=list[ProductResponse])
async def get_products():
    """Get all products in the catalog."""
    products = _state.get("products", [])
    return [
        ProductResponse(
            id=str(p.id),
            sku=p.sku,
            name=p.name,
            description=p.description,
            price=float(p.price),
            cost=float(p.cost),
            margin_percent=p.margin_percent,
            stock_quantity=p.stock_quantity,
            stock_level=p.stock_level.value,
            unit=p.unit,
        )
        for p in products
    ]


@app.get("/api/policy", response_model=PolicyResponse)
async def get_policy():
    """Get the seller's business policy."""
    policy = _state.get("policy")
    if not policy:
        raise HTTPException(status_code=500, detail="Policy not initialized")

    return PolicyResponse(
        margin_floor=policy.margin_floor,
        bundle_discount_percent=policy.bundle_discount_percent,
        shipping_note=policy.shipping_note,
        returns_note=policy.returns_note,
    )


@app.get("/api/facts", response_model=list[BusinessFactResponse])
async def get_business_facts():
    """Get grounded business facts for the UI."""
    products = _state.get("products", [])
    policy = _state.get("policy")

    facts = []

    # Find the Purple Tea product for the demo scenario
    purple_tea = next((p for p in products if "purple" in p.name.lower()), None)

    if purple_tea:
        facts.extend(
            [
                BusinessFactResponse(
                    id="product",
                    key="Product",
                    value=purple_tea.name,
                    sub=f"{purple_tea.origin}",
                ),
                BusinessFactResponse(
                    id="price",
                    key="Unit price",
                    value=f"${purple_tea.price:.2f}",
                    sub=f"per {purple_tea.unit}",
                ),
                BusinessFactResponse(
                    id="cost",
                    key="Unit cost",
                    value=f"${purple_tea.cost:.2f}",
                    sub="landed",
                ),
                BusinessFactResponse(
                    id="margin",
                    key="Unit margin",
                    value=f"${purple_tea.margin:.2f}",
                    sub=f"{int(purple_tea.margin_percent * 100)}% · floor {int(policy.margin_floor * 100)}%",
                ),
                BusinessFactResponse(
                    id="stock",
                    key="In stock",
                    value=f"{purple_tea.stock_quantity} {purple_tea.unit}s",
                    sub="Low · reorder soon"
                    if purple_tea.stock_level.value == "low"
                    else "Healthy",
                    tone="signal" if purple_tea.stock_level.value == "low" else "default",
                ),
            ]
        )

    return facts


@app.post("/api/conversations", response_model=ConversationResponse)
async def create_conversation(customer_name: str = "Dana R."):
    """Create a new conversation."""
    from asili_agents.data.seed import create_demo_conversation

    conversation = create_demo_conversation()
    _state["conversations"][str(conversation.id)] = conversation

    return _conversation_to_response(conversation)


@app.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: str):
    """Get a conversation by ID."""
    conversation = _state["conversations"].get(conversation_id)
    if not conversation:
        # Create default demo conversation
        from asili_agents.data.seed import create_demo_conversation

        conversation = create_demo_conversation()
        _state["conversations"][str(conversation.id)] = conversation

    return _conversation_to_response(conversation)


@app.get("/api/decisions", response_model=list[AgentStepResponse])
async def get_decisions():
    """Get all logged agent decisions."""
    decisions = get_decision_log()
    return [
        AgentStepResponse(
            id=str(d.id),
            agent_name=d.agent_name,
            agent_role=d.agent_role,
            step_type=d.step_type,
            reasoning_trace=d.reasoning_trace,
            grounded_facts=d.grounded_facts,
            timestamp=d.timestamp.isoformat(),
        )
        for d in decisions
    ]


@app.post("/api/reset")
async def reset_demo():
    """Reset the demo state."""
    clear_decision_log()
    _state["conversations"] = {}
    _state["pending_drafts"] = {}
    _state["runners"] = {}

    # Reinitialize with fresh demo data
    seller, products, policy = get_demo_seller()
    _state["seller"] = seller
    _state["products"] = products
    _state["policy"] = policy
    set_product_store(products)
    set_pricing_context(products, policy)

    return {"status": "reset"}


@app.post("/api/run", response_model=RunAgentsResponse)
async def run_agents(request: RunAgentsRequest):
    """Run the multi-agent system on a conversation.

    This endpoint executes the real ADK agents on the customer message,
    returning the agent steps, grounded facts, and composed draft reply.
    """
    seller = _state.get("seller")
    products = _state.get("products", [])
    policy = _state.get("policy")

    if not seller or not policy:
        raise HTTPException(status_code=500, detail="Demo data not initialized")

    # Get or create conversation
    conversation = _state["conversations"].get(request.conversation_id)
    if not conversation:
        from asili_agents.data.seed import create_demo_conversation

        conversation = create_demo_conversation()
        _state["conversations"][str(conversation.id)] = conversation

    # Get the customer message (use provided or last inbound message)
    if request.message:
        customer_message = request.message
    else:
        inbound_messages = [m for m in conversation.messages if m.direction.value == "inbound"]
        if not inbound_messages:
            raise HTTPException(status_code=400, detail="No customer message found")
        customer_message = inbound_messages[-1].body

    # Create and run the agent system (MongoDB + MCP when configured).
    runner = create_runner(
        seller,
        products,
        policy,
        repository=_state.get("repository"),
        use_mcp=_state.get("use_mcp"),
    )
    _state["runners"][request.conversation_id] = runner

    # run_agent() is synchronous and uses asyncio.run() internally, so it must
    # run in a worker thread to avoid "asyncio.run() cannot be called from a
    # running event loop" inside this async endpoint.
    result = await asyncio.to_thread(run_agent, runner, customer_message)

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {result.error}")

    # Store the draft for approval
    if result.draft:
        draft_id = f"draft_{request.conversation_id}"
        _state["pending_drafts"][request.conversation_id] = {
            "draft_id": draft_id,
            "body": result.draft,
            "sources": result.draft_sources,
            "status": "pending",
        }

    # Build response
    steps = [
        AgentStepResponse(
            id=step.id,
            agent_name=step.agent_name,
            agent_role=step.agent_role,
            step_type=step.step_type,
            reasoning_trace=step.reasoning_trace,
            grounded_facts=step.grounded_facts,
            timestamp=step.timestamp.isoformat(),
        )
        for step in result.steps
    ]

    # Get grounded facts for UI display
    facts = _get_grounded_facts_for_response(products, policy)

    # Build draft response
    draft_response = None
    if result.draft:
        draft_response = {
            "body": result.draft,
            "sources": result.draft_sources,
            "status": "pending",
        }

    return RunAgentsResponse(
        steps=steps,
        draft=draft_response,
        facts=facts,
    )


@app.post("/api/run/baseline")
async def run_baseline_agent(request: RunAgentsRequest):
    """Run the baseline (single-model) agent for comparison.

    This endpoint executes the baseline agent which has no tools,
    demonstrating the failure modes of a naive LLM approach.
    """
    seller = _state.get("seller")
    products = _state.get("products", [])

    if not seller:
        raise HTTPException(status_code=500, detail="Demo data not initialized")

    # Get or create conversation
    conversation = _state["conversations"].get(request.conversation_id)
    if not conversation:
        from asili_agents.data.seed import create_demo_conversation

        conversation = create_demo_conversation()
        _state["conversations"][str(conversation.id)] = conversation

    # Get the customer message
    if request.message:
        customer_message = request.message
    else:
        inbound_messages = [m for m in conversation.messages if m.direction.value == "inbound"]
        if not inbound_messages:
            raise HTTPException(status_code=400, detail="No customer message found")
        customer_message = inbound_messages[-1].body

    # Create and run the baseline agent
    baseline_runner = create_baseline_runner(seller, products)
    response_text, raw_events = await asyncio.to_thread(
        run_baseline, baseline_runner, customer_message
    )

    return {
        "response": response_text,
        "events_count": len(raw_events),
        "has_tools": False,
        "grounded": False,
    }


@app.post("/api/approve", response_model=ApprovalResponse)
async def approve_draft(request: ApprovalRequest):
    """Process approval/rejection of a pending draft message.

    Actions:
    - approve: Send the draft as-is
    - edit: Send the edited version
    - reject: Discard the draft
    """
    pending = _state["pending_drafts"].get(request.conversation_id)
    if not pending:
        raise HTTPException(status_code=404, detail="No pending draft for this conversation")

    conversation = _state["conversations"].get(request.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if request.action == "reject":
        # Discard the draft
        del _state["pending_drafts"][request.conversation_id]
        return ApprovalResponse(status="rejected", message=None)

    # Approve or edit
    final_body = request.edited_body if request.action == "edit" else pending["body"]

    # Add the message to the conversation
    message = conversation.add_message(
        direction=MessageDirection.OUTBOUND,
        sender_name="Asili Agent",
        body=final_body,
        agent_name="Operations Manager",
        sources=pending.get("sources", []),
    )
    message.status = MessageStatus.SENT

    # Clear the pending draft
    del _state["pending_drafts"][request.conversation_id]

    return ApprovalResponse(
        status="approved" if request.action == "approve" else "edited",
        message=MessageResponse(
            id=str(message.id),
            direction=message.direction.value,
            sender_name=message.sender_name,
            body=message.body,
            status=message.status.value,
            timestamp=message.timestamp_display,
            agent_name=message.agent_name,
            sources=message.sources,
        ),
    )


@app.get("/api/pending/{conversation_id}")
async def get_pending_draft(conversation_id: str):
    """Get the pending draft for a conversation, if any."""
    pending = _state["pending_drafts"].get(conversation_id)
    if not pending:
        return {"has_pending": False}

    return {
        "has_pending": True,
        "draft": pending,
    }


@app.post("/api/eval")
async def run_trust_scorecard(limit: int = 6) -> dict[str, Any]:
    """Run the Trust Scorecard: the multi-agent team vs the naive baseline.

    Runs adversarial scenarios through both systems and scores each reply for
    hallucinated stock, margin safety, and groundedness. ``limit`` bounds how
    many scenarios run live (each issues real Gemini calls), defaulting to 6 to
    keep latency and token spend reasonable for an interactive demo.
    """
    seller = _state.get("seller")
    products = _state.get("products", [])
    policy = _state.get("policy")

    if not seller or not policy:
        raise HTTPException(status_code=500, detail="Demo data not initialized")

    team_fn, baseline_fn = build_live_reply_fns(
        seller,
        products,
        policy,
        repository=_state.get("repository"),
        use_mcp=_state.get("use_mcp"),
    )
    # run_scorecard drives synchronous ADK runners (asyncio.run internally), so
    # offload it to a worker thread to avoid a nested event loop.
    result = await asyncio.to_thread(
        run_scorecard,
        products,
        policy,
        team_reply_fn=team_fn,
        baseline_reply_fn=baseline_fn,
        limit=limit,
    )
    return result


def _get_grounded_facts_for_response(products: list, policy) -> list[BusinessFactResponse]:
    """Get grounded facts based on tool calls during agent run."""
    facts = []

    # Find the Purple Tea product (demo scenario focus)
    purple_tea = next((p for p in products if "purple" in p.name.lower()), None)

    if purple_tea:
        # Get real data from tools
        stock_info = check_stock(str(purple_tea.id))
        cost_info = get_costs(str(purple_tea.id))
        bundle_result = compute_bundle_price(
            items=[{"product_id": str(purple_tea.id), "quantity": 2}],
            margin_floor=policy.margin_floor,
        )

        facts.extend(
            [
                BusinessFactResponse(
                    id="product",
                    key="Product",
                    value=purple_tea.name,
                    sub=purple_tea.origin,
                ),
                BusinessFactResponse(
                    id="price",
                    key="Unit price",
                    value=f"${purple_tea.price:.2f}",
                    sub=f"per {purple_tea.unit}",
                ),
                BusinessFactResponse(
                    id="cost",
                    key="Unit cost",
                    value=f"${cost_info.get('unit_cost', 0):.2f}",
                    sub="landed",
                ),
                BusinessFactResponse(
                    id="margin",
                    key="Unit margin",
                    value=f"${cost_info.get('unit_margin', 0):.2f}",
                    sub=f"{int(cost_info.get('margin_percent', 0) * 100)}% - floor {int(policy.margin_floor * 100)}%",
                ),
                BusinessFactResponse(
                    id="stock",
                    key="In stock",
                    value=f"{stock_info.get('quantity', 0)} {purple_tea.unit}s",
                    sub="Low - reorder soon" if stock_info.get("level") == "low" else "Healthy",
                    tone="signal" if stock_info.get("level") == "low" else "default",
                ),
            ]
        )

        if "bundle_price" in bundle_result:
            facts.append(
                BusinessFactResponse(
                    id="bundle",
                    key="Bundle (2 tins)",
                    value=f"${bundle_result['bundle_price']:.2f}",
                    sub=f"{int(bundle_result['margin_percent'] * 100)}% margin",
                    tone="accent",
                )
            )

    return facts


def _conversation_to_response(conversation: Conversation) -> ConversationResponse:
    """Convert a Conversation to a response model."""
    return ConversationResponse(
        id=str(conversation.id),
        customer_name=conversation.customer_name,
        customer_initials=conversation.customer_initials,
        channel=conversation.channel,
        status=conversation.status.value,
        messages=[
            MessageResponse(
                id=str(m.id),
                direction=m.direction.value,
                sender_name=m.sender_name,
                body=m.body,
                status=m.status.value,
                timestamp=m.timestamp_display,
                agent_name=m.agent_name,
                sources=m.sources,
            )
            for m in conversation.messages
        ],
    )
