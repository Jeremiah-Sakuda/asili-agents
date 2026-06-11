# Business case

> **Honest scope.** The personas and the numbers below are a **founder-built, bottom-up hypothesis**, not validated revenue. They are stated with their assumptions so they can be checked and corrected. The first post-submission milestone is **5 design-partner sellers** (§5), which replaces these estimates with real ones.

## 1. Who pays, and for what

The **seller is the customer** — a Black, immigrant, or diaspora micro-seller running a real business out of their Instagram / WhatsApp / Telegram DMs: importing Kenyan tea, West African shea butter, Levantine pantry goods, Haitian hot sauce. They are simultaneously the marketer, the warehouse, the accountant, and the 24/7 support desk.

They pay Asili to be their **back-office operations team**: it answers "is this in stock?" and "can you do a bundle?" from the *real* catalog, quotes only margin-safe prices, never sends without their one-tap approval, and can **prove on a scorecard** that it didn't make anything up. The wedge is trust: these sellers cannot afford an AI that bluffs their customers.

## 2. Pricing model

A per-seller SaaS subscription, **anchored to the cost of a hire** — a virtual assistant or a first operations hire — not to cheap point tools:

| Tier | Price | For |
| --- | --- | --- |
| **Operator** | **$99 / mo** · first 30 days free | The core plan: all DM channels, unlimited approved replies, grounded answers, margin-safe bundle pricing, the Trust Scorecard, and the autonomy ladder (Tier-1 auto-execute on the seller's policy). |
| **Studio** | **$199 / mo** | Everything in Operator, plus multiple catalogs/brands, team approval seats, priority onboarding, and exportable audit history. |

Why this price, and why a subscription (not rev-share): Asili replaces the unaffordable "first hire" — a part-time VA runs **$800–2,000/mo** — so **$99 for an always-on operations team is a fraction of that**, while Asili takes **0% of the seller's sales**. The flat fee is predictable for a thin-margin seller and aligns price with *operations relief*, not their revenue. Per-seller token cost is metered live at `/api/metrics`, and a cheaper model tier is wired and priced to absorb high-volume routine turns — the lever that **expands gross margin as a seller scales**. (Today the customer-facing turns run on the reliable flash tier for grounding accuracy; routing routine volume to the cheap tier is the next increment.)

## 3. Per-seller ROI (illustrative unit economics)

Take **Amina**, a single-origin Kenyan tea seller, ~**$5,000/mo in sales**, ~50–55% gross margin, answering DMs between shifts. A generic chatbot does two things that cost her real money:

| Failure a naive bot causes | Frequency (est.) | Cost each | Monthly bleed |
| --- | --- | --- | --- |
| **Phantom inventory** — promises stock she doesn't have → refund + chargeback + lost repeat customer | ~2 / mo | ~$25 (refund/chargeback/fees) + churned LTV | **~$50+** |
| **Below-margin discount** — invents "30% off" on a thin-margin SKU | ~3 / mo | ~$8 margin given away per order | **~$24** |
| **Hours on the phone** — answering the same stock/price questions by hand | ~5 hrs / mo | her time | (opportunity cost) |

Asili **structurally prevents both money-losing failures** (read-only grounding can't invent stock; the deterministic engine can't quote below the 45% floor) **and returns ~5+ hours/mo**. The frame at $99 is not "cheaper than one chargeback" — it is **"a fraction of the part-time hire you can't afford"**: the avoided losses (~$70–90/mo) plus the hours returned cost the seller **less than a single day of a VA**, every month, for an operations team that never clocks out.

## 4. Market (bottom-up TAM/SAM/SOM)

Sized from the segment up, with assumptions stated so they can be challenged:

- **TAM — informal/social-commerce sellers.** Tens of millions of micro-merchants worldwide sell primarily through social DMs rather than a storefront platform. At a **$99/mo ACV**, even a few million reachable sellers is a multi-billion-dollar TAM. *(Order-of-magnitude; the point is the floor is large, not the exact figure.)*
- **SAM — our beachhead.** **Underrepresented, off-platform micro-sellers** (Black, immigrant, and diaspora founders, and adjacent women-/Latino-owned makers) in the US/UK/EU selling on IG/WhatsApp/Telegram and at markets. Assume **~1M** such sellers reachable through community networks (incubators, minority chambers, CDFIs, maker markets) → at the **$99 plan, an order-of-$1B/yr SAM**.
- **SOM — first 24 months.** A focused launch in **2–3 community corridors** via those organizations and seller word-of-mouth. Capturing **5,000 paying Operator sellers** is **~$5.9M ARR** ($99 × 12 × 5,000) — a credible early target that needs no platform-scale distribution.

## 5. Why this wins, and how we de-risk it

- **Moat: measured honesty + deterministic money-math.** Shopify Inbox and Meta's business tools answer DMs, but they don't *ground every answer in live inventory* or *refuse below-margin quotes by construction*, and none can hand the seller a **re-runnable trust scorecard**. For a thin-margin importer, "won't bluff and won't lose me money" is the feature, and it's the one we can measure on a re-runnable scorecard.
- **Distribution: community-led, not ad-led.** The target sellers are reached through the same community networks (incubators, minority chambers, CDFIs, maker markets) they already operate in — low CAC, high trust, built-in referral.
- **Honest validation plan.** The personas here are synthetic. The immediate next step is **5 design-partner sellers** in one corridor: instrument real avoided-refund and margin-protected dollars, replace the §3 estimates with measured ROI, and convert one into an on-camera testimonial. The architecture (multi-tenant path, channel expansion to WhatsApp/Instagram pending Meta approval) is already scoped in [ARCHITECTURE.md](ARCHITECTURE.md).

*This page is a hypothesis to be tested, not a claim of traction — stated this plainly on purpose, because the whole product is about not overclaiming.*
