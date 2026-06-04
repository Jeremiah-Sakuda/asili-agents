// ops-data.jsx — Scenario data + mock agent service for the Operations Console.
// This is the ONLY place the demo's "facts" live. Swap `mockAgentService` for
// the real ADK / Agent-Engine backend later; the screen components only depend
// on the shape of what it returns (see the JSDoc-style contracts below).

// ── Scenario (one customer message, one Bridge) ────────────────────────
const SCENARIO = {
  bridge:   { name: 'Mahaba Tea', lane: 'KE → US' },
  customer: { name: 'Dana R.', channel: 'Storefront chat', initials: 'DR' },
  inbound:  'Do you have the purple tea in stock? Can you do a bundle?',

  product: {
    name: 'Purple Tea',
    detail: 'Purple-leaf · Nandi Hills, Kenya',
    sku: 'MH-PRP-50',
    price: 18.0,      // per tin
    cost: 7.4,        // per tin (landed)
    stock: 6,         // live units
    lowThreshold: 8,  // ≤ this ⇒ "low"
  },
  policy: { marginFloor: 0.45 },            // pricing tool hard floor
  bundle: { units: 2, regular: 36.0, price: 34.0, cost: 14.8 },
};

// Derived figures (kept here so both screens agree to the cent)
const money = (n) => '$' + n.toFixed(2);
const pct = (n) => Math.round(n * 100) + '%';

const DERIVED = (() => {
  const p = SCENARIO.product, b = SCENARIO.bundle;
  const unitMargin = p.price - p.cost;                  // 10.60
  const bundleMargin = b.price - b.cost;                // 19.20
  return {
    unitMargin,
    unitMarginPct: unitMargin / p.price,                // .589
    bundleMargin,
    bundleMarginPct: bundleMargin / b.price,            // .565
    bundleSave: b.regular - b.price,                    // 2.00
    isLow: p.stock <= p.lowThreshold,
  };
})();

// ── Grounded business state — the card in the console sidebar ───────────
// Each fact has an id so an agent step can "light up" the fact it grounded.
const BUSINESS_FACTS = [
  { id: 'product', k: 'Product', v: SCENARIO.product.name, sub: SCENARIO.product.detail },
  { id: 'price',   k: 'Unit price', v: money(SCENARIO.product.price), sub: 'per tin' },
  { id: 'cost',    k: 'Unit cost', v: money(SCENARIO.product.cost), sub: 'landed' },
  { id: 'margin',  k: 'Unit margin', v: money(DERIVED.unitMargin), sub: pct(DERIVED.unitMarginPct) + ' · floor ' + pct(SCENARIO.policy.marginFloor) },
  { id: 'stock',   k: 'In stock', v: SCENARIO.product.stock + ' tins', sub: DERIVED.isLow ? 'Low · reorder soon' : 'Healthy', tone: DERIVED.isLow ? 'signal' : 'default' },
];

// Revealed only after the Pricing agent runs (the bundle didn't exist before).
const BUNDLE_FACT = {
  id: 'bundle', k: 'Bundle (2 tins)', v: money(SCENARIO.bundle.price),
  sub: pct(DERIVED.bundleMarginPct) + ' margin · save ' + money(DERIVED.bundleSave), tone: 'accent',
};

// ── The agent hand-off sequence (the focal stream) ─────────────────────
// `grounds` = ids of BUSINESS_FACTS this step verified against live data.
const AGENT_STEPS = [
  { id: 's1', agent: 'Operations Manager', role: 'Orchestrator', kind: 'route',
    trace: 'Routing: product question plus pricing request.', grounds: [], t: '+0.0s' },
  { id: 's2', agent: 'Messaging', role: 'Catalog grounding', kind: 'ground',
    trace: 'Grounding on catalog. Found Purple Tea. Stock: 6 units, low.', grounds: ['product', 'stock'], t: '+0.7s' },
  { id: 's3', agent: 'Pricing', role: 'Margin tool', kind: 'compute',
    trace: 'Computing bundle within margin floor. $34, margin safe.', grounds: ['bundle', 'margin'], t: '+1.5s', revealsBundle: true },
  { id: 's4', agent: 'Operations Manager', role: 'Orchestrator', kind: 'compose',
    trace: 'Composing reply for approval.', grounds: [], t: '+2.2s' },
];

// ── The drafted reply that lands in the thread for approval ─────────────
const DRAFT_REPLY = {
  id: 'draft_1',
  by: 'Messaging',
  body: "Hi Dana! Yes — our Purple Tea is in stock, though we're down to the last few tins this week. I can do a 2-tin bundle for $34 (normally $36) and ship them together. Want me to set one aside for you?",
  sources: ['Catalog · Purple Tea', 'Stock · 6 tins', 'Pricing policy · floor 45%'],
};

// ── Proof-moment content: same question, two ways to answer it ──────────
// Tokens flagged inline. marker: 'error' (clay ✕) | 'success' (green ✓).
const PROOF = {
  question: SCENARIO.inbound,
  left: {
    label: 'One model alone',
    sub: 'Single prompt · no tools · no catalog',
    avatarTone: 'default',
    // segments render in order; flagged ones carry a marker + note
    reply: [
      { text: 'Yes! We have ' },
      { text: '32 tins', flag: { marker: 'error', note: 'hallucinated stock' } },
      { text: ' of purple tea in stock. I can do a 2-tin bundle for ' },
      { text: '$24', flag: { marker: 'error', note: 'below margin' } },
      { text: ' — want me to set it up?' },
    ],
    verdict: 'Confident, fabricated, and unsellable at that price.',
  },
  right: {
    label: 'Asili operations team',
    sub: 'Ops Manager → Messaging → Pricing → Ops Manager',
    avatarTone: 'accent',
    reply: [
      { text: 'Yes — Purple Tea is in stock (' },
      { text: '6 tins', flag: { marker: 'success', note: 'grounded' } },
      { text: ' left). I can do a 2-tin bundle for ' },
      { text: '$34', flag: { marker: 'success', note: 'margin safe' } },
      { text: ', shipped together.' },
    ],
    verdict: 'Grounded on live stock, priced above the 45% floor.',
  },
};

// ── Mock agent service ─────────────────────────────────────────────────
// Contract (mirror this when wiring the real backend):
//   getConversation()        → { messages: Message[] }
//   getBusinessFacts()       → Fact[]                  (pre-run grounded state)
//   run({ onStep, signal })  → Promise<void>           (streams AGENT_STEPS)
//   approve(draftId)         → Promise<{status,at}>    (posts the reply)
// Message = { id, dir:'in'|'out', from, body, at }
const wait = (ms, signal) => new Promise((res, rej) => {
  const id = setTimeout(res, ms);
  if (signal) signal.addEventListener('abort', () => { clearTimeout(id); rej(new Error('aborted')); }, { once: true });
});

const nowLabel = () => new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

const mockAgentService = {
  getConversation() {
    return {
      messages: [
        { id: 'm_in', dir: 'in', from: SCENARIO.customer.name, body: SCENARIO.inbound, at: '2:11 PM' },
      ],
    };
  },
  getBusinessFacts() { return BUSINESS_FACTS.map((f) => ({ ...f })); },

  // Streams each hand-off with a short, demo-readable delay between steps.
  async run({ onStep, onBundle, onDraft, signal } = {}) {
    const gap = [450, 950, 1050, 900]; // ms before each step lands
    for (let i = 0; i < AGENT_STEPS.length; i++) {
      await wait(gap[i], signal);
      const step = AGENT_STEPS[i];
      onStep && onStep(step, i);
      if (step.revealsBundle) onBundle && onBundle({ ...BUNDLE_FACT });
    }
    await wait(700, signal);
    onDraft && onDraft({ ...DRAFT_REPLY });
  },

  async approve(_draftId, body, { signal } = {}) {
    await wait(500, signal);
    return { status: 'sent', at: nowLabel(), channel: SCENARIO.customer.channel, body };
  },
};

Object.assign(window, {
  SCENARIO, DERIVED, BUSINESS_FACTS, BUNDLE_FACT, AGENT_STEPS, DRAFT_REPLY, PROOF,
  mockAgentService, money, pct,
});
