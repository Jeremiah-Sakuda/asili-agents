# Business case

> **Honest scope.** The personas and the numbers below are a **founder-built, bottom-up hypothesis**, not validated revenue. They are stated with their assumptions so they can be checked and corrected. The first post-submission milestone is **5 design-partner sellers** (§5), which replaces these estimates with real ones.

## 1. Who pays, and for what

The **seller is the customer** — a Black, immigrant, or diaspora micro-seller running a real business out of their Instagram / WhatsApp / Telegram DMs: importing Kenyan tea, West African shea butter, Levantine pantry goods, Haitian hot sauce. They are simultaneously the marketer, the warehouse, the accountant, and the 24/7 support desk.

They pay Asili to be their **back-office operations team**: it answers "is this in stock?" and "can you do a bundle?" from the *real* catalog, quotes only margin-safe prices, never sends without their one-tap approval, and can **prove on a scorecard** that it didn't make anything up. The wedge is trust: these sellers cannot afford an AI that bluffs their customers.

## 2. Pricing model

A simple per-seller SaaS subscription, priced well below the cost of a single avoided mistake:

| Tier | Price | For |
| --- | --- | --- |
| **Starter** | **$0** | 1 channel, up to 50 approved replies/mo. Removes adoption friction for the thinnest-margin sellers. |
| **Operator** | **$29 / mo** | All DM channels, unlimited approved replies, the Trust Scorecard, bundle pricing. The core plan. |
| **Studio** | **$79 / mo** | Multiple catalogs/brands, team approval seats, exportable audit history. |

Why a subscription (not rev-share): it is predictable for a thin-margin seller, doesn't tax their revenue, and aligns price with *operations relief*, not their sales. A usage add-on (per approved reply beyond the included volume) is the natural expansion lever.

## 3. Per-seller ROI (illustrative unit economics)

Take **Amina**, importing single-origin Kenyan tea, ~**$5,000/mo GMV**, ~50–55% gross margin, answering DMs between shifts. A generic chatbot does two things that cost her real money:

| Failure a naive bot causes | Frequency (est.) | Cost each | Monthly bleed |
| --- | --- | --- | --- |
| **Phantom inventory** — promises stock she doesn't have → refund + chargeback + lost repeat customer | ~2 / mo | ~$25 (refund/chargeback/fees) + churned LTV | **~$50+** |
| **Below-margin discount** — invents "30% off" on a thin-margin SKU | ~3 / mo | ~$8 margin given away per order | **~$24** |
| **Hours on the phone** — answering the same stock/price questions by hand | ~5 hrs / mo | her time | (opportunity cost) |

Asili **structurally prevents both money-losing failures** (read-only grounding can't invent stock; the deterministic engine can't quote below the 45% floor). Conservatively, that's **~$70–90/mo of avoided loss plus hours back** — so the **$29 Operator plan pays for itself on the first prevented mistake**, every month. That is the entire pitch in one number: *the product costs less than one chargeback.*

## 4. Market (bottom-up TAM/SAM/SOM)

Sized from the segment up, with assumptions stated so they can be challenged:

- **TAM — informal/social-commerce sellers.** Tens of millions of micro-merchants worldwide sell primarily through social DMs rather than a storefront platform. At a $29/mo ACV, even a few million reachable sellers is a multi-billion-dollar TAM. *(Order-of-magnitude; the point is the floor is large, not the exact figure.)*
- **SAM — our beachhead.** English-speaking **diaspora micro-sellers in the US/UK/EU** running import businesses on IG/WhatsApp/Telegram (African, Caribbean, Levantine, South Asian corridors). Assume **~1M** such sellers reachable through diaspora community networks → at the $29 plan, an **order-of-$300M/yr SAM**.
- **SOM — first 24 months.** A focused launch in **2–3 diaspora corridors** via community organizations and seller word-of-mouth. Capturing **5,000 paying Operator sellers** is **~$1.7M ARR** — a credible early target that needs no platform-scale distribution.

## 5. Why this wins, and how we de-risk it

- **Moat: measured honesty + deterministic money-math.** Shopify Inbox and Meta's business tools answer DMs, but they don't *ground every answer in live inventory* or *refuse below-margin quotes by construction*, and none can hand the seller a **re-runnable trust scorecard**. For a thin-margin importer, "won't bluff and won't lose me money" is the feature, and it's the one we can measure on a re-runnable scorecard.
- **Distribution: community-led, not ad-led.** The target sellers are reached through the same diaspora networks they already sell into — low CAC, high trust, built-in referral.
- **Honest validation plan.** The personas here are synthetic. The immediate next step is **5 design-partner sellers** in one corridor: instrument real avoided-refund and margin-protected dollars, replace the §3 estimates with measured ROI, and convert one into an on-camera testimonial. The architecture (multi-tenant path, channel expansion to WhatsApp/Instagram pending Meta approval) is already scoped in [ARCHITECTURE.md](ARCHITECTURE.md).

*This page is a hypothesis to be tested, not a claim of traction — stated this plainly on purpose, because the whole product is about not overclaiming.*
