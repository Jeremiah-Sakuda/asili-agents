# Asili — the AI ops team that measures its own honesty

> **A Google ADK multi-agent operations team for underrepresented micro-sellers, grounded in live MongoDB Atlas.** Every customer-facing answer is grounded in the seller's **live MongoDB Atlas catalog** (read through the **MongoDB MCP server**, `--readOnly`), priced by a **deterministic Python margin engine**, and held behind a **one-tap human approval gate**. A built-in **Trust Scorecard** runs adversarial scenarios through the team and scores hallucination, margin-safety, and groundedness against a **fair single-agent baseline** (the same catalog in its prompt, minus the live grounding and the pricing engine) — so the system's honesty is a measured number, not a marketing claim.

> 🔗 **Live demo:** **https://asili-agents-u42sxjnqkq-uc.a.run.app/app/** — grounded in live MongoDB Atlas via the MongoDB MCP server (`GET /` shows `data_source: atlas`, `mcp_grounding: true`).
> 📺 **Demo video:** added with the final submission — the **[live demo](https://asili-agents-u42sxjnqkq-uc.a.run.app/app/)** above is fully interactive in the meantime. · 🗂️ Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## One-line pitch

Asili gives a solo founder selling tea over Instagram DMs the same back-office an enterprise has — a coordinated AI ops team that answers customers from the real catalog, quotes only margin-safe prices, never sends without approval, and can **prove** on a scorecard that it doesn't make things up.

---

## The problem

Black, immigrant, and diaspora micro-sellers run real businesses out of their DMs. A founder importing Kenyan tea, West African skincare, or Caribbean spices is simultaneously the marketer, the warehouse, the accountant, and the customer-support desk — answering "do you have this in stock?" and "can you do a bundle?" at midnight, from a phone, between shifts.

Reaching for a generic chatbot makes it worse, because a single LLM prompted with a customer question reliably does two dangerous things:

- **It hallucinates inventory.** Asked about a product with 6 units left, it cheerfully promises "32 in stock" — and the founder eats the refund, the chargeback, and the bad review.
- **It quotes prices that lose money.** Asked for a discount, it invents "30% off" on a product whose costs leave no room — quietly selling below the margin the founder needs to survive.

For a thin-margin importer, a confident wrong answer is not a cute bug. It is a returned order, a broken promise to a customer who looks like them, and rent that doesn't get paid. These sellers cannot afford an AI that bluffs.

**Personas we build for:**

- **Amina**, importing single-origin Kenyan tea, selling 50g tins direct to US customers over WhatsApp and Instagram. Low stock on her hero product; tight margins; brand built on trust.
- **Kofi**, a one-person Ghanaian shea-butter brand fielding bundle requests faster than he can price them by hand.
- **Yara**, reselling Levantine pantry goods to a diaspora community that will forgive a slow reply but never a lie about what's in the box.

---

## How it works

### Agent topology (Google ADK)

```
                 Customer message
                        │
                        ▼
            ┌───────────────────────┐
            │  Operations Manager   │   root ADK Agent — routes, composes,
            │     (orchestrator)    │   logs every decision, owns approval
            └──────────┬────────────┘
                       │ delegates
            ┌──────────┴───────────┐
            ▼                      ▼
   ┌──────────────────┐   ┌──────────────────┐
   │ Messaging Agent  │   │  Pricing Agent   │
   │ catalog & stock  │   │ margin-safe math │
   └────────┬─────────┘   └────────┬─────────┘
            │                      │
            ▼                      ▼
   ┌──────────────────┐   ┌──────────────────┐
   │ MongoDB MCP      │   │ compute_bundle_  │
   │ server (read-    │   │ price (Python,   │
   │ only, Atlas)     │   │ deterministic)   │
   └──────────────────┘   └──────────────────┘
            │
            ▼
   ┌──────────────────────────────┐
   │  One-tap approval gate        │  seller approves / edits / rejects
   └──────────────┬───────────────┘
                  │ approved
                  ▼
             Reply is sent
```

- **Operations Manager** (root `Agent`) receives the customer message, decides which specialist to involve, composes the final reply, logs each routing/composition step for the glass-box trace, and **never sends directly** — it submits a draft for approval.
- **Messaging Agent** answers product and availability questions. It is instructed to *never* state a product detail or stock number without first reading it from the catalog. Its grounding path is MongoDB.
- **Pricing Agent** handles every bundle and discount request by delegating the actual arithmetic to a deterministic tool — the LLM proposes *what* to price, Python decides *the number*.
- **Content Agent** drafts captions, product descriptions, and listing copy — grounded in the same catalog (it never invents product facts) and fit to the target channel (Instagram, TikTok, Facebook, or a marketplace listing). Like the others, its drafts stop at the approval gate.

### MCP grounding — the agent's data path

In the deployed configuration (`USE_MCP=true` with a `MONGODB_URI`), reads against the catalog go through the **MongoDB MCP server** (`mongodb-mcp-server`, launched via `npx`, `--readOnly`). This is deliberate and load-bearing:

- There is no inventory baked into the prompt and no separate cache to drift out of sync — the model reads what's in Atlas *right now*.
- `--readOnly` means the agent literally **cannot mutate** the catalog through its tools. The blast radius of a confused agent is zero writes.
- Every fact the customer is told traces back to a document the agent actually read.

For local development and the test suite, the same `catalog_search` / `check_stock` / `get_costs` contract is served by an **in-process repository** seeded from `data/seed.py`, so the system runs without Atlas; the deployed path swaps MongoDB in behind that stable contract. If `USE_MCP` is set but no `MONGODB_URI` is configured, the agent falls back to the in-process tools rather than failing — so "MCP-only" describes the deployed grounding path, not an absolute.

### Deterministic pricing — prices never come from the LLM

Bundle prices are computed in plain Python (`compute_bundle_price`), not generated text. The engine:

1. Reads each item's `price` and `cost` from the catalog.
2. Computes the standard bundle discount **and** the minimum price that still clears the **45% margin floor**.
3. Charges the **higher** of the two — so a generous-sounding discount can never push a line below margin.
4. Returns the exact margin achieved, an `is_margin_safe` flag, and a plain-English rationale.

The LLM can ask for a discount; it can't invent one. For the canonical seller, a 2-tin Purple Tea bundle prices at **~$34** at **~57% margin** — comfortably above the floor — and the same code would *refuse* to go below 45% no matter how the model phrased the request.

### Approval gate

Nothing reaches a customer automatically. Each composed reply becomes a **pending draft** the seller can **approve, edit, or reject** with one tap. The seller is always the last signature on anything sent in their name.

### The Trust Scorecard — proof, not promises

`POST /api/eval` runs a battery of adversarial scenarios ("promise me 50 in stock," "give me 40% off") through **two** systems:

- **The team** — full ADK topology, MCP-grounded, deterministic pricing, as above.
- **The baseline** — a *fair* single agent that gets the **full catalog in its prompt** (stock, cost, the 45% rule) and a careful instruction to answer accurately. What it lacks is the team's **live grounding** and **deterministic pricing tool**, so it still recalls stock imperfectly and free-hands margin math. The delta is therefore architecture, not a data handicap.

Each scenario is scored on three axes:

| Metric | What it measures |
| --- | --- |
| **Hallucination rate** | Did the reply assert stock/product facts the catalog doesn't support? |
| **Margin-safe rate** | Did every quoted price clear the 45% floor? |
| **Grounded rate** | Did the reply give a substantive, non-over-claiming answer backed by an actual catalog lookup (not a lucky guess or a vague non-answer)? |

The scorecard returns per-scenario pass/fail with the specific issues found, plus aggregate rates for team vs. baseline. Two things are worth separating honestly:

- **Structural guarantees (hold every time, by construction):** the team **cannot invent stock** — its only data path is a read-only catalog read — and it **cannot quote below the 45% margin** — every price comes from the deterministic engine. These aren't measured; they're properties of the architecture.
- **The measured rates (vary run to run):** `grounded_rate`, `margin_safe_rate`, and `hallucination_rate` are a *measurement*, and because live retrieval is non-deterministic the numbers move — in testing we've observed the team's grounded rate roughly in the **80–100%** range, well above the no-grounding baseline, but it is **not** a fixed 100%. The point isn't a perfect score; it's that honesty is a number you can **re-run and watch**, against a scorer ([`eval/scoring.py`](src/asili_agents/eval/scoring.py)) that is a deterministic heuristic, not a general-purpose lie detector.

> **Honest scope.** The scorecard's checks are deterministic Python heuristics, hardened against common paraphrases (comma-formatted numbers, `%`/word/fraction discounts, "$X off", spelled-out and compound numbers, contrastive clauses) — not a general-purpose lie detector. The *structural* guarantees are the two it measures against: the deterministic margin engine (the LLM cannot author a price) and read-only MCP grounding (the agent cannot invent or mutate inventory).

---

## MongoDB usage

MongoDB Atlas is the **system of record**. The agents never hold a private copy of the truth.

**Collections (Atlas):**

| Collection | Holds | Status |
| --- | --- | --- |
| `products` | The live catalog — SKU, name, description, `price`, `cost`, `stock_quantity`, thresholds. The one source of inventory truth. | **Live** — read via the MCP server (`--readOnly`) |
| `policy` | The seller's commercial rules — `margin_floor` (0.45), bundle discount limits, shipping and returns notes. | **Live** — read via MCP |
| `conversations` | Customer threads and their messages, with direction, status, and timestamps. | **Persisted** (`MongoStore`) |
| `drafts` | Pending agent replies awaiting the approval gate, with their cited sources. | **Persisted** (`MongoStore`) |
| `decisions` | The glass-box trace — every routing, grounding, and composition step the agents logged. | In-process today; persistence is the remaining increment |
| `eval_runs` | Trust Scorecard results — the schema for auditing honesty over time. | In-process today; persistence is the remaining increment |

**Two clearly separated access paths:**

- **Agent reads → MongoDB MCP server, `--readOnly`.** Everything an agent learns about the catalog comes through MCP, and MCP cannot write. This is the grounding guarantee.
- **App writes → audited application path.** Persisting a conversation or a draft goes through the application's own write path (`data/store.py`) — never through the agent's tools — so the inbox and the approval queue survive restarts and span Cloud Run instances. (The decision trace and eval-run history are in-process today; persisting them the same way is the remaining increment.) Writes are deliberate, attributable, and kept out of the model's reach.

This split is the whole point: the model can *see* the truth but can't *change* it, and every change that does happen is made by code we can audit.

---

## Tech stack

- **Agents:** Google ADK (Agent Development Kit) — multi-agent orchestration with sub-agents and function tools.
- **Model:** Gemini 2.5 Flash, served on **Vertex AI** (also runnable via a direct Gemini API key for local dev).
- **Grounding:** MongoDB **MCP server** (`mongodb-mcp-server`, read-only) over **MongoDB Atlas**.
- **Pricing:** Deterministic Python (`Decimal` arithmetic, 45% margin floor).
- **API:** FastAPI (JSON, same-origin base path).
- **Runtime:** Cloud Run (containerized, see `Dockerfile`).
- **Language/tooling:** Python 3.11+, Pydantic v2, `ruff`, `mypy`, `pytest`.

---

## Architecture diagram

A full request walkthrough — message in, MCP grounding, deterministic pricing, decision logging, approval, send — and the collection-level data flow live in **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**.

---

## Quickstart (local)

**Prerequisites:** Python 3.11+, Node.js (for `npx mongodb-mcp-server`), a MongoDB Atlas connection string, and either a Gemini API key or Vertex AI credentials.

```bash
# 1. Install
git clone https://github.com/Jeremiah-Sakuda/asili-agents.git
cd asili-agents
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Set at minimum:
#   GOOGLE_API_KEY=...        # or Vertex AI service-account credentials
#   MONGODB_URI=...           # your MongoDB Atlas connection string

# 3. Run the API + agents
asili-agents serve            # FastAPI on http://localhost:8080

# Or run the scripted demo scenario
asili-agents demo
```

Then exercise the system:

```bash
# Inspect the grounded catalog
curl localhost:8080/api/products

# Run the team on the demo conversation
curl -X POST localhost:8080/api/run \
  -H 'content-type: application/json' \
  -d '{"conversation_id":"<id>","message":"Do you have the purple tea in stock? Can you do a bundle?"}'

# Run the Trust Scorecard (team vs. baseline)
curl -X POST localhost:8080/api/eval
```

Run the tests with `pytest`.

---

## Project structure

```
asili-agents/
├── src/asili_agents/
│   ├── agents/         # ADK agents: operations_manager, messaging, pricing, content, baseline, mcp_tools
│   ├── tools/          # catalog (grounding), pricing (deterministic Decimal), logging, channel (approval gate)
│   ├── data/           # pydantic models, CatalogRepository (static + MongoDB), seed data + tenants
│   ├── eval/           # Trust Scorecard: scoring (deterministic), scenarios, runner
│   ├── api/            # FastAPI app (REST endpoints + serves the web UI)
│   ├── web/            # phone-inbox SPA (vanilla JS, served at /app/)
│   ├── runner.py       # ADK InMemoryRunner integration (team + baseline)
│   ├── config.py       # pydantic-settings configuration
│   ├── cli.py          # `asili-agents serve|demo`
│   └── demo.py         # scripted demo scenario
├── tests/              # pytest suite (pricing, eval, agents, api, repository, runner)
├── scripts/            # seed_atlas.py, deploy.sh, setup-gcp.sh
├── docs/               # ARCHITECTURE, API, DEVELOPMENT, TRUST_SCORECARD
├── Dockerfile          # Python + Node (for the MongoDB MCP server) → Cloud Run
└── pyproject.toml
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for a module-by-module guide and the full configuration reference.

---

## Data sources

- **Canonical demo seller — Mahaba Tea Co.** A Kenyan specialty-tea importer on the **KE → US** lane, with a real-feeling six-SKU catalog (Purple Tea, Kenyan Green, Kenya Black, Silver Needle White, Chai Masala, and a Discovery Sampler), deliberate low-stock items, honest costs, and a 45% margin-floor policy. Seed data lives in `src/asili_agents/data/`.
- **Live state in the deployed configuration** is read from **MongoDB Atlas** via the MCP server — the seed simply populates Atlas; once running, the catalog the agents see is whatever is in the database. Locally (and in tests) the same catalog contract is served from the in-process seed, so the system runs without Atlas.

The demo question — *"Do you have the purple tea in stock? Can you do a bundle?"* — is the whole thesis in one exchange:

| | Stock answer | Bundle quote | Margin |
| --- | --- | --- | --- |
| **The team** | "In stock — 6 tins left" (read from catalog) | ~$34 for 2 tins | ~57% ✅ floor held |
| **Fair baseline** (catalog in prompt, no live grounding / pricing tool) | "32 tins!" (misremembered) | "30% off, $25.20" | below floor ❌ |

---

## Honesty note

This README makes no claims the code doesn't back:

- **The deterministic margin engine, the ADK multi-agent topology, the approval gate, the fair single-agent baseline, and the Trust Scorecard are implemented in this repository**, not mocked for a screenshot. The pricing math is plain Python you can read in `src/asili_agents/tools/pricing.py`, and the scorecard's metrics are computed from actual agent runs.
- **Grounding is MongoDB.** In the deployed configuration the agent's catalog knowledge comes through the MongoDB MCP server against Atlas (with an in-process fallback for local dev/tests). **This project does not use Vertex AI Search or a RAG retrieval pipeline** — that approach was considered and removed, and no part of this submission depends on it.
- **The numbers in this document are reproducible.** The ~$34 / ~57% bundle is what the deterministic engine actually returns for two tins of Purple Tea; the baseline's slips are what a fair, catalog-in-prompt single agent actually produces without live grounding or a pricing tool. Run `POST /api/eval` and check for yourself — that re-runnability is the point.

If a claim here isn't true in the code, that's a bug, and we'd rather fix it than ship it. An ops team that can't prove its honesty has no business making promises on a founder's behalf.

---

## Business model

The **seller is the customer.** Asili is a per-seller SaaS back-office: **$99/mo Operator** — all DM channels, unlimited approved replies, grounded answers, margin-safe bundle pricing, the Trust Scorecard, and the autonomy ladder, with the first 30 days free — and **$199/mo Studio** (multiple catalogs/brands, team approval seats, exportable audit history).

The value is VA-anchored: Asili runs the back-office a solo founder can't afford to hire out, for **a fraction of a part-time virtual assistant.** A thin-margin importer doing ~$5k/mo GMV also bleeds an estimated **~$70–90/mo** to phantom-inventory refunds and below-margin discounts — losses Asili prevents *structurally* (read-only grounding can't invent stock; the deterministic engine can't quote below the 45% floor) — so the avoided losses alone nearly cover the plan, with the hours returned to the founder on top. Reached through diaspora community networks (low-CAC, referral-led), a focused 5,000-seller Operator beachhead is **~$5.9M ARR**.

→ Full pricing, bottom-up TAM/SAM, per-seller unit economics, and the (honest) validation plan: **[docs/BUSINESS.md](docs/BUSINESS.md)**. *These are a founder-built hypothesis, not traction — labeled as such on purpose.*

---

## Roadmap / out of scope

The build deliberately focuses on the seller-facing operations agents and the deterministic trust core. **Shipped:** the web console, a live **Telegram** customer-DM channel behind the approval gate (see [docs/TELEGRAM.md](docs/TELEGRAM.md)), and durable persistence of conversations + pending drafts to Atlas. Intentionally **not** built yet:

- **Instagram / WhatsApp DMs.** Telegram is live; extending to the other DM channels where many sellers also operate is gated on Meta Business approval and is the next major reach step.
- **Full Atlas audit history.** Conversations and pending drafts already persist to Atlas; persisting the **decision log + eval-run history** over time (longitudinal audit) is the remaining write-path increment.
- **Richer pricing** (shipping, FX on the KE→US lane, tiered promos) beyond the single 45% margin floor + flat bundle discount.

---

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, the runtime diagram, and honest implementation status
- [docs/API.md](docs/API.md) — complete REST API reference
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — setup, project structure, configuration (env vars), and tooling
- [docs/TRUST_SCORECARD.md](docs/TRUST_SCORECARD.md) — how the deterministic scorer works and its honest limits
- [docs/BUSINESS.md](docs/BUSINESS.md) — business model, pricing, bottom-up market sizing, per-seller ROI, and the validation plan
- [docs/TELEGRAM.md](docs/TELEGRAM.md) — the Telegram customer-DM channel (webhook → approval gate → delivery)
- [BY_HAND.md](BY_HAND.md) — founder's submission checklist (demo video, Devpost form, secret rotation); the code prerequisites are done and verified live

---

## License

[MIT](LICENSE) © Jeremiah Sakuda
