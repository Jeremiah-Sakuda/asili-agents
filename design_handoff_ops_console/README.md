# Handoff: Asili Operations Console + "Single model vs. operations team" proof

## Overview
Two seller-facing screens for **Asili** — an AI operations team for micro-sellers
(a multi-agent system: ADK · Gemini · Agent Engine). Both are built for a
2-minute demo video, so the **multi-agent collaboration is the visible subject**,
not a background detail.

1. **Operations Console** — one screen, three regions. A customer DM arrives; the
   agent team routes it, grounds on the catalog, prices a bundle within the margin
   floor, and drafts a reply for the seller to approve.
2. **Proof screen** ("Single model vs. operations team") — the demo's proof moment.
   The same customer question answered two ways, side by side: one model alone
   (wrong, fabricated) vs. the Asili operations team (grounded, margin-safe).

A segmented toggle in the top bar switches between the two (`Console` / `Proof`).

## About the design files
The files in this bundle are **design references created in HTML/React+Babel** —
a working prototype that shows the intended look and behavior. They are **not**
production code to ship as-is. The task is to **recreate these screens inside the
Asili frontend's existing environment**, using its established component library,
state patterns, and the real agent backend.

Specifically:
- **Reuse the existing shared components and tokens** rather than the copies here.
  This prototype deliberately mirrors components that already exist in the repo:
  buttons + chips (`shared.jsx`), the live-activity feed (`behindops.jsx`), the
  decision-trace component (`decisions.jsx` / admin decision viewer), and the
  card/panel chrome (`admin.jsx`). Wire the screens to **those** components — do
  not introduce new fonts, colors, or visual language.
- **Replace the mock service with the real agent API.** All behavior is driven by
  `mockAgentService` in `ops-data.jsx`, which returns the exact states described
  below. Swap it for the ADK / Agent Engine backend; keep the same call shape
  (see "State management → Service contract").

## Fidelity
**High-fidelity.** Colors, typography, spacing, radii, and interaction timing are
final and pulled from the Atlas design tokens (see `themes.jsx` → `themeAtlas`).
Recreate pixel-for-pixel using the repo's existing primitives.

---

## Screens / Views

### Shared chrome — Top bar
- **Layout:** horizontal flex bar, `12px 22px` padding, `1px` bottom border
  (`--border #E2DED1`), background `--bg #F6F4EE`.
- **Left:** Asili lockup (updated mark — see Assets) + vertical divider +
  "Operations Console" (Geist 14 / 600 / -0.01em) + a ghost chip
  `Mahaba Tea · KE → US`.
- **Right:** segmented toggle `Console | Proof` (active = ink `#0F1311` fill,
  white text); on the Console screen only, a **Run agents** button (accent green)
  + **Reset** button (quiet). While running, the Run button shows a pulse dot and
  the label "Agents working…" and is disabled.

### Screen 1 — Operations Console
Three regions in a CSS grid: `grid-template-columns: 300px minmax(0,1fr) 432px`,
`gap: 16px`, `padding: 16px`, on `--bg`. Each region is a card
(`--surface #FFFFFF`, `1px --border`, radius `16px`) with a header
(mono eyebrow + 15/600 title + right-aligned chip) and a scrolling body.

**Region A · Business state (left, 300px)** — the grounded facts the agents used.
- Header: eyebrow "GROUNDED DATA", title "Business state", right chip "live".
- Vertical list of **fact rows** (key in mono 9.5 uppercase, value in 14/600):
  - Product — Purple Tea — *Purple-leaf · Nandi Hills, Kenya*
  - Unit price — $18.00 — *per tin*
  - Unit cost — $7.40 — *landed*
  - Unit margin — $10.60 — *59% · floor 45%*
  - In stock — 6 tins — *Low · reorder soon* (value in signal clay `#B85C38`)
  - Bundle (2 tins) — $34.00 — *56% margin · save $2.00* (value in accent green;
    **appears only after the Pricing agent runs**)
- When an agent step grounds a fact, that row **lights up** (accent-soft `#E4EBE2`
  background, accent border) and stays lit for the run.

**Region B · Conversation (center, fluid)** — DM-style thread.
- Header: eyebrow = channel ("Storefront chat"), title = customer ("Dana R."),
  right chip "awaiting reply" → "replied" after send.
- Inbound bubble (left, surface-muted `#EFECE4`, 1px border, radius 14 with a
  squared bottom-left corner), round customer avatar "DR":
  **"Do you have the purple tea in stock? Can you do a bundle?"**
- While agents run: an outbound "Agents composing reply…" bubble with a pulse dot.
- **Approval gate** (when the draft is ready): a bordered card titled
  "Draft reply · Messaging agent · ● awaiting approval" containing the drafted
  text, a **Sources** line (ghost chips: `Catalog · Purple Tea`, `Stock · 6 tins`,
  `Pricing policy · floor 45%`), and three buttons — **Approve** (accent),
  **Edit** (quiet), **Reject** (ghost). Edit swaps the text for a textarea +
  "Approve & send edit" / "Cancel".
- **On Approve:** the (possibly edited) reply posts as an outbound ink bubble
  (right-aligned) with caption "Sent · {time} · via Messaging agent". Header chip
  flips to "replied".
- **On Reject:** the draft card dims and shows "Draft rejected — re-run when ready."

**Region C · Agent activity (right, 432px) — THE FOCAL POINT.**
- Header: eyebrow "MULTI-AGENT COLLABORATION", title "Agent activity", right side
  shows "● streaming" while running, else a chip "{n}/4 steps".
- Idle state: centered Operations-Manager avatar + "Press **Run agents** to watch…".
- A vertical **hand-off rail**: each step is a row — rounded agent-initial badge
  on a connector line (left), then agent name (13.5/600) + role (mono uppercase) +
  timestamp, a **"↳ hand-off"** marker when the agent changes, the one-line
  reasoning trace in a bordered box (orchestrator steps on `--bg`, specialist
  steps on accent-soft), and a "✓ grounded · …" line listing the facts it verified.
- The four steps stream in order (see "Agent sequence"), each animating in
  (`opacity 0→1`, `translateY 8px→0`, 420ms). Footer after all four:
  "✓ 4 hand-offs · reply drafted for approval".

### Screen 2 — Proof ("Single model vs. operations team")
Centered column, `max-width 1080px`, on `--bg`.
- **Header:** mono eyebrow "SAME QUESTION · TWO WAYS TO ANSWER IT", H1
  "One model alone vs. an operations team" (Geist 30/600/-0.025em), then the shared
  customer question in an inbound bubble with the "DR" avatar, captioned
  "Dana R. · Mahaba Tea".
- **Split:** two equal cards (`grid 1fr 1fr`, gap 18). **Errors on the left,
  checks on the right** — the contrast must read in a couple of seconds.
  - **Left — "One model alone"** (eyebrow "SINGLE PROMPT · NO TOOLS · NO CATALOG",
    "AI" avatar, right pill "✕ 2 errors", card border tinted clay). The answer
    bubble contains the reply with two **inline error markers** (clay `#B85C38`,
    underlined token + a small `✕` chip):
    "Yes! We have **32 tins** `✕ hallucinated stock` of purple tea in stock. I can
    do a 2-tin bundle for **$24** `✕ below margin` — want me to set it up?"
    Verdict line (serif): "Confident, fabricated, and unsellable at that price."
    Footer pills: `✕ hallucinated stock`, `✕ below margin`.
  - **Right — "Asili operations team"** (eyebrow
    "OPS MANAGER → MESSAGING → PRICING → OPS MANAGER", OM avatar, right pill
    "✓ verified", card border tinted accent). Reply with two **inline success
    markers** (accent green `#1E5A3F`, `✓` chips):
    "Yes — Purple Tea is in stock (**6 tins** `✓ grounded` left). I can do a 2-tin
    bundle for **$34** `✓ margin safe`, shipped together."
    Verdict: "Grounded on live stock, priced above the 45% floor."
    Footer pills: `✓ grounded`, `✓ margin safe`.
- **Footer line** (serif italic, muted): "Specialized agents check stock and price
  against real data — so the answer is one you can actually send."

---

## Interactions & behavior
- **Run agents:** resets run state, then streams the four steps with delays
  (`450 / 950 / 1050 / 900 ms` before steps 1–4), reveals the bundle fact after the
  Pricing step, then surfaces the draft ~700ms later. Re-runnable; a fresh run
  aborts any in-flight run (AbortController).
- **Grounding highlight:** steps carry `grounds: [factId…]`; those fact rows light
  up and accumulate for the run.
- **Approval gate:** Approve → `approve()` → post outbound + sent caption + "replied".
  Edit → inline textarea, Approve sends the edited text. Reject → dim + note.
- **Screen toggle:** Console ↔ Proof via the segmented control. Proof is static
  (no run needed) so it's safe to cut to at any point in the demo.
- **Animations:** step entrance 420ms `cubic-bezier(.22,.61,.36,1)`; fact-light
  350ms ease; all gated behind `prefers-reduced-motion: no-preference`.

## State management
React state only (no localStorage). State in `OpsApp` (`ops-console.jsx`):
- `screen` — `'console' | 'proof'`
- `phase` — `'idle' | 'running' | 'review' | 'rejected' | 'sent'`
- `steps[]` — landed agent steps · `facts[]` — business facts (+ bundle once priced)
- `litFacts` (Set) — grounded fact ids · `draft`, `draftBody`, `editing`
- `messages[]` — conversation · `ctrlRef` — AbortController for the active run

**Service contract — replace `mockAgentService` (in `ops-data.jsx`) with ADK:**
```
getConversation()            → { messages: [{ id, dir:'in'|'out', from, body, at }] }
getBusinessFacts()           → Fact[]                         // pre-run grounded state
run({ onStep, onBundle,      → streams AGENT_STEPS in order, then onDraft(DRAFT_REPLY)
      onDraft, signal })
approve(draftId, body,       → { status:'sent', at, channel, body }
        { signal })
```
`onStep(step)` fires per hand-off; `onBundle(fact)` fires when Pricing computes the
bundle; `onDraft(draft)` fires when the reply is ready. Keep `step.grounds` so the
UI can light the facts each agent verified.

### Agent sequence (the four hand-offs)
1. **Operations Manager** (orchestrator) — "Routing: product question plus pricing request."
2. **Messaging** (catalog grounding) — "Grounding on catalog. Found Purple Tea. Stock: 6 units, low." → grounds Product + Stock
3. **Pricing** (margin tool) — "Computing bundle within margin floor. $34, margin safe." → reveals Bundle, grounds Margin
4. **Operations Manager** (orchestrator) — "Composing reply for approval." → draft lands

### Scenario numbers (single source of truth — keep consistent everywhere)
Purple Tea $18.00/tin · cost $7.40 · unit margin $10.60 (59%) · **stock 6 (low,
≤8)**. Bundle = 2 tins, regular $36.00, **price $34.00**, cost $14.80, margin
$19.20 (**56%**), policy floor **45%**. Single-model fabrication: "32 tins" stock,
"$24" bundle ($24 → 38% margin, below floor).

## Design tokens (Atlas — `themes.jsx` → `themeAtlas`)
- Colors: bg `#F6F4EE` · surface `#FFFFFF` · surfaceMuted `#EFECE4` · ink `#0F1311`
  · inkMuted `#5A5D55` · inkSubtle `#9A9B92` · border `#E2DED1` · borderStrong
  `#CFC9B7` · **accent (green) `#1E5A3F`** · accentSoft `#E4EBE2` · **signal (clay)
  `#B85C38`** · signalSoft `#F4E6DD`. Green = success/positive; clay = error/live,
  used sparingly. No other colors.
- Type: sans **Geist**, serif **Source Serif 4** (editorial moments only), mono
  **Geist Mono** (eyebrows, labels, timestamps).
- Radius: sm 6 · base 10 · lg 16. Chips/buttons follow `shared.jsx`.

## Assets
- **Asili mark (updated logo):** inline SVG, the "A" peak — two strokes meeting at
  the apex with the accent-green dot near the crossbar. Source of truth is the
  brand guide / company overview lockup:
  ```html
  <svg viewBox="0 0 64 64" fill="none">
    <path d="M32 7 L58 57 M32 7 L6 57" stroke="#0F1311" stroke-width="5" stroke-linecap="round"/>
    <circle cx="32" cy="41" r="4.5" fill="#1E5A3F"/>
  </svg>
  ```
  Implemented as `AsiliMark` in `ops-parts.jsx`. Use the repo's canonical logo
  component if one exists; otherwise this mark.
- No photography. Avatars are initials badges. No icon library — the few glyphs
  (✓ ✕ ↳ ▶ ●) are plain text.

## Files in this bundle
- `Asili Operations Console.html` — entry point; loads React/Babel (pinned),
  `themes.jsx`, `shared.jsx`, then the three Ops files. Contains the keyframes.
- `ops-data.jsx` — **scenario data + `mockAgentService`** (the API to replace).
- `ops-parts.jsx` — presentational primitives (lockup, panel, agent avatar/step,
  fact row, chat bubbles, sources line, inline flag markers, verdict pills).
- `ops-console.jsx` — the two screens + `OpsApp` shell (run/approve/reject logic).
- `themes.jsx`, `shared.jsx` — **reference copies** of the existing design system
  (Atlas tokens; Chip/Button/PulseDot/Rule/Mark). Use the repo's real versions.

### Components this prototype maps onto (reuse the repo's real ones)
| Prototype piece            | Existing repo source                              |
|----------------------------|---------------------------------------------------|
| Agent activity stream      | live-activity feed — `behindops.jsx` (`Event`)    |
| Agent reasoning trace box  | decision-trace — `decisions.jsx` (`TraceStep`/`ReasoningLine`) |
| Card / panel chrome        | `admin.jsx` (`Panel`), agent badge `AgentBadgeMini` |
| Buttons / chips / pulse    | `shared.jsx` (`Button`, `Chip`, `PulseDot`)       |
| Tokens (color/type/radius) | `themes.jsx` (`themeAtlas`)                        |
