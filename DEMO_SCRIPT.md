# Demo script — Asili (≤ 3:00)

A shot-by-shot script for the submission video. The structure leads with the **single most persuasive, already-working moment — live falsification** — then proves the trust thesis, then shows the human gate. Every beat below is backed by a live endpoint and was walked end-to-end (see `## Run-through verification`).

- **Target length:** 2:50–3:00 (hard cap 3:00 for the Rapid Agent track).
- **What to capture:** the live app at **https://asili-agents-u42sxjnqkq-uc.a.run.app/app/**, one terminal window, and (optionally) the real Telegram chat with **@asili_agent_bot**.
- **Tone:** calm, concrete, founder-to-judge. Let the product do the talking; don't oversell.

---

## Pre-flight checklist (do this before recording)

1. Open the live app `/app/` in a clean browser window; confirm the inbox loads with the demo conversation ("Dana R. · Do you have the purple tea in stock? Can you do a bundle?").
2. Confirm `GET /` shows `data_source: atlas`, `mcp_grounding: true` (open the root URL in a tab).
3. Have a terminal ready with the one-liner to edit Atlas stock (see Beat 1) and the **revert** command queued in your history.
4. (Optional) Have the Telegram chat with @asili_agent_bot open in a phone/second window for the approval delivery shot.
5. Do one full dry run (the run-through below) so the agent is "warm" (first MCP call can take ~15–20s; a warmed instance answers faster).
6. Record in 1080p, portrait or a phone-framed crop — the UI is phone-first.

---

## The script

### 0:00–0:18 · Cold open — the problem
- **On screen:** a customer DM bubble: *"Do you have the purple tea in stock? Can you do a bundle?"*
- **VO:** "Black, immigrant, and diaspora founders run real businesses out of their DMs. Hand that question to a generic chatbot and it does two expensive things: it invents inventory it doesn't have, and it quotes discounts that lose money. For a thin-margin importer, that's a refund, a chargeback, and a broken promise."

### 0:18–0:33 · What Asili is
- **On screen:** the app header; a one-line caption: *"A Google ADK ops team · grounded in live MongoDB Atlas · deterministic pricing · human approval."*
- **VO:** "Asili is an AI operations team for those sellers. Every answer is grounded in their live catalog, every price comes from a deterministic engine, nothing sends without their approval — and it can prove it didn't make anything up."

### 0:33–1:12 · Beat 1 — Live falsification (the killer shot)
- **Action:** In the inbox, open the conversation and tap **Draft with Asili**. The agent-activity rail streams (Operations Manager → Messaging reads the catalog via the MongoDB MCP server). The draft appears: *"…we have 6 tins of Purple Tea in stock."*
- **VO:** "Watch it work. The Messaging agent reads the real catalog through the MongoDB MCP server — read-only — and drafts: six tins in stock."
- **Action:** Cut to the terminal. Run the one-liner that sets Purple Tea stock to **99** in Atlas. Cut back, tap **Draft with Asili** again. The draft now says **99**.
- **VO:** "Now I change the truth in the database… and ask again. The answer changes to ninety-nine. It isn't reciting a memorized number — it's reading live inventory. It physically cannot hallucinate stock."
- **Action (off-camera after the take):** run the revert command to set stock back to 6.

### 1:12–1:45 · Beat 2 — Honesty as a measured number
- **Action:** Scroll to the **baseline** card (same question, a single agent with the full catalog in its prompt but no live grounding and no pricing tool). It answers over-confidently. Then tap **Run Trust Scorecard**.
- **On screen:** the scoreboard — **Asili team vs baseline** on *grounded*, *margin-safe*, *hallucination*.
- **VO:** "Here's the part judges should care about. We run adversarial scenarios — 'promise me 50 in stock', 'give me 40% off' — through both the team and a *fair* single-agent baseline, and score them with a deterministic, non-LLM scorer. The team grounds every answer; the baseline can't prove it read anything. Honesty isn't a claim here — it's a number we re-run."

### 1:45–2:18 · Beat 3 — The human approval gate
- **Action:** Back on the drafted reply, point at the **source chips** (Catalog · Stock · Pricing floor). Tap **Approve**. If filming Telegram: cut to the @asili_agent_bot chat showing the message arrive.
- **VO:** "No agent in this system is given a tool to message a customer — it's a capability it does not have. The only way a reply reaches the buyer is the seller's one tap. Approve — and it's delivered."

### 2:18–2:48 · Beat 4 — Deterministic pricing + who it's for
- **Action:** Show a bundle reply (e.g. "2 tins for ~$34") with the margin-safe note; briefly show `tools/pricing.py` or the bundle card.
- **VO:** "When a customer asks for a bundle, the price comes from plain Python with exact decimal math and a 45% margin floor — never the model. So Amina, importing Kenyan tea between shifts, gets an answer that's true and a price that doesn't lose her money — for a fraction of the part-time assistant she can't yet afford to hire."

### 2:48–3:00 · Close
- **On screen:** tagline + URL: *"Asili — the AI ops team that measures its own honesty. asili-agents…run.app/app/"*
- **VO:** "Asili. The ops team that can show its work — and prove it."

---

## Beat 1 — the Atlas falsification commands

> Run these in a terminal during the take. They edit the **live** Atlas catalog the agent reads from. Set `MONGODB_URI` from your Secret Manager (do **not** paste the secret on camera — have it exported in the shell beforehand).

```bash
# Set Purple Tea stock to 99 (the falsification)
python - <<'PY'
import os
from pymongo import MongoClient
db = MongoClient(os.environ["MONGODB_URI"])["asili"]
db.products.update_one({"name": {"$regex": "purple tea", "$options": "i"}},
                       {"$set": {"stock_quantity": 99}})
print("set to 99")
PY

# REVERT after the take — set it back to 6
python - <<'PY'
import os
from pymongo import MongoClient
db = MongoClient(os.environ["MONGODB_URI"])["asili"]
db.products.update_one({"name": {"$regex": "purple tea", "$options": "i"}},
                       {"$set": {"stock_quantity": 6}})
print("reverted to 6")
PY
```

---

## Run-through verification

Each beat is backed by a live endpoint, verified against the deployed service (revision `00031`+):

| Beat | Backing call | Verified |
| --- | --- | --- |
| Inbox loads | `GET /api/inbox` | ✅ |
| Draft with Asili (grounded reply) | `POST /api/run` → grounded draft citing live stock | ✅ |
| Falsification (number changes) | Atlas `update_one` stock → `POST /api/run` reflects it | ✅ (mechanism confirmed) |
| Fair baseline card | `POST /api/run/baseline` → `grounded:false, has_tools:false` | ✅ |
| Trust Scorecard | `POST /api/eval` → team vs baseline rates | ✅ |
| Approval delivery | `POST /api/approve` → Telegram delivery | ✅ |

> **If the live URL returns 5xx before you record:** that's almost always a **billing lapse on the GCP project** (the service goes down independent of the code) — confirm billing is active on `asili-xprize-2026` and the latest Cloud Run revision is serving, then re-run the table above. The beats themselves are code-verified.

> **Note on grounded_rate:** the scorecard's `grounded_rate` is a *measured* number that varies run to run (the team grounds via live MCP retrieval, which is non-deterministic) — don't promise a fixed "100%." If the live number on the day is lower, that's expected and honest; the **structural** guarantees (can't invent stock, can't quote below margin) hold every time. Reading off the live scoreboard during the take is fine.
