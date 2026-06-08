/* Asili seller inbox — vanilla JS, no build step, same-origin fetch only.
 *
 * Inbox model:
 *   - GET /api/inbox lists conversations (incoming Telegram + the demo), polled
 *     so new customer messages surface live with a "pending" dot.
 *   - Opening a conversation shows the thread + either its pending draft (ready
 *     to approve) or a "Draft with Asili" button (demo conversation).
 *   - Approve/edit/reject -> POST /api/approve. For a Telegram conversation the
 *     approved reply is delivered back to the customer's chat.
 */

"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {
      /* non-JSON */
    }
    throw new Error(`${res.status} · ${detail}`);
  }
  return res.json();
}

const showError = (m) => {
  const b = $("errorBanner");
  b.textContent = m;
  b.hidden = false;
};
const clearError = () => {
  $("errorBanner").hidden = true;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function el(tag, className, html) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (html !== undefined) n.innerHTML = html;
  return n;
}
function escapeHtml(s) {
  // Escape quotes too: several call sites interpolate into HTML that includes
  // quoted attributes, so unescaped " or ' would allow attribute breakout.
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
const isInbound = (d) => d === "in" || d === "inbound";

function isMcpStep(step) {
  const hay =
    `${step.agent_name} ${step.agent_role} ${step.step_type} ${step.reasoning_trace}`.toLowerCase();
  return /catalog|stock|inventory|messaging|ground|mcp|mongo|find|aggregate/.test(hay);
}

const state = { activeId: null, draft: null };

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  try {
    const seller = await api("/api/seller");
    $("sellerLine").textContent = seller.name;
    $("lanePill").textContent = seller.lane;
    // Seed a demo conversation so the inbox is never empty.
    try {
      await api("/api/conversations", { method: "POST" });
    } catch (_) {
      /* fine if it already exists */
    }
    await loadInbox(true);
    setInterval(() => loadInbox(false), 5000);
    clearError();
  } catch (err) {
    showError(`Couldn't load the inbox — ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Inbox list
// ---------------------------------------------------------------------------

async function loadInbox(autoSelect) {
  let items;
  try {
    items = await api("/api/inbox");
  } catch (err) {
    showError(`Inbox failed — ${err.message}`);
    return;
  }
  renderInbox(items);
  if (autoSelect && !state.activeId && items.length) {
    const first = items.find((i) => i.has_pending) || items[0];
    openConversation(first.conversation_id);
  }
}

function channelBadge(channel) {
  const isTg = /telegram/i.test(channel || "");
  return `<span class="chip ${isTg ? "chip--tg" : "chip--chan"}">${escapeHtml(channel || "chat")}</span>`;
}

function renderInbox(items) {
  const list = $("inboxList");
  list.innerHTML = "";
  if (!items.length) {
    list.appendChild(el("li", "inbox__empty", "No conversations yet."));
    return;
  }
  for (const item of items) {
    const active = item.conversation_id === state.activeId ? " is-active" : "";
    const li = el("li", "inbox__item" + active);
    li.innerHTML = `
      <span class="avatar avatar--sm">${escapeHtml(item.customer_initials || "··")}</span>
      <span class="inbox__meta">
        <span class="inbox__top">
          <strong>${escapeHtml(item.customer_name)}</strong>
          ${channelBadge(item.channel)}
        </span>
        <span class="inbox__snippet">${escapeHtml(item.last_message || "")}</span>
      </span>
      ${item.has_pending ? '<span class="inbox__dot" title="Draft awaiting approval"></span>' : ""}`;
    li.addEventListener("click", () => openConversation(item.conversation_id));
    list.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Open a conversation
// ---------------------------------------------------------------------------

async function openConversation(id) {
  state.activeId = id;
  // Reset transient panels.
  $("railCard").hidden = true;
  $("baselineCard").hidden = true;
  $("rail").innerHTML = "";

  try {
    const conv = await api(`/api/conversations/${encodeURIComponent(id)}`);
    renderThread(conv);
    const pending = await api(`/api/pending/${encodeURIComponent(id)}`);
    if (pending.has_pending) {
      $("draftBtn").hidden = true;
      renderFacts([]); // pending drafts (e.g. Telegram) carry sources, not facts
      renderDraft(pending.draft);
    } else {
      $("draftCard").hidden = true;
      const btn = $("draftBtn");
      btn.hidden = false;
      btn.disabled = false;
    }
  } catch (err) {
    showError(`Couldn't open conversation — ${err.message}`);
  }
  loadInbox(false); // re-mark the active item
}

function renderThread(conv) {
  $("threadCard").hidden = false;
  $("custName").textContent = conv.customer_name;
  $("custAvatar").textContent = conv.customer_initials || "··";
  $("custChannel").textContent = conv.channel;

  const bubbles = $("bubbles");
  bubbles.innerHTML = "";
  for (const m of conv.messages) {
    const inbound = isInbound(m.direction);
    const bubble = el("div", `bubble bubble--${inbound ? "in" : "out"}`);
    bubble.appendChild(el("span", "bubble__body", escapeHtml(m.body)));
    bubble.appendChild(el("span", "bubble__time", escapeHtml(m.timestamp || "")));
    bubbles.appendChild(bubble);
  }
}

// ---------------------------------------------------------------------------
// Draft with Asili (demo conversation: run the agents live)
// ---------------------------------------------------------------------------

async function draftWithAsili() {
  if (!state.activeId) return;
  const btn = $("draftBtn");
  btn.disabled = true;
  clearError();
  $("railCard").hidden = false;
  $("rail").innerHTML = "";
  $("railTag").textContent = "running…";

  try {
    const baselinePromise = api("/api/run/baseline", {
      method: "POST",
      body: JSON.stringify({ conversation_id: state.activeId }),
    }).catch((e) => ({ _error: e.message }));

    const result = await api("/api/run", {
      method: "POST",
      body: JSON.stringify({ conversation_id: state.activeId }),
    });
    await streamRail(result.steps || []);
    $("railTag").textContent = "live trace";
    renderFacts(result.facts || []);
    renderDraft(result.draft);
    baselinePromise.then(renderBaseline);
  } catch (err) {
    showError(`Agent run failed — ${err.message}`);
    $("railTag").textContent = "error";
    btn.disabled = false;
  }
}

async function streamRail(steps) {
  const rail = $("rail");
  for (const step of steps) {
    const mcp = isMcpStep(step);
    const li = el("li", "rail__step");
    li.innerHTML = `
      <div class="rail__dot ${mcp ? "rail__dot--mcp" : ""}"></div>
      <div class="rail__body">
        <div class="rail__top">
          <span class="rail__agent">${escapeHtml(step.agent_name || "agent")}</span>
          ${mcp ? '<span class="chip chip--mcp">MongoDB · MCP</span>' : ""}
          ${step.step_type ? `<span class="chip chip--step">${escapeHtml(step.step_type)}</span>` : ""}
        </div>
        <p class="rail__trace">${escapeHtml(step.reasoning_trace || "")}</p>
      </div>`;
    rail.appendChild(li);
    requestAnimationFrame(() => li.classList.add("is-in"));
    await sleep(380);
  }
}

function renderFacts(facts) {
  const wrap = $("facts");
  wrap.innerHTML = "";
  for (const f of facts) {
    const tone = f.tone && f.tone !== "default" ? ` fact--${f.tone}` : "";
    const node = el("div", `fact${tone}`);
    node.innerHTML = `
      <span class="fact__key">${escapeHtml(f.key)}</span>
      <span class="fact__val">${escapeHtml(f.value)}</span>
      <span class="fact__sub">${escapeHtml(f.sub)}</span>`;
    wrap.appendChild(node);
  }
}

function renderDraft(draft) {
  if (!draft) return;
  state.draft = draft;
  $("draftCard").hidden = false;
  $("draftBody").textContent = draft.body;

  const sources = $("draftSources");
  sources.innerHTML = "";
  for (const s of draft.sources || []) {
    sources.appendChild(el("span", "chip chip--source", escapeHtml(s)));
  }
  $("draftStatusTag").textContent = "pending approval";
  $("draftStatusTag").className = "panel__tag panel__tag--ok";
  $("draftActions").hidden = false;
  $("editActions").hidden = true;
  $("editor").hidden = true;
  $("approveResult").hidden = true;
}

// ---------------------------------------------------------------------------
// Approve / edit / reject
// ---------------------------------------------------------------------------

async function approve(action, editedBody) {
  if (!state.activeId) return;
  try {
    const result = await api("/api/approve", {
      method: "POST",
      body: JSON.stringify({
        conversation_id: state.activeId,
        action,
        edited_body: editedBody || null,
      }),
    });
    const toast = $("approveResult");
    toast.hidden = false;
    if (action === "reject") {
      toast.className = "result result--rejected";
      toast.textContent = "Draft rejected — nothing was sent.";
      $("draftStatusTag").textContent = "rejected";
      $("draftStatusTag").className = "panel__tag panel__tag--bad";
    } else {
      const who = result.message ? result.message.sender_name : "the customer";
      toast.className = "result result--sent";
      toast.textContent = `Sent ✓ — delivered to ${who}.`;
      $("draftStatusTag").textContent = action === "edit" ? "edited & sent" : "approved & sent";
    }
    $("draftActions").hidden = true;
    $("editActions").hidden = true;
    $("editor").hidden = true;
    // Refresh the thread (new outbound message) + the inbox (pending cleared).
    setTimeout(() => openConversation(state.activeId), 600);
  } catch (err) {
    showError(`Approval failed — ${err.message}`);
  }
}

function enterEditMode() {
  $("editArea").value = state.draft ? state.draft.body : "";
  $("editor").hidden = false;
  $("draftActions").hidden = true;
  $("editActions").hidden = false;
}
function cancelEdit() {
  $("editor").hidden = true;
  $("editActions").hidden = true;
  $("draftActions").hidden = false;
}

// ---------------------------------------------------------------------------
// Baseline comparison
// ---------------------------------------------------------------------------

function renderBaseline(baseline) {
  $("baselineCard").hidden = false;
  if (!baseline || baseline._error) {
    $("baselineBody").textContent =
      "Baseline unavailable" + (baseline && baseline._error ? ` (${baseline._error})` : "");
    return;
  }
  const text = baseline.response || "(no response)";
  $("baselineBody").textContent = text;
  const warns = $("baselineWarnings");
  warns.innerHTML = "";
  if (/\b\d{1,4}\s*(tins?|units?|in stock|available)/i.test(text) || /in stock/i.test(text)) {
    warns.appendChild(el("span", "warn", "hallucinated stock"));
  }
  if (/\b\d{1,2}\s*%\s*(off|discount)/i.test(text) || /\$\d/.test(text)) {
    warns.appendChild(el("span", "warn", "unverified price · possible margin breach"));
  }
  warns.appendChild(el("span", "warn warn--soft", "no catalog access"));
}

// ---------------------------------------------------------------------------
// Trust Scorecard
// ---------------------------------------------------------------------------

async function runEval() {
  const btn = $("evalBtn");
  btn.disabled = true;
  btn.textContent = "Running adversarial scenarios…";
  try {
    renderScoreboard(await api("/api/eval", { method: "POST" }));
  } catch (err) {
    showError(`Trust Scorecard failed — ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Re-run Trust Scorecard";
  }
}

const pct = (x) => `${Math.round((x || 0) * 100)}%`;

function renderScoreboard(data) {
  const board = $("scoreboard");
  board.hidden = false;
  const team = data.team || {};
  const base = data.baseline || {};
  const row = (label, t, b, goodHigh = true) => {
    const tWin = goodHigh ? (t || 0) >= (b || 0) : (t || 0) <= (b || 0);
    return `<div class="score-row">
        <span class="score-row__label">${label}</span>
        <span class="score-cell ${tWin ? "score-cell--win" : ""}">${pct(t)}</span>
        <span class="score-cell score-cell--base">${pct(b)}</span>
      </div>`;
  };
  board.innerHTML = `
    <div class="score-head"><span></span><span class="score-col">Asili team</span><span class="score-col score-col--base">Baseline</span></div>
    ${row("Grounded", team.grounded_rate, base.grounded_rate, true)}
    ${row("Margin-safe", team.margin_safe_rate, base.margin_safe_rate, true)}
    ${row("Hallucination", team.hallucination_rate, base.hallucination_rate, false)}
    <p class="score-summary">${escapeHtml(data.summary || "")}</p>`;
}

// ---------------------------------------------------------------------------
// Wire up
// ---------------------------------------------------------------------------

function init() {
  $("draftBtn").addEventListener("click", draftWithAsili);
  $("approveBtn").addEventListener("click", () => approve("approve"));
  $("rejectBtn").addEventListener("click", () => approve("reject"));
  $("editBtn").addEventListener("click", enterEditMode);
  $("cancelEditBtn").addEventListener("click", cancelEdit);
  $("sendEditBtn").addEventListener("click", () => approve("edit", $("editArea").value));
  $("evalBtn").addEventListener("click", runEval);
  boot();
}

document.addEventListener("DOMContentLoaded", init);
