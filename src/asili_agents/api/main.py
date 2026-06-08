"""FastAPI application for the Asili Operations Team.

This API provides:
1. Agent execution endpoints
2. Conversation management
3. Approval workflow
4. Demo runner
"""

import asyncio
import hmac
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from asili_agents.config import get_settings
from asili_agents.data.models import (
    Conversation,
    ConversationStatus,
    MessageDirection,
    MessageStatus,
    Policy,
    Product,
)
from asili_agents.data.repository import set_catalog_repository
from asili_agents.data.seed import get_demo_seller
from asili_agents.data.store import ConversationStore, InMemoryStore, MongoStore
from asili_agents.eval.runner import build_live_reply_fns_async, run_scorecard_async
from asili_agents.integrations.telegram import (
    SECRET_HEADER,
    TelegramClient,
    initials_of,
    parse_update,
)
from asili_agents.runner import (
    create_baseline_runner,
    create_runner,
    run_agent_async,
    run_baseline_async,
)
from asili_agents.tools.catalog import check_stock, get_costs, set_product_store
from asili_agents.tools.channel import ApprovalResult, ApprovalStatus, set_approval_callback
from asili_agents.tools.logging import clear_decision_log
from asili_agents.tools.pricing import compute_bundle_price, set_pricing_context

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

logger = logging.getLogger("asili.api")

T = TypeVar("T")

# Application state
_state: dict[str, Any] = {}

# Inbound payload + abuse guards. The service is deployed --allow-unauthenticated
# and some endpoints issue billable Gemini calls, so cap body size and rate-limit
# the expensive/agent endpoints (best-effort, per-process sliding window).
MAX_BODY_BYTES = 64 * 1024  # global cap for any JSON request body
MAX_WEBHOOK_BYTES = 64 * 1024
MAX_INBOUND_CHARS = 2000
# Bound the rate-limiter memory: keys (client IPs) are evicted once stale, and the
# whole table is capped so a flood of distinct source IPs can't grow it unbounded.
MAX_RATE_KEYS = 10_000
# Telegram redelivers an Update on any non-2xx/timeout. Remembering recent
# update_ids makes the webhook idempotent so a redelivery can't trigger a second
# billable agent run or a duplicate inbound message.
SEEN_UPDATE_CAP = 4096
_rate_state: dict[str, list[float]] = {}
_seen_update_ids: OrderedDict[int, None] = OrderedDict()


def _rate_limited(key: str, max_calls: int, window_s: float) -> bool:
    """Return True if `key` has exceeded `max_calls` within `window_s` seconds."""
    now = time.monotonic()
    recent = [t for t in _rate_state.get(key, []) if now - t < window_s]
    if len(recent) >= max_calls:
        _rate_state[key] = recent
        return True
    recent.append(now)
    _rate_state[key] = recent
    # Opportunistic eviction so the table can't grow without bound: drop any key
    # whose window has fully elapsed, then hard-cap the total key count.
    if len(_rate_state) > MAX_RATE_KEYS:
        stale = [k for k, ts in _rate_state.items() if not ts or now - ts[-1] >= window_s]
        for k in stale:
            _rate_state.pop(k, None)
        while len(_rate_state) > MAX_RATE_KEYS:
            _rate_state.pop(next(iter(_rate_state)), None)
    return False


def _seen_update(update_id: int | None) -> bool:
    """Return True if this Telegram update_id was already processed (idempotency)."""
    if update_id is None:
        return False
    if update_id in _seen_update_ids:
        return True
    _seen_update_ids[update_id] = None
    while len(_seen_update_ids) > SEEN_UPDATE_CAP:
        _seen_update_ids.popitem(last=False)
    return False


def _client_key(request: Request) -> str:
    """Best-effort client identity for rate limiting.

    Behind Cloud Run, ``request.client.host`` is the front-end proxy, so all
    callers collapse into one bucket. Prefer the left-most X-Forwarded-For hop
    (the original client) when present.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


async def _run_with_timeout(coro: Awaitable[T], *, what: str) -> T:
    """Run an agent/Gemini/MCP coroutine under a hard timeout.

    Without this a single pathological run (huge prompt, model stall, MCP hang)
    can pin a request slot + the Node MCP subprocess for the entire Cloud Run
    request window. On timeout we surface a clean 504 and let the task cancel.
    """
    timeout_s = float(get_settings().agent_run_timeout_s)
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except TimeoutError as exc:
        logger.warning("%s exceeded %.0fs timeout — cancelled", what, timeout_s)
        raise HTTPException(status_code=504, detail=f"{what} timed out") from exc


def _store() -> ConversationStore:
    store: ConversationStore = _state["store"]
    return store


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize application state on startup.

    If ``MONGODB_URI`` is configured, the catalog/policy come from MongoDB Atlas
    (the system of record) and the agents read through the MongoDB MCP server.
    Otherwise the in-process demo seed is used (local dev + tests). A failure to
    reach Atlas falls back to the demo seed so the service always boots.
    """
    settings = get_settings()

    # Configure logging once, at startup. Without this nothing ever calls
    # basicConfig/dictConfig, so the root logger stays at WARNING and every
    # deliberate INFO diagnostic — including the "Atlas FAILED, serving DEMO"
    # alarm and the missing-webhook-secret warning — is silently dropped in
    # Cloud Logging exactly when the service degrades. force=True so we win over
    # any handler uvicorn may have installed on the root logger.
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    seller, demo_products, demo_policy = get_demo_seller()
    products, policy = demo_products, demo_policy
    repository = None
    use_mcp = False
    data_source = "demo"

    if settings.mongodb_uri and not settings.demo_mode:
        try:
            from asili_agents.data.mongo_repository import MongoCatalogRepository

            repository = MongoCatalogRepository(settings.mongodb_uri, settings.mongodb_database)
            mongo_products = repository.all_products()
            mongo_policy = repository.get_policy()
            if not mongo_products:
                raise RuntimeError(
                    f"MongoDB connected but database {settings.mongodb_database!r} has no "
                    "products — run scripts/seed_atlas.py."
                )
            products = mongo_products
            if mongo_policy is not None:
                policy = mongo_policy
            set_catalog_repository(repository)
            use_mcp = settings.use_mcp
            data_source = "atlas"
            logger.info(
                "MongoDB Atlas connected: %d products in %r; MCP grounding=%s",
                len(products),
                settings.mongodb_database,
                use_mcp,
            )
        except Exception as exc:
            # Do NOT silently serve demo data on the graded path — log loudly.
            logger.error(
                "MongoDB Atlas connection FAILED (%s: %s) — serving DEMO seed (NOT live "
                "grounded). Fix: in Atlas, set Network Access to allow 0.0.0.0/0 so Cloud Run "
                "can connect, confirm the MONGODB_URI secret, and run scripts/seed_atlas.py.",
                type(exc).__name__,
                exc,
            )
            repository = None
            use_mcp = False
            data_source = "demo"
            products, policy = demo_products, demo_policy
            set_product_store(products)
            set_pricing_context(products, policy)
    else:
        reason = "DEMO_MODE is on" if settings.demo_mode else "MONGODB_URI is not set"
        logger.info("Using in-process demo seed (%s) — no MongoDB, no MCP grounding.", reason)
        set_product_store(products)
        set_pricing_context(products, policy)

    _state["seller"] = seller
    _state["products"] = products
    _state["policy"] = policy
    _state["repository"] = repository
    _state["use_mcp"] = use_mcp
    _state["data_source"] = data_source
    _state["telegram"] = (
        TelegramClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
    )
    _state["telegram_secret"] = settings.telegram_webhook_secret
    _state["channel_enabled"] = bool(settings.telegram_bot_token)
    if _state["channel_enabled"]:
        logger.info("Telegram channel enabled.")
        if not settings.telegram_webhook_secret:
            logger.error(
                "TELEGRAM_BOT_TOKEN is set but TELEGRAM_WEBHOOK_SECRET is not — the "
                "webhook will reject all requests (fail closed). Set a webhook secret."
            )
    _state["conversations"] = {}
    _state["pending_drafts"] = {}  # conversation_id -> draft info
    _state["runners"] = {}  # conversation_id -> runner
    _state["last_decisions"] = []
    _rate_state.clear()
    _seen_update_ids.clear()

    # Durable store: MongoDB when Atlas is connected (survives restarts + shared
    # across instances), else in-memory wrapping the dicts above (local/tests).
    store: ConversationStore = InMemoryStore(_state["conversations"], _state["pending_drafts"])
    if data_source == "atlas" and settings.mongodb_uri:
        try:
            store = MongoStore(settings.mongodb_uri, settings.mongodb_database)
            logger.info("Durable conversation store: MongoDB.")
        except Exception:
            logger.exception("MongoStore init failed — using in-memory store.")
            store = InMemoryStore(_state["conversations"], _state["pending_drafts"])
    _state["store"] = store

    # The agent's send_for_approval just marks the draft PENDING; the real
    # pending draft (keyed by conversation) is persisted by the endpoints via the
    # store. This callback only guarantees the agent never auto-sends.
    def approval_callback(draft_id: str, body: str) -> ApprovalResult:
        return ApprovalResult(status=ApprovalStatus.PENDING, draft_id=draft_id, body=body)

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

# Content Security Policy for the same-origin web UI. The /app inbox renders
# attacker-controlled Telegram names/bodies through innerHTML sinks guarded by a
# hand-rolled escaper; a strict CSP is the backstop if one escape is ever missed.
# Everything the UI loads is same-origin static, so 'self' is sufficient — no CDNs.
_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def security_and_size_guard(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Reject oversized bodies up front and stamp security headers on every reply."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return Response(status_code=413, content="payload too large")
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    # The web UI is same-origin; we expose a read-only public demo API and use no
    # cookies/credentials, so allow any origin but NOT credentials (the
    # `*` + allow_credentials=True combination is an unsafe, browser-rejected mix).
    allow_origins=["*"],
    allow_credentials=False,
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

    conversation_id: str = Field(..., max_length=256)
    # Cap caller-supplied prompts: these drive billable Gemini calls, so an
    # unbounded message is a direct cost-amplification lever.
    message: str | None = Field(default=None, max_length=MAX_INBOUND_CHARS)


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
async def root() -> dict[str, Any]:
    """Health check endpoint, with data-source visibility for verification."""
    return {
        "service": "Asili Operations Team",
        "version": "0.1.0",
        "status": "healthy",
        "data_source": _state.get("data_source", "demo"),
        "mcp_grounding": bool(_state.get("use_mcp", False)),
        "products_loaded": len(_state.get("products", [])),
    }


@app.get("/api/seller", response_model=SellerResponse)
async def get_seller() -> SellerResponse:
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
async def get_products() -> list[ProductResponse]:
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
async def get_policy() -> PolicyResponse:
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
async def get_business_facts() -> list[BusinessFactResponse]:
    """Get grounded business facts for the UI."""
    products = _state.get("products", [])
    policy = _state.get("policy")

    facts = []

    # Find the Purple Tea product for the demo scenario
    focus = _focus_product(products)

    if focus and policy:
        facts.extend(
            [
                BusinessFactResponse(
                    id="product",
                    key="Product",
                    value=focus.name,
                    sub=f"{focus.origin}",
                ),
                BusinessFactResponse(
                    id="price",
                    key="Unit price",
                    value=f"${focus.price:.2f}",
                    sub=f"per {focus.unit}",
                ),
                BusinessFactResponse(
                    id="cost",
                    key="Unit cost",
                    value=f"${focus.cost:.2f}",
                    sub="landed",
                ),
                BusinessFactResponse(
                    id="margin",
                    key="Unit margin",
                    value=f"${focus.margin:.2f}",
                    sub=f"{int(focus.margin_percent * 100)}% · floor {int(policy.margin_floor * 100)}%",
                ),
                BusinessFactResponse(
                    id="stock",
                    key="In stock",
                    value=f"{focus.stock_quantity} {focus.unit}s",
                    sub="Low · reorder soon" if focus.stock_level.value == "low" else "Healthy",
                    tone="signal" if focus.stock_level.value == "low" else "default",
                ),
            ]
        )

    return facts


@app.post("/api/conversations", response_model=ConversationResponse)
async def create_conversation(customer_name: str = "Dana R.") -> ConversationResponse:
    """Create a new conversation."""
    from asili_agents.data.seed import create_demo_conversation

    conversation = create_demo_conversation()
    _store().save_conversation(str(conversation.id), conversation)

    return _conversation_to_response(conversation)


@app.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: str) -> ConversationResponse:
    """Get a conversation by ID."""
    conversation = _store().get_conversation(conversation_id)
    if not conversation:
        # Create default demo conversation
        from asili_agents.data.seed import create_demo_conversation

        conversation = create_demo_conversation()
        _store().save_conversation(str(conversation.id), conversation)

    return _conversation_to_response(conversation)


@app.get("/api/decisions", response_model=list[AgentStepResponse])
async def get_decisions() -> list[AgentStepResponse]:
    """Get the agent decision steps from the most recent run.

    The per-run decision log is a ContextVar scoped to the agent's task, so it is
    empty in this handler's request context. The run endpoints instead snapshot
    each run's steps into ``_state['last_decisions']`` so this endpoint reflects
    the latest run rather than always returning an empty list.
    """
    steps: list[AgentStepResponse] = _state.get("last_decisions", [])
    return steps


@app.get("/api/inbox")
async def get_inbox() -> list[dict[str, Any]]:
    """List conversations for the seller inbox (incoming Telegram + demo).

    Each item summarizes a conversation so the UI can show the inbox and poll for
    new messages. Conversations with a pending draft are surfaced first.
    """
    items: list[dict[str, Any]] = []
    store = _store()
    for conversation_id, conversation in store.list_conversations():
        last = conversation.messages[-1] if conversation.messages else None
        items.append(
            {
                "conversation_id": conversation_id,
                "customer_name": conversation.customer_name,
                "customer_initials": conversation.customer_initials,
                "channel": conversation.channel,
                "status": conversation.status.value,
                "last_message": last.body if last else "",
                "last_direction": last.direction.value if last else None,
                "has_pending": store.has_pending(conversation_id),
            }
        )
    # Pending drafts first (seller's action queue), then everything else.
    items.sort(key=lambda item: (not item["has_pending"], item["customer_name"]))
    return items


@app.post("/api/reset")
async def reset_demo() -> dict[str, str]:
    """Reset the in-memory demo state.

    SECURITY: this endpoint is unauthenticated. It must NEVER destroy durable
    data. When backed by Atlas, ``store.clear()`` would run ``delete_many({})``
    against the real ``conversations``/``drafts`` collections — an anonymous,
    irrecoverable wipe of every conversation and every pending seller-approval
    draft across all instances. So on the Atlas path we refuse to clear the store
    and only re-seed the in-memory demo catalog. The in-memory store (local/tests)
    is safe to clear because it holds nothing durable.
    """
    clear_decision_log()
    _state["last_decisions"] = []
    data_source = _state.get("data_source", "demo")
    cleared = False
    if data_source != "atlas":
        _store().clear()
        cleared = True
    else:
        logger.info("/api/reset called on Atlas-backed store — refusing to clear durable data.")
    _state["runners"] = {}

    # Reinitialize with fresh demo data
    seller, products, policy = get_demo_seller()
    _state["seller"] = seller
    _state["products"] = products
    _state["policy"] = policy
    set_product_store(products)
    set_pricing_context(products, policy)

    return {"status": "reset" if cleared else "reset-demo-only"}


@app.post("/api/run", response_model=RunAgentsResponse)
async def run_agents(request: RunAgentsRequest, http_request: Request) -> RunAgentsResponse:
    """Run the multi-agent system on a conversation.

    This endpoint executes the real ADK agents on the customer message,
    returning the agent steps, grounded facts, and composed draft reply.
    """
    if _rate_limited(f"run:{_client_key(http_request)}", max_calls=30, window_s=60.0):
        raise HTTPException(status_code=429, detail="rate limited")

    seller = _state.get("seller")
    products = _state.get("products", [])
    policy = _state.get("policy")

    if not seller or not policy:
        raise HTTPException(status_code=500, detail="Demo data not initialized")

    # Get or create conversation
    store = _store()
    conversation = store.get_conversation(request.conversation_id)
    if not conversation:
        from asili_agents.data.seed import create_demo_conversation

        conversation = create_demo_conversation()
        store.save_conversation(str(conversation.id), conversation)

    # Get the customer message (use provided or last inbound message)
    if request.message:
        customer_message = request.message
    else:
        inbound_messages = [
            m for m in conversation.messages if m.direction == MessageDirection.INBOUND
        ]
        if not inbound_messages:
            raise HTTPException(status_code=400, detail="No customer message found")
        customer_message = inbound_messages[-1].body

    # Each request is its own asyncio task, so the per-run decision log (a
    # ContextVar) isolates concurrent runs without a process-wide lock. Runs on
    # this event loop so the MongoDB MCP stdio session shares it.
    runner = create_runner(
        seller,
        products,
        policy,
        repository=_state.get("repository"),
        use_mcp=_state.get("use_mcp"),
    )
    result = await _run_with_timeout(run_agent_async(runner, customer_message), what="agent run")

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {result.error}")

    # Store the draft for approval
    if result.draft:
        store.set_pending(
            request.conversation_id,
            {
                "draft_id": f"draft_{request.conversation_id}",
                "body": result.draft,
                "sources": result.draft_sources,
                "status": "pending",
            },
        )

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
    # Snapshot the latest run's steps so GET /api/decisions reflects it (the
    # ContextVar decision log is empty outside the agent's own task context).
    _state["last_decisions"] = steps

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
async def run_baseline_agent(
    request: RunAgentsRequest, http_request: Request
) -> dict[str, Any]:
    """Run the baseline (single-model) agent for comparison.

    This endpoint executes the baseline agent which has no tools,
    demonstrating the failure modes of a naive LLM approach.
    """
    # Billable Gemini call — rate-limit it the same as /api/run.
    if _rate_limited(f"baseline:{_client_key(http_request)}", max_calls=30, window_s=60.0):
        raise HTTPException(status_code=429, detail="rate limited")

    seller = _state.get("seller")
    products = _state.get("products", [])

    if not seller:
        raise HTTPException(status_code=500, detail="Demo data not initialized")

    # Get or create conversation
    store = _store()
    conversation = store.get_conversation(request.conversation_id)
    if not conversation:
        from asili_agents.data.seed import create_demo_conversation

        conversation = create_demo_conversation()
        store.save_conversation(str(conversation.id), conversation)

    # Get the customer message
    if request.message:
        customer_message = request.message
    else:
        inbound_messages = [
            m for m in conversation.messages if m.direction == MessageDirection.INBOUND
        ]
        if not inbound_messages:
            raise HTTPException(status_code=400, detail="No customer message found")
        customer_message = inbound_messages[-1].body

    # Create and run the baseline agent (async, on this event loop)
    baseline_runner = create_baseline_runner(seller, products)
    response_text, raw_events = await _run_with_timeout(
        run_baseline_async(baseline_runner, customer_message), what="baseline run"
    )

    return {
        "response": response_text,
        "events_count": len(raw_events),
        "has_tools": False,
        "grounded": False,
    }


@app.post("/api/approve", response_model=ApprovalResponse)
async def approve_draft(request: ApprovalRequest) -> ApprovalResponse:
    """Process approval/rejection of a pending draft message.

    Actions:
    - approve: Send the draft as-is
    - edit: Send the edited version
    - reject: Discard the draft
    """
    store = _store()
    pending = store.get_pending(request.conversation_id)
    if not pending:
        raise HTTPException(status_code=404, detail="No pending draft for this conversation")

    conversation = store.get_conversation(request.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if request.action == "reject":
        store.delete_pending(request.conversation_id)
        return ApprovalResponse(status="rejected", message=None)

    # Approve or edit
    final_body = str(
        request.edited_body
        if request.action == "edit" and request.edited_body
        else pending.get("body", "")
    )

    # Deliver over the originating channel (Telegram), if the draft came from one.
    telegram = _state.get("telegram")
    if pending.get("channel") == "telegram" and telegram is not None and pending.get("chat_id"):
        try:
            await telegram.send_message(pending["chat_id"], final_body)
        except Exception:
            logger.exception("Telegram delivery failed for chat %s", pending.get("chat_id"))

    # Add the message to the conversation
    message = conversation.add_message(
        direction=MessageDirection.OUTBOUND,
        sender_name="Asili Agent",
        body=final_body,
        agent_name="Operations Manager",
        sources=pending.get("sources", []),
    )
    message.status = MessageStatus.SENT

    # Persist the updated conversation + clear the pending draft.
    store.save_conversation(request.conversation_id, conversation)
    store.delete_pending(request.conversation_id)

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
async def get_pending_draft(conversation_id: str) -> dict[str, Any]:
    """Get the pending draft for a conversation, if any.

    Returns only the fields the UI needs. The stored draft also holds the
    customer's Telegram ``chat_id`` (the delivery address); that is never exposed
    over the API — it stays server-side and is used only on approval.
    """
    pending = _store().get_pending(conversation_id)
    if not pending:
        return {"has_pending": False}

    return {
        "has_pending": True,
        "draft": {
            "body": pending.get("body", ""),
            "sources": pending.get("sources", []),
            "status": pending.get("status", "pending"),
            "channel": pending.get("channel"),
        },
    }


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    """Inbound Telegram messages -> a grounded draft held for seller approval.

    The reply is NOT sent to the customer here. It becomes a pending draft that
    the seller approves (POST /api/approve), at which point it is delivered back
    to the customer's Telegram chat. This preserves the human-approval gate.
    """
    # Read the body once and enforce the size cap on the ACTUAL bytes. Relying on
    # the Content-Length header alone is bypassable (chunked Transfer-Encoding, or
    # a missing/spoofed header), which would let an arbitrarily large body be
    # buffered + parsed into memory.
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")

    # Verify the secret token. FAIL CLOSED: a configured secret is REQUIRED to do
    # any (billable) work. If no secret is configured the webhook is rejected
    # outright — otherwise, as deployed without a bot token, the route would be
    # anonymous and fire full Gemini runs for any internet caller. Compare in
    # constant time to avoid a timing side-channel on the secret.
    secret = _state.get("telegram_secret")
    if not secret:
        raise HTTPException(status_code=401, detail="webhook secret not configured")
    provided = request.headers.get(SECRET_HEADER) or ""
    if not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="invalid Telegram secret token")

    if _rate_limited(f"tg:{_client_key(request)}", max_calls=60, window_s=60.0):
        raise HTTPException(status_code=429, detail="rate limited")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid update payload")

    # Idempotency: Telegram redelivers an Update on any non-2xx/timeout. Skip one
    # we have already processed so a redelivery can't trigger a second billable
    # run or a duplicate inbound message.
    update_id = payload.get("update_id")
    if isinstance(update_id, int) and _seen_update(update_id):
        return {"ok": True, "skipped": True, "duplicate": True}

    inbound = parse_update(payload)
    if inbound is None or not inbound.text.strip():
        return {"ok": True, "skipped": True}
    inbound.text = inbound.text[:MAX_INBOUND_CHARS]

    seller = _state.get("seller")
    products = _state.get("products", [])
    policy = _state.get("policy")
    if not seller or not policy:
        raise HTTPException(status_code=500, detail="Service not initialized")

    conversation_id = f"tg:{inbound.chat_id}"
    store = _store()
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        conversation = Conversation(
            seller_id=seller.id,
            customer_name=inbound.sender_name,
            customer_initials=initials_of(inbound.sender_name),
            channel="Telegram",
            status=ConversationStatus.AWAITING_REPLY,
        )
    conversation.add_message(
        direction=MessageDirection.INBOUND,
        sender_name=inbound.sender_name,
        body=inbound.text,
    )
    store.save_conversation(conversation_id, conversation)

    telegram = _state.get("telegram")
    if telegram is not None:
        try:
            await telegram.send_chat_action(inbound.chat_id, "typing")
        except Exception:
            logger.debug("Telegram typing action failed", exc_info=True)

    # Ground a draft reply behind the approval gate. The per-run decision log is
    # a ContextVar, so no global lock is needed; run on this loop (MCP-safe).
    try:
        runner = create_runner(
            seller,
            products,
            policy,
            repository=_state.get("repository"),
            use_mcp=_state.get("use_mcp"),
        )
        result = await _run_with_timeout(
            run_agent_async(runner, inbound.text), what="telegram agent run"
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Agent run failed for Telegram chat %s", inbound.chat_id)
        return {"ok": True, "pending": False, "error": "agent_run_failed"}

    pending = bool(result.success and result.draft)
    if pending:
        store.set_pending(
            conversation_id,
            {
                "draft_id": f"draft_{conversation_id}",
                "body": result.draft,
                "sources": result.draft_sources,
                "status": "pending",
                "channel": "telegram",
                "chat_id": inbound.chat_id,
            },
        )
    return {"ok": True, "conversation_id": conversation_id, "pending": pending}


@app.post("/api/eval")
async def run_trust_scorecard(http_request: Request, limit: int = 6) -> dict[str, Any]:
    """Run the Trust Scorecard: the multi-agent team vs the naive baseline.

    Runs adversarial scenarios through both systems and scores each reply for
    hallucinated stock, margin safety, and groundedness. ``limit`` bounds how
    many scenarios run live (each issues real Gemini calls), defaulting to 6 to
    keep latency and token spend reasonable for an interactive demo.
    """
    # The scorecard issues many Gemini calls; rate-limit it tightly.
    if _rate_limited(f"eval:{_client_key(http_request)}", max_calls=4, window_s=60.0):
        raise HTTPException(status_code=429, detail="rate limited")
    limit = max(1, min(limit, 12))

    seller = _state.get("seller")
    products = _state.get("products", [])
    policy = _state.get("policy")

    if not seller or not policy:
        raise HTTPException(status_code=500, detail="Demo data not initialized")

    team_fn, baseline_fn = build_live_reply_fns_async(
        seller,
        products,
        policy,
        repository=_state.get("repository"),
        use_mcp=_state.get("use_mcp"),
    )
    # Per-run decision log is a ContextVar, so no global lock is needed; runs on
    # this event loop so the MCP stdio sessions work.
    result = await run_scorecard_async(
        products,
        policy,
        team_reply_fn=team_fn,
        baseline_reply_fn=baseline_fn,
        limit=limit,
    )
    return result


def _focus_product(products: list[Product]) -> Product | None:
    """The product to surface in the UI fact cards: the first low-stock item (the
    kind that needs attention), else the first product. (Generalized from a
    Purple-Tea hardcode so the panel works for any seeded catalog.)"""
    low = next((p for p in products if p.stock_level.value == "low"), None)
    return low or (products[0] if products else None)


def _get_grounded_facts_for_response(
    products: list[Product], policy: Policy
) -> list[BusinessFactResponse]:
    """Get grounded facts based on tool calls during agent run."""
    facts = []

    # Find the Purple Tea product (demo scenario focus)
    focus = _focus_product(products)

    if focus:
        # Get real data from tools
        stock_info = check_stock(str(focus.id))
        cost_info = get_costs(str(focus.id))
        bundle_result = compute_bundle_price(
            items=[{"product_id": str(focus.id), "quantity": 2}],
            margin_floor=policy.margin_floor,
        )

        facts.extend(
            [
                BusinessFactResponse(
                    id="product",
                    key="Product",
                    value=focus.name,
                    sub=focus.origin,
                ),
                BusinessFactResponse(
                    id="price",
                    key="Unit price",
                    value=f"${focus.price:.2f}",
                    sub=f"per {focus.unit}",
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
                    value=f"{stock_info.get('quantity', 0)} {focus.unit}s",
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
