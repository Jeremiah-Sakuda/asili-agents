# Asili Agents — Developer Guide

A developer-facing guide to building, running, testing, configuring, and deploying **asili-agents**: a Python 3.11+ Google ADK multi-agent "AI operations team" for underrepresented micro-sellers.

> **What this system is, in one breath:** an Operations Manager (root `Agent`) routes a customer message to two specialist sub-agents — **Messaging** (catalog grounding) and **Pricing** (deterministic margin-safe bundle prices) — plus a tool-less single-agent **baseline** for comparison. Data flows through a `CatalogRepository` seam: `StaticCatalogRepository` for local dev/tests, `MongoCatalogRepository` for Atlas. A deterministic `Decimal` engine computes bundle prices, and a deterministic **Trust Scorecard** scores team-vs-baseline replies. A FastAPI backend serves a vanilla-JS web UI at `/app/`.

---

## 1. Prerequisites

| Requirement | Why | Notes |
| --- | --- | --- |
| **Python 3.11+** | Project targets `requires-python = ">=3.11"`; CI runs 3.11 and 3.12. | `pyproject.toml` declares 3.11/3.12 classifiers. |
| **Node.js (`npx`)** | Only needed for the **MongoDB MCP grounding path** — the Messaging/Pricing agents spawn `npx mongodb-mcp-server`. | Not required for local dev/tests on the in-process seed. The production `Dockerfile` bundles Node 20 for this reason. |
| **MongoDB Atlas (optional)** | The *deployed* system of record + grounding source. Set `MONGODB_URI` to enable. | Without it, the app runs on the in-process seed (Mahaba Tea Co.). |
| **Gemini / Vertex AI credentials (optional, but required to actually run agents)** | The agents make real LLM calls. Provide **either** `GOOGLE_API_KEY` (AI Studio key) **or** `GOOGLE_APPLICATION_CREDENTIALS` (GCP service account for Vertex AI). | Pure unit tests don't need credentials; running `demo`/`/api/run`/`/api/eval` does. |

**Runtime status, stated honestly:**

- The in-process seed (`data/seed.py`, *Mahaba Tea Co.*) is the **local/test default**.
- MongoDB Atlas + the MongoDB MCP server is the **deployed grounding path**, enabled only when **`USE_MCP=true` AND `MONGODB_URI` is set AND `DEMO_MODE` is false**.
- If `USE_MCP` is set but there is **no** `MONGODB_URI`, `make_mongodb_mcp_toolset()` returns `None` and the agents **fall back to the in-process catalog tools**.
- **Conversations and pending drafts are persisted back to Atlas** (`data/store.py` `MongoStore`) when Atlas is connected; an in-memory store is the local/test fallback. Still in-process: the agent **decision log** (`tools/logging.py`, a per-run `ContextVar`-isolated list) and the `eval_runs` history — persisting those back to Atlas is the remaining increment.

---

## 2. Setup

```bash
# From the repo root: /path/to/asili-agents
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Editable install with dev tools (pytest, ruff, mypy, pre-commit)
pip install --upgrade pip
pip install -e ".[dev]"

# Configure environment (all values are optional for the in-process demo)
cp .env.example .env
# edit .env: set GOOGLE_API_KEY (or GOOGLE_APPLICATION_CREDENTIALS) to run agents
```

`config.py` loads settings from a `.env` file in the working directory (`SettingsConfigDict(env_file=".env", case_sensitive=False)`), so env vars are case-insensitive and `.env` is read automatically.

The install exposes a console entry point (`[project.scripts]` in `pyproject.toml`):

```toml
asili-agents = "asili_agents.cli:main"
```

---

## 3. Running locally

The CLI (`src/asili_agents/cli.py`) has two subcommands: `demo` and `serve`.

### Scripted/real demo run

```bash
asili-agents demo
# equivalent to: python -m asili_agents.demo
```

Runs `demo.run_demo_scenario()`: loads the Mahaba Tea Co. seed, executes the **real** Operations Manager multi-agent run on the demo customer message (*"Do you have the purple tea in stock? Can you do a bundle?"*), prints the agent workflow trace, grounded business facts, the draft reply, and a **real** baseline run for contrast. Requires Gemini/Vertex credentials because it issues live LLM calls.

### API server + web UI

```bash
asili-agents serve                       # binds 0.0.0.0:8080
asili-agents serve --port 8000 --reload  # dev: custom port + auto-reload
```

`serve` runs `uvicorn asili_agents.api.main:app`. Once up:

- **Web UI (phone-inbox demo):** `http://localhost:8080/app/` — vanilla JS/HTML/CSS served as same-origin static files from `src/asili_agents/web/` (mounted at `/app` with `html=True`).
- **Health + data-source visibility:** `GET /` returns `{service, version, status, data_source, mcp_grounding, products_loaded}`. `data_source` is `"demo"` or `"atlas"` — use it to confirm whether you're actually grounded on Atlas.

**By default, the server runs on the in-process seed** (because `.env.example` ships `DEMO_MODE=true` and no `MONGODB_URI`). The lifespan handler logs which path it chose and falls back to the demo seed if Atlas is configured but unreachable (it logs loudly rather than silently serving demo data on the graded path).

### Key API endpoints (`api/main.py`)

| Method + path | Purpose |
| --- | --- |
| `GET /` | Health check + data-source/MCP visibility. |
| `GET /api/seller` | Current seller (id, name, lane, brand voice). |
| `GET /api/products` | Full catalog (price, cost, margin %, stock, level, unit). |
| `GET /api/policy` | Margin floor, bundle discount, shipping/returns notes. |
| `GET /api/facts` | Grounded "business state" facts for the UI (Purple Tea focus). |
| `POST /api/conversations` / `GET /api/conversations/{id}` | Create / fetch a demo conversation. |
| `POST /api/run` | **Run the multi-agent team** on a message; returns steps, draft, facts. |
| `POST /api/run/baseline` | Run the tool-less baseline for comparison. |
| `POST /api/approve` | Human-in-the-loop: `approve` / `edit` / `reject` a pending draft. |
| `GET /api/pending/{id}` | Fetch a conversation's pending draft. |
| `GET /api/decisions` | The in-process agent decision log. |
| `POST /api/reset` | Reset demo state (clears log, conversations, drafts). |
| `POST /api/eval?limit=6` | **Trust Scorecard**: team vs baseline across adversarial scenarios. |

> The per-run decision log is isolated with a `ContextVar` (each request is its own asyncio task with its own context), so concurrent `/api/run` and `/api/eval` calls don't interleave their steps **without** a process-wide lock. The catalog/pricing repository and the approval callback are still **module-global** (`set_catalog_repository` / `set_pricing_context` / the approval callback), so the running app is effectively single-tenant per process — a deliberate demo-scale simplification, not a multi-tenant isolation guarantee. The server drives the agents with the **async** runners (`run_agent_async` / `run_baseline_async`, and `run_scorecard_async`) directly on the request's event loop — required so the MongoDB MCP server's stdio session shares that loop. The synchronous `run_agent` / `run_baseline` remain for local dev and tests.

---

## 4. Project structure

```
asili-agents/
├── pyproject.toml              # Build (hatchling), deps, ruff/mypy/pytest/coverage config, CLI entry point
├── Dockerfile                  # Python 3.11 + Node 20 image (Node = MongoDB MCP via npx); runs uvicorn
├── .env.example                # Template for all environment variables
├── .dockerignore / .gitignore
├── README.md / LICENSE / BY_HAND.md
├── .github/workflows/
│   ├── ci.yml                  # lint (ruff) → test (pytest 3.11/3.12 + coverage) → build
│   └── deploy.yml              # push to main / manual dispatch → Cloud Run deploy (Vertex AI)
├── docs/
│   ├── ARCHITECTURE.md         # System architecture write-up
│   └── DEVELOPMENT.md          # (this guide)
├── scripts/
│   ├── deploy.sh               # Build + push image, deploy to Cloud Run (toggles MCP if secret present)
│   ├── setup-gcp.sh            # One-time GCP project/APIs/Artifact Registry/CI service-account setup
│   └── seed_atlas.py           # Seed Atlas products/policy/sellers collections from the seed data
├── src/asili_agents/
│   ├── __init__.py             # Package version (0.1.0)
│   ├── config.py               # Pydantic-settings `Settings` + cached `get_settings()`
│   ├── cli.py                  # argparse CLI: `demo` and `serve` subcommands
│   ├── demo.py                 # Scripted-but-real demo: team run vs baseline run, formatted to stdout
│   ├── runner.py               # ADK `InMemoryRunner`; `create_runner`, `run_agent`(+`run_agent_async`), baseline equivalents; `RunResult`/`AgentStep`
│   ├── agents/
│   │   ├── __init__.py         # Re-exports the four create_* factories
│   │   ├── operations_manager.py  # Root orchestrator `Agent` with Messaging+Pricing sub-agents
│   │   ├── messaging.py        # Messaging `LlmAgent` (catalog_search/check_stock or MCP)
│   │   ├── pricing.py          # Pricing `LlmAgent` (get_costs + deterministic compute_bundle_price)
│   │   ├── baseline.py         # Tool-less single `LlmAgent` baseline (catalog dump in prompt)
│   │   └── mcp_tools.py        # MongoDB MCP toolset wiring (`make_mongodb_mcp_toolset`, `resolve_use_mcp`)
│   ├── tools/
│   │   ├── __init__.py         # Re-exports the ADK FunctionTools
│   │   ├── catalog.py          # catalog_search / check_stock / get_costs (read via CatalogRepository)
│   │   ├── pricing.py          # compute_bundle_price (DETERMINISTIC Decimal margin engine)
│   │   ├── channel.py          # send_for_approval / channel_send (human-in-the-loop gate)
│   │   └── logging.py          # log_decision + in-process decision log
│   ├── data/
│   │   ├── __init__.py         # Re-exports models + seed helpers
│   │   ├── models.py           # Pydantic models: Seller, Product, Policy, Message, Conversation, AgentDecision + enums
│   │   ├── repository.py       # `CatalogRepository` Protocol + `StaticCatalogRepository` + module-global setter/getter
│   │   ├── mongo_repository.py # `MongoCatalogRepository` (Atlas read path; Decimal-as-string)
│   │   ├── seed.py             # Mahaba Tea Co. seed (seller, 6 products, policy, demo conversation)
│   │   └── seed_tenants.py     # Two extra demo tenants (Mama Ngozi Foods, Ti Piment) + get_all_sellers
│   ├── eval/
│   │   ├── __init__.py
│   │   ├── scenarios.py        # Adversarial customer scenarios (stock / discount / control)
│   │   ├── scoring.py          # Deterministic claim extraction + ReplyScore + aggregate (Trust Scorecard core)
│   │   └── runner.py           # score_system / run_scorecard / build_live_reply_fns (wires ADK runners)
│   ├── api/
│   │   ├── __init__.py
│   │   └── main.py             # FastAPI app, lifespan (data-source selection), all endpoints, static mount
│   └── web/
│       ├── index.html          # Phone-inbox demo UI shell
│       ├── app.js              # Vanilla-JS client (calls /api/*)
│       └── styles.css          # UI styles
└── tests/
    ├── conftest.py             # Fixtures (demo seller/products/policy) + autouse tool-store setup/teardown
    ├── test_models.py          # Pydantic model + computed-field tests
    ├── test_tools_catalog.py   # catalog_search / check_stock / get_costs
    ├── test_tools_pricing.py   # compute_bundle_price margin-safety + edge cases
    ├── test_tools_logging.py   # decision log
    ├── test_agents.py          # Agent factory construction
    ├── test_mcp_tools.py       # MCP toolset wiring / resolve_use_mcp
    ├── test_mongo_repository.py# Mongo doc↔model mapping
    ├── test_runner.py          # Runner wiring
    ├── test_eval.py            # Scoring + scorecard logic (largest test file)
    └── test_api.py             # FastAPI endpoint tests
```

### Agent topology at a glance

```
                 customer message
                        │
                        ▼
        ┌──────────────────────────────┐
        │     Operations Manager       │  root Agent
        │  tools: log_decision,        │
        │         send_for_approval    │
        └───────────┬──────────────────┘
            sub_agents│
        ┌─────────────┴──────────────┐
        ▼                            ▼
┌────────────────┐          ┌──────────────────┐
│ Messaging Agent│          │  Pricing Agent   │
│ catalog_search │          │ get_costs +      │
│ check_stock    │          │ compute_bundle_  │
│ (or MongoDB MCP│          │ price (always    │
│  find/aggregate│          │ DETERMINISTIC)   │
│  /count …)     │          │ (or MongoDB MCP  │
└────────────────┘          │  for cost lookup)│
                            └──────────────────┘

   Baseline (control): single LlmAgent, NO tools,
   full catalog snapshot pasted into the prompt.
```

---

## 5. Configuration / environment variables

All settings come from `src/asili_agents/config.py` (`Settings(BaseSettings)`), loaded from environment / `.env`. Field names are lowercase; the corresponding env var is the uppercase name (case-insensitive).

| Setting (field) | Env var | Default | Meaning |
| --- | --- | --- | --- |
| `google_cloud_project` | `GOOGLE_CLOUD_PROJECT` | `asili-agents-hackathon` | GCP project ID (used by Vertex AI). |
| `google_cloud_location` | `GOOGLE_CLOUD_LOCATION` | `us-central1` | GCP region. |
| `google_api_key` | `GOOGLE_API_KEY` | `None` | Gemini (AI Studio) API key — simplest path for local dev. `runner._configure_api_credentials()` exports it to the env if set. |
| `google_application_credentials` | `GOOGLE_APPLICATION_CREDENTIALS` | `None` | Path to a GCP service-account JSON for Vertex AI auth (alternative to the API key). |
| `gemini_model` | `GEMINI_MODEL` | `gemini-2.5-flash` | Model used by every agent (`Agent.model` / `LlmAgent.model`). |
| `mongodb_uri` | `MONGODB_URI` | `None` | Atlas SRV connection string. **Required for MCP grounding** and for `MongoCatalogRepository`. |
| `mongodb_database` | `MONGODB_DATABASE` | `asili` | Atlas database name. |
| `use_mcp` | `USE_MCP` | `False` | Route the specialists' catalog/stock reads through the MongoDB MCP server. When `False`, agents use the in-process repository (dev + tests). |
| `mcp_read_only` | `MCP_READ_ONLY` | `True` | Launch the MCP server with `--readOnly` (and `MDB_MCP_READ_ONLY=true`) so agents can never mutate the catalog through tools. |
| `mcp_server_command` | `MCP_SERVER_COMMAND` | `npx` | Command used to launch the MongoDB MCP server (args: `-y mongodb-mcp-server [--readOnly]`). |
| `api_host` | `API_HOST` | `0.0.0.0` | API bind host. |
| `api_port` | `API_PORT` | `8080` | API bind port. |
| `log_level` | `LOG_LEVEL` | `INFO` | One of `DEBUG`/`INFO`/`WARNING`/`ERROR` (validated by a `Literal`). |
| `demo_mode` | `DEMO_MODE` | `True` | When `True`, the API uses the in-process seed even if `MONGODB_URI` is set. Atlas is used only when `demo_mode` is `False` **and** `mongodb_uri` is set. |
| `default_margin_floor` | `DEFAULT_MARGIN_FLOOR` | `0.45` | Default minimum margin floor (45%). (The active floor for pricing comes from the seller `Policy.margin_floor`; this is the configured fallback.) |

**Set at deploy time (not a `Settings` field):**

| Env var | Value | Meaning |
| --- | --- | --- |
| `GOOGLE_GENAI_USE_VERTEXAI` | `true` | Tells the Google GenAI/ADK stack to use **Vertex AI** (with the project's ADC) rather than an API key. Set in `scripts/deploy.sh` and `.github/workflows/deploy.yml`. |
| `MDB_MCP_CONNECTION_STRING` | `${MONGODB_URI}` | Passed into the MCP server subprocess env so the secret stays out of the arg list (set in `mcp_tools.make_mongodb_mcp_toolset`). |
| `MDB_MCP_READ_ONLY` | `true`/`false` | Mirrors `mcp_read_only` into the MCP server subprocess env. |

> **Decision matrix** for the API's data source (from `api/main.py` lifespan): Atlas is used **only** when `mongodb_uri` is set **and** `demo_mode` is `False` **and** the connection succeeds **and** the `products` collection is non-empty. Otherwise it serves the in-process seed (logging the reason). MCP grounding for agents is enabled only on the Atlas path, gated by `use_mcp`.

---

## 6. Tooling: lint, type-check, test

All tool config lives in `pyproject.toml`.

### Ruff (lint + format)

```bash
ruff check src/ tests/           # lint
ruff check --fix src/ tests/     # autofix
ruff format src/ tests/          # format
ruff format --check src/ tests/  # CI: verify formatting without writing
```

- `target-version = "py311"`, `line-length = 100`.
- Lint rule sets: `E`, `W`, `F`, `I` (isort), `B` (bugbear), `C4` (comprehensions), `UP` (pyupgrade).
- Ignored: `E501` (line length → formatter handles it), `B008`, `UP042`.
- isort treats `asili_agents` as first-party.

### mypy (type-check)

```bash
mypy src/
```

- `python_version = "3.11"`, `warn_return_any`, `warn_unused_ignores`, `disallow_untyped_defs = true`.
- Uses the `pydantic.mypy` plugin; `prop-decorator` error code is disabled (Pydantic `@computed_field` over `@property` is idiomatic and otherwise false-flagged).

> Note: mypy is installed via the `dev` extra and configured, but the **CI workflow runs ruff (check + format) and pytest, not mypy** — run mypy locally as part of your pre-push routine.

### pytest

```bash
pytest                              # uses pyproject addopts: -v + coverage on src/asili_agents
pytest tests/test_tools_pricing.py # one file
pytest -k bundle                    # by keyword
```

- `asyncio_mode = "auto"` (async tests need no explicit marker; `pytest-asyncio` is in dev deps).
- `testpaths = ["tests"]`; default `addopts = "-v --cov=src/asili_agents --cov-report=term-missing"`.
- Coverage: branch coverage on `src/asili_agents`, with `exclude_lines` for `__repr__`, `NotImplementedError`, `TYPE_CHECKING`, and `pragma: no cover`.
- `conftest.py` provides `demo_seller`/`demo_products`/`demo_policy`/`purple_tea` fixtures and an **autouse** `setup_tools` fixture that initializes the static product store + pricing context and clears the decision log before/after each test — so tests are deterministic and don't touch the network or an LLM.

### Pre-commit

`pre-commit` is listed in the `dev` extra. (No `.pre-commit-config.yaml` is currently checked in, so `pre-commit install` will have nothing to hook until one is added.)

### How CI runs them (`.github/workflows/ci.yml`)

Triggered on push/PR to `main`/`master`:

1. **lint** — `ruff check src/ tests/` then `ruff format --check src/ tests/`.
2. **test** — matrix over Python **3.11 and 3.12**: `pip install -e ".[dev]"` then `pytest --cov=src/asili_agents --cov-report=xml --cov-report=term-missing`; uploads coverage to Codecov (non-blocking).
3. **build** — needs lint+test; `python -m build`, uploads the `dist/` artifact.

---

## 7. How the data layer swaps in-process vs Atlas/MCP

There are **two independent data paths**, both pointing at the same logical catalog so customer-facing answers can't drift from the database:

1. **Application read path** — `CatalogRepository` (`data/repository.py`). A `runtime_checkable` `Protocol` with two implementations:
   - `StaticCatalogRepository(products, policy)` — in-memory, builds an index by id/SKU/name; used by tests, local dev, and demo mode.
   - `MongoCatalogRepository(uri, database)` — reads Atlas `products`/`policy` collections (money fields stored as strings, converted back to `Decimal` on read).
   - A module-global active repository is set via `set_catalog_repository(repo)` and read via `get_catalog_repository()` (returns an empty static repo if unset, so tool calls degrade to "not found" rather than raising). The catalog/pricing **tools** (`catalog_search`, `check_stock`, `get_costs`, `compute_bundle_price`) always read through this active repository.

2. **Agent grounding path** — MongoDB MCP (`agents/mcp_tools.py`). When `resolve_use_mcp(...)` is `True` and `mongodb_uri` is set, `make_mongodb_mcp_toolset()` returns an ADK `McpToolset` that launches `npx -y mongodb-mcp-server [--readOnly]`, filtered to read-only tools (`find`, `aggregate`, `count`, `list-collections`, `collection-schema`). The Messaging and Pricing agents then read the catalog/cost data through MongoDB instead of the in-process catalog tools, and an MCP grounding instruction is appended to their prompt. If `mongodb_uri` is unset, the toolset is `None` and the agents fall back to the in-process tools.

**Important invariant:** even on the MCP path, `compute_bundle_price` stays **deterministic** — only the *cost lookup* moves to MCP. The LLM never invents a price.

### Compatibility setters

`tools/catalog.set_product_store(products)` and `tools/pricing.set_pricing_context(products, policy)` are convenience wrappers that build a `StaticCatalogRepository` and register it. They exist for tests, local dev, and API startup, and ensure the catalog tools and the pricing tool share one source of truth.

### Switching to Atlas locally

```bash
# 1) Set credentials in .env
MONGODB_URI=mongodb+srv://USER:PASS@cluster.example.mongodb.net/
MONGODB_DATABASE=asili
DEMO_MODE=false
USE_MCP=true            # also requires Node/npx for the MCP server

# 2) Seed Atlas with the demo catalog/policy/seller
export MONGODB_URI="mongodb+srv://USER:PASS@cluster.example.mongodb.net/"
python scripts/seed_atlas.py          # Mahaba Tea Co. only
python scripts/seed_atlas.py --all    # + Mama Ngozi Foods + Ti Piment

# 3) Run and verify the data source
asili-agents serve
curl localhost:8080/        # expect "data_source":"atlas","mcp_grounding":true
```

`seed_atlas.py` upserts `sellers`, `products` (keyed by SKU), and `policy` (keyed by `seller_id`), storing `price`/`cost`/`free_shipping_threshold` as strings to preserve exact precision.

---

## 8. The deterministic pieces (worth knowing before you change them)

- **`compute_bundle_price` (`tools/pricing.py`)** computes prices with `Decimal`:
  - `bundle_price = max(list_price * (1 - bundle_discount), cost / (1 - margin_floor))`.
  - Rounds **up** to the cent (`ROUND_CEILING`) so rounding can never drop below the floor, then a bounded belt-and-suspenders loop (`MAX_MARGIN_LOOP_ITERATIONS = 100_000`) guarantees the realized margin clears the floor.
  - Rejects margin floors `< 0.0` or `>= 0.99` (`MAX_MARGIN_FLOOR`), non-numeric floors, bad product IDs, non-positive quantities, and "surcharge" bundles where even list price can't meet the floor — all returning a structured `{"error": ..., "is_margin_safe": False}` rather than raising.
- **Trust Scorecard (`eval/`)** is a **deterministic heuristic**, not a general-purpose lie detector. `scoring.py` extracts stock/discount claims via regex (handling thousands separators, word-numbers like "forty-five", word fractions like "half off", and "$X off"), neutralizes claims inside limiting/refusal clauses (split on punctuation *and* contrastive conjunctions so a stock caveat can't launder an unsafe discount), and produces a `ReplyScore` (`no_overclaim`, `answered`, `grounded`, `retrieved`, `hallucinated_stock`, `margin_unsafe`). `runner.score_system` is pure (takes a `reply_fn`) so it's unit-testable without an LLM; `build_live_reply_fns` wires the real ADK runners for `/api/eval`. The structural guarantees that matter are the **deterministic margin engine** and **read-only MCP grounding** — not the scorer.

---

## 9. Deploy pointer (Cloud Run)

The production image (`Dockerfile`) is **Python 3.11-slim + Node 20** (Node is copied in so the agents can spawn `npx mongodb-mcp-server` in-container; the MCP server is pre-cached at build time), runs as a non-root `appuser`, exposes `8080`, has a `HEALTHCHECK`, and starts `uvicorn asili_agents.api.main:app`.

### One-time GCP setup

```bash
./scripts/setup-gcp.sh [PROJECT_ID]
# Creates the project, enables run/aiplatform/artifactregistry/cloudbuild/discoveryengine,
# creates a github-actions service account with run.admin + artifactregistry.writer +
# iam.serviceAccountUser, and an Artifact Registry repo. Prints the GitHub secrets to set
# (GCP_PROJECT_ID, WIF_PROVIDER, WIF_SERVICE_ACCOUNT for Workload Identity Federation).
```

### Manual deploy

```bash
./scripts/deploy.sh
# Builds + pushes the image to Artifact Registry, then `gcloud run deploy`.
# Sets GOOGLE_GENAI_USE_VERTEXAI=true (Vertex AI auth via the Cloud Run service account).
# Attaches MONGODB_URI from the Secret Manager secret `asili-mongodb-uri` and deploys with
# USE_MCP=true, MCP_READ_ONLY=true, DEMO_MODE=false (live Atlas + MCP grounding).
# Cloud Run: 2Gi / 2 CPU, 600s timeout, startup CPU boost, min-instances 1, max-instances 5,
#   unauthenticated. The MCP server spawns a Node subprocess, so the service needs headroom
#   and one warm instance to keep responses snappy.
```

### CI/CD deploy

`.github/workflows/deploy.yml` deploys to Cloud Run on push to `main` (or manual `workflow_dispatch`), authenticating via Workload Identity Federation and setting the same Vertex AI / MCP environment. (Per project memory, asili-agents reuses the XPRIZE GCP project and a shared WIF provider.)

> **Atlas networking reminder:** for Cloud Run to reach Atlas, set the cluster's Network Access to allow `0.0.0.0/0` (or the appropriate egress IPs), confirm the `MONGODB_URI` secret, and run `scripts/seed_atlas.py`. If the connection fails at boot, the lifespan handler logs the failure loudly and falls back to the demo seed (so `GET /` will report `data_source: "demo"`).

---

## Quick reference

```bash
# Setup
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Develop
ruff check src/ tests/ && ruff format src/ tests/
mypy src/
pytest

# Run
asili-agents demo                 # real team-vs-baseline demo (needs LLM creds)
asili-agents serve --reload       # API + web UI at http://localhost:8080/app/

# Atlas / MCP
python scripts/seed_atlas.py
curl localhost:8080/              # check data_source / mcp_grounding

# Deploy
./scripts/setup-gcp.sh            # one-time
./scripts/deploy.sh               # build + push + Cloud Run
```
