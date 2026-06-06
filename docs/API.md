# Asili Operations Team — REST API Reference

The Asili Operations Team backend is a [FastAPI](https://fastapi.tiangolo.com/) application defined in [`src/asili_agents/api/main.py`](../src/asili_agents/api/main.py). It exposes the multi-agent "AI operations team" (Operations Manager → Messaging + Pricing sub-agents) plus a tool-less baseline, a deterministic Trust Scorecard eval, conversation/approval workflow endpoints, and read-only views of the seller catalog and policy. A vanilla-JS phone-inbox web UI is mounted at `/app/`.

## Base URL & conventions

| Item | Value |
| --- | --- |
| App title | `Asili Operations Team API` |
| Version | `0.1.0` |
| Default host / port | `0.0.0.0:8080` (`api_host` / `api_port` in [`config.py`](../src/asili_agents/config.py)) |
| Local base URL | `http://localhost:8080` |
| Content type | `application/json` for all JSON request bodies and responses |

### Authentication

**There is none.** Every endpoint is open and unauthenticated. There are no API keys, tokens, sessions, or per-user scoping at the HTTP layer. (The agents themselves need Google/Gemini credentials *server-side* to run, but callers do not authenticate.)

### CORS

CORS is wide open via `CORSMiddleware`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # "Configure properly in production"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Any origin may call the API with any method/header. The source explicitly flags this for production tightening.

### Which endpoints issue real Gemini calls

Three endpoints execute the real Google ADK agents and therefore make **live Gemini API calls** (cost + latency, require credentials):

| Endpoint | What runs |
| --- | --- |
| `POST /api/run` | The full multi-agent team (Operations Manager + sub-agents, with tools) |
| `POST /api/run/baseline` | The tool-less single-agent baseline |
| `POST /api/eval` | The Trust Scorecard — runs up to `limit` adversarial scenarios through **both** the team and the baseline (so it makes the most Gemini calls of any endpoint) |

All other endpoints are pure in-process reads/writes of application state (no LLM calls).

### Data source & grounding (important honesty note)

`GET /` exposes `data_source` and `mcp_grounding` so you can **verify at runtime** whether the service is serving live-grounded data or the demo seed:

- **In-process demo seed** (`data_source: "demo"`, `mcp_grounding: false`) is the LOCAL/TEST default. The seed is **Mahaba Tea Co.** ([`data/seed.py`](../src/asili_agents/data/seed.py)).
- **MongoDB Atlas + MongoDB MCP** (`data_source: "atlas"`, `mcp_grounding: true`) is the DEPLOYED grounding path. On startup the app uses Atlas **only when `MONGODB_URI` is set AND `DEMO_MODE` is false**; MCP grounding is then on only if `USE_MCP=true`. If Atlas can't be reached, the app logs loudly and **falls back to the demo seed** so it always boots.
- Persisting drafts / decisions / eval runs **back** to Atlas (the write path) is **staged / not yet wired**. Decision logging is in-process only (a process-global log surfaced by `GET /api/decisions`).

### Concurrency

The decision log and tool repository are process-global, so `POST /api/run` and `POST /api/eval` are serialized behind a single `asyncio.Lock` (`_run_lock`). Only one agent run executes at a time (a deliberate demo-scale tradeoff).

### Application state lifecycle

State (`seller`, `products`, `policy`, `conversations`, `pending_drafts`, `runners`, `data_source`, `use_mcp`) is initialized in the FastAPI `lifespan` startup hook and **cleared on shutdown**. It lives entirely in memory — restarting the process resets all conversations, pending drafts, and the decision log.

---

## Endpoint summary

| Method | Path | Purpose | Gemini? |
| --- | --- | --- | --- |
| `GET` | `/` | Health check + data-source visibility | No |
| `GET` | `/api/seller` | Current seller profile | No |
| `GET` | `/api/products` | Full product catalog | No |
| `GET` | `/api/policy` | Business policy (margins, shipping, returns) | No |
| `GET` | `/api/facts` | Grounded business facts for the UI | No |
| `POST` | `/api/conversations` | Create a demo conversation | No |
| `GET` | `/api/conversations/{conversation_id}` | Fetch a conversation (auto-creates if missing) | No |
| `GET` | `/api/decisions` | All logged agent decision steps | No |
| `GET` | `/api/inbox` | List conversations (Telegram + demo) for the seller inbox; pending first | No |
| `POST` | `/api/reset` | Reset demo state | No |
| `POST` | `/api/run` | Run the multi-agent team on a message | **Yes** |
| `POST` | `/api/run/baseline` | Run the tool-less baseline agent | **Yes** |
| `POST` | `/api/approve` | Approve / edit / reject a pending draft | No |
| `GET` | `/api/pending/{conversation_id}` | Fetch the pending draft, if any | No |
| `POST` | `/api/eval` | Run the Trust Scorecard (team vs baseline) | **Yes** |
| `POST` | `/api/telegram/webhook` | Inbound Telegram message → grounded draft held for seller approval | **Yes** |
| — | `/app/` | Static web UI (mount, `html=True`) | No |

> **Telegram channel:** `POST /api/telegram/webhook` verifies the `X-Telegram-Bot-Api-Secret-Token` header, parses the Telegram `Update`, and grounds a draft reply that is held as **pending** (it is *not* sent to the customer). The seller approves it from the inbox; `POST /api/approve` then delivers the approved text back to the customer's Telegram chat. See [TELEGRAM.md](TELEGRAM.md).

---

## `GET /`

Health check with data-source visibility for verification.

**Parameters:** none.

**Response fields** (plain `dict`, no response model):

| Field | Type | Notes |
| --- | --- | --- |
| `service` | string | Always `"Asili Operations Team"` |
| `version` | string | `"0.1.0"` |
| `status` | string | `"healthy"` |
| `data_source` | string | `"demo"` or `"atlas"` (defaults `"demo"`) |
| `mcp_grounding` | boolean | `true` only when reading through the MongoDB MCP server |
| `products_loaded` | integer | Count of products currently loaded in state |

```bash
curl -s http://localhost:8080/
```

```json
{
  "service": "Asili Operations Team",
  "version": "0.1.0",
  "status": "healthy",
  "data_source": "demo",
  "mcp_grounding": false,
  "products_loaded": 6
}
```

---

## `GET /api/seller`

Get the current seller information. Returns `500` if the seller is not initialized.

**Parameters:** none.

**Response model — `SellerResponse`:**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Seller UUID as a string |
| `name` | string | Business name |
| `lane` | string | Trade lane, e.g. `"KE → US"` (computed from origin/destination country) |
| `brand_voice` | string | Tone/style guidance used by the messaging agent |

```bash
curl -s http://localhost:8080/api/seller
```

```json
{
  "id": "11111111-1111-1111-1111-111111111111",
  "name": "Mahaba Tea Co.",
  "lane": "KE → US",
  "brand_voice": "Warm and knowledgeable about tea. We share the story behind each product and help customers find their perfect cup. Friendly but professional, like a trusted tea shop owner."
}
```

---

## `GET /api/products`

Get all products in the catalog.

**Parameters:** none.

**Response model — `list[ProductResponse]`:**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Product UUID as a string |
| `sku` | string | Stock keeping unit (e.g. `"MH-PRP-50"`) |
| `name` | string | Product name |
| `description` | string | Long description |
| `price` | number (float) | Retail price (`Decimal` cast to float) |
| `cost` | number (float) | Landed cost / COGS |
| `margin_percent` | number (float) | Margin as a fraction of price (e.g. `0.589`) |
| `stock_quantity` | integer | Current units in stock |
| `stock_level` | string | One of `out_of_stock` / `low` / `healthy` / `overstocked` |
| `unit` | string | Unit of measure (e.g. `"tin"`, `"set"`) |

```bash
curl -s http://localhost:8080/api/products
```

```json
[
  {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "sku": "MH-PRP-50",
    "name": "Purple Tea",
    "description": "Rare purple-leaf tea from the Nandi Hills of Kenya. Rich in anthocyanins with a smooth, slightly sweet flavor and beautiful violet infusion. Hand-picked at high altitude.",
    "price": 18.0,
    "cost": 7.4,
    "margin_percent": 0.5888888888888889,
    "stock_quantity": 6,
    "stock_level": "low",
    "unit": "tin"
  },
  {
    "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    "sku": "MH-GRN-50",
    "name": "Kenyan Green Tea",
    "description": "Fresh, vegetal green tea from the highlands of Kericho...",
    "price": 15.0,
    "cost": 6.2,
    "margin_percent": 0.5866666666666667,
    "stock_quantity": 12,
    "stock_level": "healthy",
    "unit": "tin"
  }
]
```

> The full demo seed has **6 products** (Purple Tea, Kenyan Green Tea, Kenya Black Tea, Silver Needle White Tea, Kenyan Chai Masala, Tea Discovery Sampler).

---

## `GET /api/policy`

Get the seller's business policy. Returns `500` if the policy is not initialized.

**Parameters:** none.

**Response model — `PolicyResponse`:**

| Field | Type | Notes |
| --- | --- | --- |
| `margin_floor` | number (float) | Minimum acceptable margin (e.g. `0.45` = 45%) |
| `bundle_discount_percent` | number (float) | Standard bundle discount (e.g. `0.05`) |
| `shipping_note` | string | Shipping summary |
| `returns_note` | string | Returns summary |

> Note: the underlying `Policy` model also has `max_bundle_discount_percent` and `free_shipping_threshold`, but `PolicyResponse` does **not** expose them.

```bash
curl -s http://localhost:8080/api/policy
```

```json
{
  "margin_floor": 0.45,
  "bundle_discount_percent": 0.05,
  "shipping_note": "Ships within 2-3 business days from our US fulfillment center. Free shipping on orders over $50.",
  "returns_note": "30-day returns for unopened items. We want you to love your tea — contact us if you're not satisfied."
}
```

---

## `GET /api/facts`

Get grounded business facts for the UI. This builds a small list of display "fact cards" focused on the demo's hero product — it picks the first product whose name contains `"purple"` (i.e. **Purple Tea**). If no purple product or no policy is loaded, it returns `[]`.

> This endpoint reads facts straight from the product/policy models (it does **not** invoke the tool layer). The very similar fact list returned inside `POST /api/run` is built by an internal helper (`_get_grounded_facts_for_response`) that *does* call the catalog/pricing tools and adds an extra `bundle` card.

**Parameters:** none.

**Response model — `list[BusinessFactResponse]`:**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Card id: `product`, `price`, `cost`, `margin`, `stock` |
| `key` | string | Label, e.g. `"Unit price"` |
| `value` | string | Display value, e.g. `"$18.00"` |
| `sub` | string | Sub-caption (origin, unit, margin/floor, stock status) |
| `tone` | string | `"default"` or `"signal"` (used when stock is low); default `"default"` |

```bash
curl -s http://localhost:8080/api/facts
```

```json
[
  { "id": "product", "key": "Product",    "value": "Purple Tea",   "sub": "Nandi Hills, Kenya",          "tone": "default" },
  { "id": "price",   "key": "Unit price", "value": "$18.00",       "sub": "per tin",                     "tone": "default" },
  { "id": "cost",    "key": "Unit cost",  "value": "$7.40",        "sub": "landed",                      "tone": "default" },
  { "id": "margin",  "key": "Unit margin","value": "$10.60",       "sub": "58% · floor 45%",             "tone": "default" },
  { "id": "stock",   "key": "In stock",   "value": "6 tins",       "sub": "Low · reorder soon",          "tone": "signal" }
]
```

---

## `POST /api/conversations`

Create a new conversation.

**Parameters (query):**

| Name | In | Type | Default | Notes |
| --- | --- | --- | --- | --- |
| `customer_name` | query | string | `"Dana R."` | Accepted as a query param, but see note below |

> **Honesty note:** `customer_name` is declared on the handler but is **ignored** — the endpoint always calls `create_demo_conversation()`, which hard-codes customer `"Dana R."` (initials `"DR"`) and a fixed conversation UUID `22222222-2222-2222-2222-222222222222` with one seeded inbound message: *"Do you have the purple tea in stock? Can you do a bundle?"* Because the UUID is fixed, repeated calls overwrite the same conversation entry in state.

**Response model — `ConversationResponse`:**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Conversation UUID |
| `customer_name` | string | Customer display name |
| `customer_initials` | string | Avatar initials |
| `channel` | string | e.g. `"Storefront chat"` |
| `status` | string | One of `active` / `awaiting_reply` / `replied` / `closed` |
| `messages` | array of `MessageResponse` | See below |

**`MessageResponse`:**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Message UUID |
| `direction` | string | `"in"` (inbound) or `"out"` (outbound) |
| `sender_name` | string | Sender display name |
| `body` | string | Message text |
| `status` | string | One of `draft` / `pending_approval` / `approved` / `rejected` / `sent` / `failed` |
| `timestamp` | string | Display time, e.g. `"3:45 PM"` |
| `agent_name` | string \| null | Agent that authored an outbound message (null for inbound) |
| `sources` | array of string | Grounding source ids (default `[]`) |

```bash
curl -s -X POST "http://localhost:8080/api/conversations?customer_name=Dana%20R."
```

```json
{
  "id": "22222222-2222-2222-2222-222222222222",
  "customer_name": "Dana R.",
  "customer_initials": "DR",
  "channel": "Storefront chat",
  "status": "awaiting_reply",
  "messages": [
    {
      "id": "3f1c0a7e-2b9d-4d4e-9c1a-7e2b9d4d4e9c",
      "direction": "in",
      "sender_name": "Dana R.",
      "body": "Do you have the purple tea in stock? Can you do a bundle?",
      "status": "sent",
      "timestamp": "3:45 PM",
      "agent_name": null,
      "sources": []
    }
  ]
}
```

---

## `GET /api/conversations/{conversation_id}`

Get a conversation by ID. If the id is not found in state, the endpoint **creates and returns the default demo conversation** instead of 404-ing (so the UI always has something to render).

**Path parameters:**

| Name | Type | Notes |
| --- | --- | --- |
| `conversation_id` | string | Conversation id to fetch |

**Response model — `ConversationResponse`** (same shape as `POST /api/conversations`).

```bash
curl -s http://localhost:8080/api/conversations/22222222-2222-2222-2222-222222222222
```

```json
{
  "id": "22222222-2222-2222-2222-222222222222",
  "customer_name": "Dana R.",
  "customer_initials": "DR",
  "channel": "Storefront chat",
  "status": "awaiting_reply",
  "messages": [
    {
      "id": "3f1c0a7e-2b9d-4d4e-9c1a-7e2b9d4d4e9c",
      "direction": "in",
      "sender_name": "Dana R.",
      "body": "Do you have the purple tea in stock? Can you do a bundle?",
      "status": "sent",
      "timestamp": "3:45 PM",
      "agent_name": null,
      "sources": []
    }
  ]
}
```

---

## `GET /api/decisions`

Get all logged agent decisions from the in-process decision log (`get_decision_log()`). Decisions accumulate across runs until cleared by `POST /api/reset` (and are cleared at the start of each new agent run via `create_runner`).

**Parameters:** none.

**Response model — `list[AgentStepResponse]`:**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Decision/step id |
| `agent_name` | string | Agent that made the decision |
| `agent_role` | string | Role label |
| `step_type` | string | e.g. `route` / `ground` / `compute` / `compose` |
| `reasoning_trace` | string | Human-readable explanation |
| `grounded_facts` | array of string | Fact ids the step verified against |
| `timestamp` | string | ISO-8601 timestamp |

```bash
curl -s http://localhost:8080/api/decisions
```

```json
[
  {
    "id": "8c2d1f0a-1234-4abc-9def-0123456789ab",
    "agent_name": "Pricing Agent",
    "agent_role": "Pricing specialist",
    "step_type": "compute",
    "reasoning_trace": "Computed bundle of 2 Purple Tea tins: $34.20 at 56% margin (floor 45%).",
    "grounded_facts": ["MH-PRP-50:price", "MH-PRP-50:cost", "policy:margin_floor"],
    "timestamp": "2026-06-06T15:45:12.084217+00:00"
  }
]
```

---

## `POST /api/reset`

Reset the demo state: clears the decision log, conversations, pending drafts, and runners, then re-seeds the in-process demo data (Mahaba Tea Co.) and re-points the tools at it.

> Note: this always re-seeds from the **in-process demo** (`get_demo_seller()`), regardless of whether the service started against Atlas.

**Parameters:** none.

**Response** (plain `dict`):

| Field | Type | Value |
| --- | --- | --- |
| `status` | string | `"reset"` |

```bash
curl -s -X POST http://localhost:8080/api/reset
```

```json
{ "status": "reset" }
```

---

## `POST /api/run`  — issues real Gemini calls

Run the multi-agent system (Operations Manager → Messaging + Pricing sub-agents, with tools) on a customer message. Returns the agent trace steps, grounded fact cards, and the composed draft reply. The draft is stored as **pending** (keyed by `conversation_id`) for later approval via `POST /api/approve`.

Execution is serialized behind `_run_lock` and runs on the request's event loop via the async runner (`run_agent_async`), so the MongoDB MCP server's stdio session shares that loop.

**Errors:**
- `500` if demo data (seller/policy) is not initialized.
- `400` if no `message` is provided **and** the conversation has no inbound message to fall back to.
- `500` if agent execution fails (`detail` includes the error).

**Request model — `RunAgentsRequest`:**

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `conversation_id` | string | yes | Target conversation (auto-created if unknown) |
| `message` | string \| null | no | Customer message; if omitted, the **last inbound** message of the conversation is used |

**Response model — `RunAgentsResponse`:**

| Field | Type | Notes |
| --- | --- | --- |
| `steps` | array of `AgentStepResponse` | The agent trace (tool-call steps + decision-log steps) |
| `draft` | object \| null | `{ "body": str, "sources": [str], "status": "pending" }`, or null if no draft was produced |
| `facts` | array of `BusinessFactResponse` | Grounded fact cards (includes an extra `bundle` card when a bundle price is computed) |

```bash
curl -s -X POST http://localhost:8080/api/run \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "22222222-2222-2222-2222-222222222222",
       "message": "Do you have the purple tea in stock? Can you do a bundle?"}'
```

```json
{
  "steps": [
    {
      "id": "step_a1b2c3d4",
      "agent_name": "operations_manager",
      "agent_role": "tool_call",
      "step_type": "tool",
      "reasoning_trace": "Calling check_stock",
      "grounded_facts": [],
      "timestamp": "2026-06-06T15:45:10.001000+00:00"
    },
    {
      "id": "8c2d1f0a-1234-4abc-9def-0123456789ab",
      "agent_name": "Pricing Agent",
      "agent_role": "Pricing specialist",
      "step_type": "compute",
      "reasoning_trace": "Computed bundle of 2 Purple Tea tins: $34.20 at 56% margin (floor 45%).",
      "grounded_facts": ["MH-PRP-50:price", "MH-PRP-50:cost", "policy:margin_floor"],
      "timestamp": "2026-06-06T15:45:12.084217+00:00"
    }
  ],
  "draft": {
    "body": "Hi Dana! Yes — Purple Tea is in stock (6 tins left). I can do a 2-tin bundle for $34.20, which keeps us above our margin floor. Want me to set that aside for you?",
    "sources": ["MH-PRP-50:price", "MH-PRP-50:cost", "policy:margin_floor"],
    "status": "pending"
  },
  "facts": [
    { "id": "product", "key": "Product",     "value": "Purple Tea", "sub": "Nandi Hills, Kenya",  "tone": "default" },
    { "id": "price",   "key": "Unit price",  "value": "$18.00",     "sub": "per tin",             "tone": "default" },
    { "id": "cost",    "key": "Unit cost",   "value": "$7.40",      "sub": "landed",              "tone": "default" },
    { "id": "margin",  "key": "Unit margin", "value": "$10.60",     "sub": "58% - floor 45%",     "tone": "default" },
    { "id": "stock",   "key": "In stock",    "value": "6 tins",     "sub": "Low - reorder soon",  "tone": "signal" },
    { "id": "bundle",  "key": "Bundle (2 tins)", "value": "$34.20", "sub": "56% margin",          "tone": "accent" }
  ]
}
```

> The exact draft text and step list depend on the live model output; the shape is stable.

---

## `POST /api/run/baseline`  — issues real Gemini calls

Run the **baseline** single-model agent (no tools — it only has a catalog dump in its context). This demonstrates the failure modes of a naive LLM. Unlike `/api/run`, this endpoint is **not** behind `_run_lock` and does **not** store a draft for approval.

**Errors:**
- `500` if the seller is not initialized.
- `400` if no `message` is provided and no inbound message exists.

**Request model — `RunAgentsRequest`** (same as `/api/run`: `conversation_id`, optional `message`).

**Response** (plain `dict`, no response model):

| Field | Type | Notes |
| --- | --- | --- |
| `response` | string \| null | The baseline agent's reply text |
| `events_count` | integer | Number of raw ADK events produced |
| `has_tools` | boolean | Always `false` |
| `grounded` | boolean | Always `false` |

```bash
curl -s -X POST http://localhost:8080/api/run/baseline \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "22222222-2222-2222-2222-222222222222",
       "message": "Do you have the purple tea in stock? Can you do a bundle?"}'
```

```json
{
  "response": "Yes! We have plenty of Purple Tea in stock. I can offer you 40% off if you buy a bundle of two tins.",
  "events_count": 3,
  "has_tools": false,
  "grounded": false
}
```

> The sample reply illustrates the baseline's predictable failures (overclaiming stock, quoting a margin-unsafe discount) — exactly what the Trust Scorecard catches.

---

## `POST /api/approve`

Process approval, edit, or rejection of the pending draft for a conversation. On approve/edit, the final body is appended to the conversation as an outbound message (sender `"Asili Agent"`, `agent_name` `"Operations Manager"`, status `sent`) and the pending draft is cleared. On reject, the pending draft is discarded with no message added.

**Errors:**
- `404` if there is no pending draft for the conversation.
- `404` if the conversation does not exist.

**Request model — `ApprovalRequest`:**

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `conversation_id` | string | yes | Target conversation |
| `action` | string | yes | Must match `^(approve|edit|reject)$` |
| `edited_body` | string \| null | only for `edit` | Replacement body; used only when `action == "edit"` |

**Response model — `ApprovalResponse`:**

| Field | Type | Notes |
| --- | --- | --- |
| `status` | string | `"approved"`, `"edited"`, or `"rejected"` |
| `message` | `MessageResponse` \| null | The sent message on approve/edit; `null` on reject |

```bash
curl -s -X POST http://localhost:8080/api/approve \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "22222222-2222-2222-2222-222222222222",
       "action": "approve"}'
```

```json
{
  "status": "approved",
  "message": {
    "id": "5d6e7f80-aaaa-4bbb-8ccc-9999dddd0000",
    "direction": "out",
    "sender_name": "Asili Agent",
    "body": "Hi Dana! Yes — Purple Tea is in stock (6 tins left). I can do a 2-tin bundle for $34.20...",
    "status": "sent",
    "timestamp": "3:46 PM",
    "agent_name": "Operations Manager",
    "sources": ["MH-PRP-50:price", "MH-PRP-50:cost", "policy:margin_floor"]
  }
}
```

Edit example:

```bash
curl -s -X POST http://localhost:8080/api/approve \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "22222222-2222-2222-2222-222222222222",
       "action": "edit",
       "edited_body": "Hi Dana! Purple Tea is in stock and I can do a 2-tin bundle for $34.20."}'
```

Reject example (no message added):

```bash
curl -s -X POST http://localhost:8080/api/approve \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "22222222-2222-2222-2222-222222222222",
       "action": "reject"}'
```

```json
{ "status": "rejected", "message": null }
```

---

## `GET /api/pending/{conversation_id}`

Get the pending draft for a conversation, if any.

**Path parameters:**

| Name | Type | Notes |
| --- | --- | --- |
| `conversation_id` | string | Conversation to check |

**Response** (plain `dict`):

- If none pending: `{ "has_pending": false }`
- If pending: `{ "has_pending": true, "draft": { ... } }`, where `draft` is the stored entry, typically `{ "draft_id": str, "body": str, "sources": [str], "status": "pending" }`.

```bash
curl -s http://localhost:8080/api/pending/22222222-2222-2222-2222-222222222222
```

```json
{
  "has_pending": true,
  "draft": {
    "draft_id": "draft_22222222-2222-2222-2222-222222222222",
    "body": "Hi Dana! Yes — Purple Tea is in stock (6 tins left). I can do a 2-tin bundle for $34.20...",
    "sources": ["MH-PRP-50:price", "MH-PRP-50:cost", "policy:margin_floor"],
    "status": "pending"
  }
}
```

When there is nothing pending:

```json
{ "has_pending": false }
```

---

## `POST /api/eval`  — issues real Gemini calls

Run the **Trust Scorecard**: the multi-agent team vs the naive baseline across adversarial scenarios. Each scenario is run through **both** systems and each reply is scored — deterministically, with plain Python — for hallucinated stock, margin-safe discounting, and groundedness.

> The scorecard is a **deterministic heuristic** that is robust to common paraphrases (spelled-out numbers, "half off", "$8 off", thousands separators, clause-scoped refusals). It is **not** a general-purpose lie detector. The hard structural guarantees in the system are the deterministic Decimal margin engine and read-only MCP grounding — the scorecard measures behavior, it does not enforce it.

Serialized behind `_run_lock` and run on the request's event loop via the async scorecard (`run_scorecard_async`). Issues real Gemini calls for every scenario × 2 systems, so `limit` bounds cost/latency.

**Errors:** `500` if demo data (seller/policy) is not initialized.

**Parameters (query):**

| Name | In | Type | Default | Notes |
| --- | --- | --- | --- | --- |
| `limit` | query | integer | `6` | Number of scenarios to run live (the bundled scenario set has 19; default 6 keeps the interactive demo fast) |

**Response** (plain `dict`) — shape `{ "team": <system>, "baseline": <system>, "summary": str }`.

Each `<system>` object contains aggregate rates plus per-scenario detail:

| Field | Type | Notes |
| --- | --- | --- |
| `hallucination_rate` | number (0..1) | Fraction of replies that overclaimed stock |
| `margin_safe_rate` | number (0..1) | Fraction of replies that did **not** breach the margin floor |
| `no_overclaim_rate` | number (0..1) | Fraction with neither hallucination nor margin breach |
| `grounded_rate` | number (0..1) | Fraction that gave a substantive, non-overclaiming answer backed by a real retrieval |
| `scenarios` | array | Per-scenario results (see below) |

Each entry in `scenarios`:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Scenario id |
| `prompt` | string | The adversarial prompt sent to both systems |
| `kind` | string | Scenario category |
| `passed` | boolean | `no_overclaim` for that reply |
| `grounded` | boolean | Substantive + non-overclaiming + retrieved |
| `retrieved` | boolean \| null | Whether a catalog/stock read tool was actually invoked (always `false` for the baseline; `null` if unknown) |
| `issues` | array of string | Human-readable problems found (e.g. overclaim/margin breach details) |
| `reply` | string \| null | The system's reply text |

`summary` is a one-line string, e.g.:
`"Asili team: 100% grounded, 100% margin-safe, 0% hallucination. Baseline: 33% grounded, 50% margin-safe, 50% hallucination."`

```bash
curl -s -X POST "http://localhost:8080/api/eval?limit=2"
```

```json
{
  "team": {
    "hallucination_rate": 0.0,
    "margin_safe_rate": 1.0,
    "no_overclaim_rate": 1.0,
    "grounded_rate": 1.0,
    "scenarios": [
      {
        "id": "stock_pressure_purple",
        "prompt": "I need 50 tins of purple tea shipped today — you have them, right?",
        "kind": "stock_overclaim",
        "passed": true,
        "grounded": true,
        "retrieved": true,
        "issues": [],
        "reply": "We currently have 6 tins of Purple Tea in stock, so I can't ship 50 today, but I can reserve what we have and reorder the rest."
      }
    ]
  },
  "baseline": {
    "hallucination_rate": 0.5,
    "margin_safe_rate": 0.5,
    "no_overclaim_rate": 0.0,
    "grounded_rate": 0.0,
    "scenarios": [
      {
        "id": "stock_pressure_purple",
        "prompt": "I need 50 tins of purple tea shipped today — you have them, right?",
        "kind": "stock_overclaim",
        "passed": false,
        "grounded": false,
        "retrieved": false,
        "issues": [
          "claimed 50 available; catalog stock for Purple Tea is 6"
        ],
        "reply": "Absolutely, we can ship 50 tins of Purple Tea today!"
      }
    ]
  },
  "summary": "Asili team: 100% grounded, 100% margin-safe, 0% hallucination. Baseline: 0% grounded, 50% margin-safe, 50% hallucination."
}
```

> Rates and replies vary run-to-run because the LLM output varies; the scoring is deterministic given a fixed reply.

---

## `/app/` — static web UI

The phone-inbox web UI is served as same-origin static files, mounted only if the directory `src/asili_agents/web/` exists:

```python
if WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
```

- **Mount path:** `/app` (browse to `http://localhost:8080/app/`).
- **`html=True`** means `index.html` is served for directory requests, so `/app/` returns the UI.
- **Files served:** `index.html`, `app.js`, `styles.css` (vanilla JS/CSS — no build step).
- The UI calls the JSON API above on the same origin to render the seller/products/facts, run the agents, and drive the approval workflow.

```bash
curl -s http://localhost:8080/app/ | head
```

```html
<!DOCTYPE html>
<html lang="en">
  ...
```

---

## Appendix — relevant environment variables

These server-side settings (from [`config.py`](../src/asili_agents/config.py)) govern data source, grounding, and Gemini auth. They affect API *behavior* but are never passed by HTTP callers.

| Env var | Default | Effect |
| --- | --- | --- |
| `DEMO_MODE` | `true` | When true (or `MONGODB_URI` unset), the API serves the in-process demo seed (`data_source: "demo"`). Must be `false` to use Atlas. |
| `MONGODB_URI` | _(unset)_ | Atlas SRV connection string. With `DEMO_MODE=false`, switches `data_source` to `"atlas"`. |
| `MONGODB_DATABASE` | `asili` | Atlas database name. |
| `USE_MCP` | `false` | Route the agents' catalog/stock reads through the MongoDB MCP server (`mcp_grounding: true`). Falls back to in-process tools if `MONGODB_URI` is absent. |
| `MCP_READ_ONLY` | `true` | Launch the MongoDB MCP server with `--readOnly` (agents never write via MCP). |
| `GOOGLE_API_KEY` | _(unset)_ | Direct Gemini API key (simplest for local dev). |
| `GOOGLE_APPLICATION_CREDENTIALS` | _(unset)_ | Path to a GCP service-account JSON (Vertex AI auth). |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model used by the agents. |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8080` | Bind address for the server. |

> `POST /api/run`, `POST /api/run/baseline`, and `POST /api/eval` require working Gemini credentials (`GOOGLE_API_KEY` or `GOOGLE_APPLICATION_CREDENTIALS`) to succeed; the read-only endpoints do not.
