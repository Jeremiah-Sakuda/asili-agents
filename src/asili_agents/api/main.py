"""FastAPI application for the Asili Operations Team.

This API provides:
1. Agent execution endpoints
2. Conversation management
3. Approval workflow
4. Demo runner
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from asili_agents.config import get_settings
from asili_agents.data.channel_store import (
    ChannelConnectionStore,
    InMemoryChannelStore,
    MongoChannelStore,
)
from asili_agents.data.models import (
    ChannelConnection,
    ChannelStatus,
    Conversation,
    ConversationStatus,
    MessageDirection,
    MessageStatus,
    Policy,
    Product,
)
from asili_agents.data.repository import set_catalog_repository
from asili_agents.data.seed import create_demo_followups, get_demo_seller
from asili_agents.data.store import ConversationStore, InMemoryStore, MongoStore
from asili_agents.eval.runner import build_live_reply_fns_async, run_scorecard_async
from asili_agents.integrations.channels import build_channel_registry
from asili_agents.integrations.channels.instagram import INSTAGRAM_SCOPES
from asili_agents.integrations.secrets import TokenVault
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
from asili_agents.tools import approvals, autonomy, cost
from asili_agents.tools.catalog import check_stock, get_costs, set_product_store
from asili_agents.tools.channel import ApprovalResult, ApprovalStatus, set_approval_callback
from asili_agents.tools.followups import (
    find_quiet_threads,
    find_unpaid_invoices,
    set_followups_context,
)
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

    # Seed the follow-up / unpaid-invoice store. In-process demo data for now
    # (quiet threads + an overdue invoice, aged relative to startup); grounding
    # orders/threads through Atlas is the remaining write-path increment, like
    # the decision log and eval runs.
    demo_conversations, demo_orders = create_demo_followups(datetime.now(UTC))
    set_followups_context(demo_conversations, demo_orders)

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
    _seen_message_ids.clear()

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

    # Channel connectors (Instagram / WhatsApp / Telegram), the per-seller
    # channel-connection store, and the token vault. The connectors are the ONLY
    # outbound path and are invoked solely by /api/approve — never by an agent.
    _state["channels"] = build_channel_registry(settings)
    _state["token_vault"] = (
        TokenVault(settings.token_encryption_key) if settings.token_encryption_key else None
    )
    channel_store: ChannelConnectionStore = InMemoryChannelStore()
    if data_source == "atlas" and settings.mongodb_uri:
        try:
            channel_store = MongoChannelStore(settings.mongodb_uri, settings.mongodb_database)
        except Exception:
            logger.exception("MongoChannelStore init failed — using in-memory channel store.")
            channel_store = InMemoryChannelStore()
    _state["channel_store"] = channel_store

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


class PasteConversationRequest(BaseModel):
    """A Tier-0 pasted DM: the seller copies a customer message in by hand."""

    text: str = Field(..., min_length=1, max_length=4000)
    customer_name: str = Field(default="Customer", max_length=80)
    channel: str = Field(default="Instagram DM", max_length=40)


@app.post("/api/conversations/paste", response_model=ConversationResponse)
async def paste_conversation(
    request: PasteConversationRequest, http_request: Request
) -> ConversationResponse:
    """Tier-0 channel fallback: paste a customer DM, get a grounded draft back.

    Until a channel's API path is live (Instagram is gated on Meta App Review),
    the seller pastes the customer's message here, runs "Draft with Asili", and
    copies the approved reply back into the app themselves. Clunky by design —
    the human does the sending inside the platform, which keeps the seller's
    account inside the channel's terms of service while still exercising the
    full grounded-draft -> approval -> instrumentation loop.
    """
    if _rate_limited(f"paste:{_client_key(http_request)}", max_calls=30, window_s=60.0):
        raise HTTPException(status_code=429, detail="rate limited")

    seller = _state.get("seller")
    if not seller:
        raise HTTPException(status_code=500, detail="Demo data not initialized")

    name = request.customer_name.strip() or "Customer"
    conversation = Conversation(
        seller_id=seller.id,
        customer_name=name,
        customer_initials=initials_of(name),
        channel=request.channel.strip() or "Instagram DM",
        status=ConversationStatus.AWAITING_REPLY,
    )
    conversation.add_message(
        direction=MessageDirection.INBOUND,
        sender_name=name,
        body=request.text.strip()[:MAX_INBOUND_CHARS],
    )
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


@app.get("/api/metrics")
async def get_metrics() -> dict[str, Any]:
    """Operating metrics — judge-inspectable proof of AI-native operation + unit economics.

    - ``autonomy``: how many decisions the AI executed at Tier-1 without per-action
      approval vs. held for the seller — the autonomy rate that converts "AI assists"
      into "AI operates."
    - ``cost``: priced model spend per seller/per call (cheaper for routine-tier
      volume) — the substrate for the cost-per-seller curve.
    - ``approvals``: per-seller ladder metrics — approval rate, unedited rate,
      edit distance, time-to-send — the learning-system evidence that autonomy
      is being earned (drafts approved verbatim → intents promoted to Tier-1).
    """
    return {
        "autonomy": autonomy.autonomy_stats(),
        "cost": cost.cost_stats(),
        "approvals": approvals.approval_stats(),
    }


@app.get("/api/followups")
async def get_followups(quiet_after_hours: float = 24.0) -> dict[str, Any]:
    """Open customer threads that have gone quiet — the follow-up work queue.

    Deterministic detection over the order/thread store (no LLM): which real
    threads are stale and how long they've been quiet. The Messaging Agent drafts
    re-engagement copy from this; the seller approves it.
    """
    threads = find_quiet_threads(quiet_after_hours)
    return {"count": len(threads), "quiet_after_hours": quiet_after_hours, "threads": threads}


@app.get("/api/invoices/unpaid")
async def get_unpaid_invoices(grace_hours: float = 0.0) -> dict[str, Any]:
    """Invoices sent but not paid and now overdue — the payment-chase work queue.

    Deterministic detection over the order store (no LLM): exact amounts and how
    overdue, so a nudge can quote the precise figure. The Messaging Agent drafts
    the reminder from this; the seller approves it.
    """
    invoices = find_unpaid_invoices(grace_hours)
    total = sum(float(i["amount"]) for i in invoices)
    return {
        "count": len(invoices),
        "grace_hours": grace_hours,
        "total_outstanding": round(total, 2),
        "invoices": invoices,
    }


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
    autonomy.reset_autonomy_stats()
    cost.reset_cost()
    approvals.reset_approval_stats()
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
                "created_at": time.time(),
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
async def run_baseline_agent(request: RunAgentsRequest, http_request: Request) -> dict[str, Any]:
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

    # Ladder instrumentation: every seller decision on a held draft is measured
    # (approval rate, edit distance, time-to-send) — the evidence that autonomy
    # is being earned per seller, not asserted.
    seller_key = str(conversation.seller_id)
    created_at = pending.get("created_at")
    time_to_send = (time.time() - float(created_at)) if created_at else None

    if request.action == "reject":
        approvals.record_outcome("reject", seller_id=seller_key)
        store.delete_pending(request.conversation_id)
        return ApprovalResponse(status="rejected", message=None)

    # Approve or edit
    original_body = str(pending.get("body", ""))
    final_body = str(
        request.edited_body if request.action == "edit" and request.edited_body else original_body
    )
    approvals.record_outcome(
        request.action,
        edit_distance=(
            approvals.normalized_edit_distance(original_body, final_body)
            if request.action == "edit"
            else None
        ),
        time_to_send_s=time_to_send,
        seller_id=seller_key,
    )

    # Deliver over the originating channel. This is the ONLY outbound path and
    # runs solely here, after the seller's approval — no agent can reach it.
    platform = pending.get("channel")
    recipient_id = pending.get("recipient_id") or pending.get("chat_id")
    telegram = _state.get("telegram")
    if platform == "telegram" and telegram is not None and recipient_id:
        # Dev/secondary channel: reuse the already-initialized single-bot client.
        try:
            await telegram.send_message(str(recipient_id), final_body)
        except Exception:
            logger.exception("Telegram delivery failed for %s", recipient_id)
    else:
        # Live channels (Instagram / WhatsApp) go through the connector seam with
        # the seller's own token, resolved + decrypted only here, at send time.
        registry = _state.get("channels") or {}
        connector = registry.get(platform) if platform else None
        if connector is not None and recipient_id:
            # The channel seller_id (string) is stamped on the pending draft for
            # multi-tenant token lookup; fall back to the conversation key.
            send_seller_id = str(pending.get("seller_id") or seller_key)
            access_token = _resolve_send_token(send_seller_id, str(platform))
            if access_token:
                send_kwargs: dict[str, Any] = {
                    "access_token": access_token,
                    "recipient_id": str(recipient_id),
                    "text": final_body,
                }
                # WhatsApp can only send free-form inside the 24h service window;
                # give the connector the last inbound time so it can enforce that.
                if platform == "whatsapp":
                    send_kwargs["last_inbound_at"] = _last_inbound_at(conversation)
                try:
                    outcome = await connector.send(**send_kwargs)
                    if not outcome.success:
                        logger.warning("%s delivery failed: %s", platform, outcome.error)
                except Exception:
                    logger.exception("%s delivery raised for %s", platform, recipient_id)
            else:
                logger.warning(
                    "No send credential for seller=%s platform=%s "
                    "(no stored connection token, or TOKEN_ENCRYPTION_KEY unset) "
                    "— not delivered",
                    seller_key,
                    platform,
                )

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
                "created_at": time.time(),
            },
        )
    return {"ok": True, "conversation_id": conversation_id, "pending": pending}


# ─────────────────────────────────────────────────────────────────────────────
# Channel connectors: Instagram + WhatsApp (Meta), multi-tenant by seller_id.
#
# These are the live customer-message path. Inbound webhooks normalize a DM into
# a Conversation scoped to the owning seller and hold a drafted reply at the
# approval gate; outbound only ever happens from /api/approve. No agent has a
# send tool and none of this changes that.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SELLER_ID = "demo"  # single-tenant fallback for legacy/demo callers
SELLER_HEADER = "x-asili-seller-id"  # set by the web ops proxy from the auth'd user

# Platforms whose inbound carries a unique per-seller account id, so a webhook
# can be routed to the owning seller via find_by_account. Telegram (one shared
# bot) is deliberately NOT here — it stays on its own single-tenant webhook.
MULTI_TENANT_PLATFORMS = frozenset({"instagram", "whatsapp"})

# String message-id idempotency for Meta webhooks (Telegram uses int update_id).
_seen_message_ids: OrderedDict[str, None] = OrderedDict()


def _seen_message(message_id: str | None) -> bool:
    """True if this message id was already processed (skip Meta retry redelivery)."""
    if not message_id:
        return False
    if message_id in _seen_message_ids:
        return True
    _seen_message_ids[message_id] = None
    while len(_seen_message_ids) > SEEN_UPDATE_CAP:
        _seen_message_ids.popitem(last=False)
    return False


def _seller_from_request(request: Request) -> str:
    """Acting seller from the ops-proxy header (multi-tenant); demo otherwise."""
    return request.headers.get(SELLER_HEADER) or DEFAULT_SELLER_ID


def _seller_uuid(seller_id: str) -> Any:
    """Deterministic UUID for a string seller_id (Conversation.seller_id is a UUID)."""
    return uuid5(NAMESPACE_URL, f"asili-seller:{seller_id}")


def _channel_store() -> ChannelConnectionStore | None:
    return _state.get("channel_store")


def _last_inbound_at(conversation: Conversation) -> datetime | None:
    """Timestamp of the most recent inbound message (for the WhatsApp 24h window)."""
    times = [
        (m.sent_at or m.created_at)
        for m in conversation.messages
        if m.direction == MessageDirection.INBOUND
    ]
    return max(times) if times else None


def _resolve_send_token(seller_id: str, platform: str) -> str | None:
    """Token used to deliver on a channel.

    Per-seller encrypted connection token is the multi-tenant path; Telegram has
    a single dev-bot env fallback so the dev channel works without a stored token.
    Tokens are decrypted only here, at send time, and never logged.
    """
    cstore = _channel_store()
    vault: TokenVault | None = _state.get("token_vault")
    if cstore is not None:
        conn = cstore.get(seller_id, platform)
        if conn and conn.encrypted_token and vault is not None:
            try:
                return vault.decrypt(conn.encrypted_token)
            except Exception:
                logger.exception("token decrypt failed seller=%s platform=%s", seller_id, platform)
                return None
    if platform == "telegram":
        return get_settings().telegram_bot_token
    return None


# OAuth state binds a connect flow to a seller and is HMAC-signed so it can't be
# forged by whoever lands on the callback. Format: base64url("seller|nonce|sig").
def _sign_oauth_state(seller_id: str) -> str:
    secret = get_settings().oauth_state_secret
    if not secret:
        # Fail closed: signing with an empty key would make every state forgeable.
        # The OAuth-start endpoint guards on this too, so this is defense in depth.
        raise RuntimeError("OAUTH_STATE_SECRET is not configured")
    nonce = secrets.token_urlsafe(16)  # CSPRNG; never a predictable counter
    payload = f"{seller_id}|{nonce}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()  # full 256-bit
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode().rstrip("=")


def _verify_oauth_state(state: str) -> str | None:
    secret = get_settings().oauth_state_secret
    if not secret:
        return None  # fail closed: no secret -> no valid state can exist
    try:
        raw = base64.urlsafe_b64decode(state + "===").decode()
        seller_id, nonce, sig = raw.rsplit("|", 2)
    except Exception:
        return None
    expected = hmac.new(
        secret.encode(), f"{seller_id}|{nonce}".encode(), hashlib.sha256
    ).hexdigest()
    return seller_id if hmac.compare_digest(sig, expected) else None


def _meta_webhook_challenge(request: Request) -> Response:
    """Meta GET verification handshake (shared by IG + WhatsApp webhooks)."""
    params = request.query_params
    token = get_settings().instagram_webhook_verify_token
    if params.get("hub.mode") == "subscribe" and token and params.get("hub.verify_token") == token:
        return Response(content=params.get("hub.challenge") or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="webhook verification failed")


async def _handle_channel_inbound(platform: str, request: Request) -> dict[str, Any]:
    """Shared inbound webhook: verify signature, route each DM to the owning
    seller by the receiving account, normalize into a per-seller Conversation,
    run the agents, and hold the drafted reply at the approval gate. Never sends.

    Only platforms whose inbound carries a per-seller account id (Instagram's
    business id, WhatsApp's phone-number id) may use this account-routed path.
    Telegram is intentionally excluded: it is a single shared bot, so every
    inbound would carry the same account sentinel and ``find_by_account`` could
    not tell sellers apart. Telegram is served only by its own single-tenant
    /api/telegram/webhook and is never resolved here.
    """
    if platform not in MULTI_TENANT_PLATFORMS:
        raise HTTPException(status_code=404, detail="channel not account-routable")
    registry = _state.get("channels") or {}
    connector = registry.get(platform)
    if connector is None:
        raise HTTPException(status_code=404, detail="channel not enabled")

    # Read the body once and cap on the ACTUAL bytes (Content-Length is spoofable).
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")

    # Verify the Meta signature on EVERY inbound call. Fail closed.
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not connector.verify_signature(raw, headers):
        raise HTTPException(status_code=401, detail="invalid signature")

    if _rate_limited(f"{platform}:{_client_key(request)}", max_calls=120, window_s=60.0):
        raise HTTPException(status_code=429, detail="rate limited")

    try:
        payload = json.loads(raw.decode() or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid payload")

    cstore = _channel_store()
    products = _state.get("products", [])
    policy = _state.get("policy")
    seller_catalog = _state.get("seller")

    handled = 0
    for inb in connector.parse_inbound(payload):
        # Route to the owning seller by the receiving account. No mapping -> ignore
        # (we never run a billable agent for an account we don't recognize).
        conn = cstore.find_by_account(platform, inb.recipient_account_id) if cstore else None
        if conn is None:
            logger.warning(
                "inbound %s for unmapped account %s — ignored",
                platform,
                inb.recipient_account_id,
            )
            continue
        # Idempotency: Meta redelivers on any non-2xx. Skip a message we've handled.
        if inb.message_id and _seen_message(f"{platform}:{inb.message_id}"):
            continue

        seller_id = conn.seller_id
        text = inb.text[:MAX_INBOUND_CHARS]
        # Namespace the conversation key by seller so the (single-tenant) global
        # store + approve path stay correct without leaking across tenants.
        conversation_id = f"{seller_id}:{platform}:{inb.external_thread_id}"
        store = _store()
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            conversation = Conversation(
                seller_id=_seller_uuid(seller_id),
                customer_name=inb.sender_name,
                customer_initials=initials_of(inb.sender_name),
                channel="Instagram DM" if platform == "instagram" else "WhatsApp",
                status=ConversationStatus.AWAITING_REPLY,
            )
        conversation.add_message(
            direction=MessageDirection.INBOUND,
            sender_name=inb.sender_name,
            body=text,
        )
        store.save_conversation(conversation_id, conversation)

        if not seller_catalog or not policy:
            continue

        # Ground a draft behind the approval gate (no auto-send).
        try:
            runner = create_runner(
                seller_catalog,
                products,
                policy,
                repository=_state.get("repository"),
                use_mcp=_state.get("use_mcp"),
            )
            result = await _run_with_timeout(
                run_agent_async(runner, text), what=f"{platform} agent run"
            )
        except Exception:
            logger.exception("Agent run failed for %s thread %s", platform, inb.external_thread_id)
            continue

        if result.success and result.draft:
            # WhatsApp send needs "phone_number_id:to"; IG sends to the customer id.
            send_recipient = (
                f"{inb.recipient_account_id}:{inb.external_thread_id}"
                if platform == "whatsapp"
                else inb.external_thread_id
            )
            store.set_pending(
                conversation_id,
                {
                    "draft_id": f"draft_{conversation_id}",
                    "body": result.draft,
                    "sources": result.draft_sources,
                    "status": "pending",
                    "channel": platform,
                    "recipient_id": send_recipient,
                    "seller_id": seller_id,
                    "created_at": time.time(),
                },
            )
        handled += 1

    return {"ok": True, "handled": handled}


@app.get("/api/instagram/oauth/start")
async def instagram_oauth_start(request: Request) -> RedirectResponse:
    """Begin the Instagram-Login connect flow: redirect the seller to Meta's
    authorize screen with a signed state that binds this flow to their seller_id.
    """
    settings = get_settings()
    if not (
        settings.meta_app_id and settings.instagram_redirect_uri and settings.oauth_state_secret
    ):
        # oauth_state_secret is required: without it we can't sign a forgery-proof
        # state, so we refuse to start the flow rather than emit a weak one.
        raise HTTPException(status_code=503, detail="Instagram connect not configured")
    seller_id = _seller_from_request(request)
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.instagram_redirect_uri,
        "response_type": "code",
        "scope": INSTAGRAM_SCOPES,
        "state": _sign_oauth_state(seller_id),
    }
    return RedirectResponse("https://www.instagram.com/oauth/authorize?" + urlencode(params))


@app.get("/api/instagram/oauth/callback")
async def instagram_oauth_callback(
    request: Request, code: str | None = None, state: str | None = None
) -> RedirectResponse:
    """Finish the connect flow: verify state, exchange the code for the seller's
    access token (using the app secret, which lives only here), encrypt + store
    the connection, and bounce back to the web onboarding step with a status.
    """
    settings = get_settings()
    app_base = (settings.public_app_base_url or "").rstrip("/")

    def _back(status: str) -> RedirectResponse:
        return RedirectResponse(f"{app_base}/onboarding?channel=instagram&status={status}")

    if not code or not state:
        return _back("error")
    seller_id = _verify_oauth_state(state)
    if not seller_id:
        return _back("error")
    if not (settings.meta_app_id and settings.meta_app_secret and settings.instagram_redirect_uri):
        return _back("error")

    vault = _state.get("token_vault")
    cstore = _channel_store()
    if vault is None or cstore is None:
        return _back("error")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                "https://api.instagram.com/oauth/access_token",
                data={
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.instagram_redirect_uri,
                    "code": code,
                },
            )
            tok = token_resp.json() if token_resp.content else {}
        access_token = tok.get("access_token")
        ig_account_id = str(tok.get("user_id")) if tok.get("user_id") is not None else None
    except Exception:
        # logger.error (not .exception): keep the secrets-handling exchange off
        # the traceback path so a code/secret can't ride along into the logs.
        logger.error("Instagram OAuth exchange failed")
        return _back("error")

    if not access_token or not ig_account_id:
        return _back("error")

    now = datetime.now(UTC)
    cstore.upsert(
        ChannelConnection(
            seller_id=seller_id,
            platform="instagram",
            status=ChannelStatus.CONNECTED,
            external_account_id=ig_account_id,
            encrypted_token=vault.encrypt(access_token),
            created_at=now,
            updated_at=now,
        )
    )
    return _back("connected")


@app.get("/api/instagram/webhook")
async def instagram_webhook_verify(request: Request) -> Response:
    return _meta_webhook_challenge(request)


@app.post("/api/instagram/webhook")
async def instagram_webhook(request: Request) -> dict[str, Any]:
    return await _handle_channel_inbound("instagram", request)


@app.get("/api/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request) -> Response:
    return _meta_webhook_challenge(request)


@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook(request: Request) -> dict[str, Any]:
    return await _handle_channel_inbound("whatsapp", request)


@app.get("/api/channels")
async def list_channels(request: Request) -> dict[str, Any]:
    """Per-seller channel connection status for the onboarding/dashboard UI."""
    seller_id = _seller_from_request(request)
    cstore = _channel_store()
    conns = {c.platform: c for c in (cstore.list_for_seller(seller_id) if cstore else [])}

    def _status(platform: str) -> dict[str, Any]:
        c = conns.get(platform)
        return {
            "status": c.status.value if c else "not_connected",
            "handle": c.external_handle if c else None,
            "connected_at": c.created_at.isoformat() if c else None,
        }

    settings = get_settings()
    return {
        "seller_id": seller_id,
        "channels": {
            "instagram": {**_status("instagram"), "available": bool(settings.meta_app_id)},
            "whatsapp": {**_status("whatsapp"), "available": settings.whatsapp_bsp_live},
            "telegram": {**_status("telegram"), "available": bool(settings.telegram_bot_token)},
        },
    }


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
