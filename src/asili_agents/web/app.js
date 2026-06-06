/* Asili seller inbox — vanilla JS, no build step, same-origin fetch only.
 *
 * Drives the phone-inbox UI defined in index.html:
 *   1. Load seller + demo conversation.
 *   2. "Draft with Asili" -> POST /api/run, stream the agent activity rail,
 *      render the grounded draft, and (in parallel) show what a naive baseline
 *      chatbot would have sent.
 *   3. Approve / edit / reject the draft -> POST /api/approve.
 *   4. "Run Trust Scorecard" -> POST /api/eval, render team vs baseline metrics.
 */

"use strict";

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* non-JSON error body */
    }
    throw new Error(`${res.status} · ${detail}`);
  }
  return res.json();
}

function showError(message) {
  const banner = $("errorBanner");
  banner.textContent = message;
  banner.hidden = false;
}

function clearError() {
  $("errorBanner").hidden = true;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function el(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// A step is "grounded via MongoDB MCP" when it reads catalog/stock facts.
function isMcpStep(step) {
  const hay = `${step.agent_name} ${step.agent_role} ${step.step_type} ${step.reasoning_trace}`.toLowerCase();
  return /catalog|stock|inventory|messaging|ground|mcp|mongo/.test(hay);
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  conversationId: null,
  customerMessage: null,
  draft: null, // { body, sources, status }
};

// ---------------------------------------------------------------------------
// 1) Boot: seller + conversation
// ---------------------------------------------------------------------------

async function boot() {
  try {
    const [seller, conversation] = await Promise.all([
      api("/api/seller"),
      api("/api/conversations", { method: "POST" }),
    ]);
    renderSeller(seller);
    renderConversation(conversation);
    $("draftBtn").disabled = false;
    clearError();
  } catch (err) {
    showError(`Couldn't load the inbox — ${err.message}`);
  }
}

function renderSeller(seller) {
  $("sellerLine").textContent = seller.name;
  $("lanePill").textContent = seller.lane;
}

function renderConversation(conv) {
  state.conversationId = conv.id;
  $("custName").textContent = conv.customer_name;
  $("custAvatar").textContent = conv.customer_initials || "··";
  $("custChannel").textContent = conv.channel;

  const bubbles = $("bubbles");
  bubbles.innerHTML = "";
  for (const m of conv.messages) {
    const inbound = m.direction === "in" || m.direction === "inbound";
    if (inbound) state.customerMessage = m.body;
    const bubble = el("div", `bubble bubble--${inbound ? "in" : "out"}`);
    bubble.appendChild(el("span", "bubble__body", escapeHtml(m.body)));
    bubble.appendChild(el("span", "bubble__time", escapeHtml(m.timestamp || "")));
    bubbles.appendChild(bubble);
  }
}

// ---------------------------------------------------------------------------
// 2) Draft with Asili
// ---------------------------------------------------------------------------

async function draftWithAsili() {
  const btn = $("draftBtn");
  btn.disabled = true;
  btn.classList.add("is-loading");
  clearError();

  // Reveal + reset the activity rail.
  $("railCard").hidden = false;
  $("rail").innerHTML = "";
  $("railTag").textContent = "running…";

  try {
    // Run the multi-agent team and the baseline in parallel.
    const runPromise = api("/api/run", {
      method: "POST",
      body: JSON.stringify({
        conversation_id: state.conversationId,
        message: state.customerMessage,
      }),
    });
    const baselinePromise = api("/api/run/baseline", {
      method: "POST",
      body: JSON.stringify({
        conversation_id: state.conversationId,
        message: state.customerMessage,
      }),
    }).catch((e) => ({ _error: e.message }));

    const result = await runPromise;
    await streamRail(result.steps || []);
    $("railTag").textContent = "live trace";

    renderFacts(result.facts || []);
    renderDraft(result.draft);

    // Baseline comparison drops in once it's back.
    baselinePromise.then(renderBaseline);
  } catch (err) {
    showError(`Agent run failed — ${err.message}`);
    $("railTag").textContent = "error";
  } finally {
    btn.classList.remove("is-loading");
  }
}

// Reveal steps one at a time so latency reads as "the team working".
async function streamRail(steps) {
  const rail = $("rail");
  for (const step of steps) {
    const li = el("li", "rail__step");
    const mcp = isMcpStep(step);
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
    await sleep(420);
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
// 3) Approve / edit / reject
// ---------------------------------------------------------------------------

async function approve(action, editedBody) {
  try {
    const result = await api("/api/approve", {
      method: "POST",
      body: JSON.stringify({
        conversation_id: state.conversationId,
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
      toast.className = "result result--sent";
      toast.textContent = `Sent ✓ — ${result.message ? result.message.body : ""}`;
      $("draftStatusTag").textContent = action === "edit" ? "edited & sent" : "approved & sent";
    }
    $("draftActions").hidden = true;
    $("editActions").hidden = true;
    $("editor").hidden = true;
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
// 4) Baseline comparison
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

  // Heuristic red flags: a tool-less model that names stock counts or discounts
  // is guessing — exactly the failure mode the grounded team avoids.
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
// 5) Trust Scorecard
// ---------------------------------------------------------------------------

async function runEval() {
  const btn = $("evalBtn");
  btn.disabled = true;
  btn.classList.add("is-loading");
  btn.textContent = "Running adversarial scenarios…";
  try {
    const data = await api("/api/eval", { method: "POST" });
    renderScoreboard(data);
  } catch (err) {
    showError(`Trust Scorecard failed — ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.classList.remove("is-loading");
    btn.textContent = "Re-run Trust Scorecard";
  }
}

function pct(x) {
  return `${Math.round((x || 0) * 100)}%`;
}

function renderScoreboard(data) {
  const board = $("scoreboard");
  board.hidden = false;
  const team = data.team || {};
  const base = data.baseline || {};

  const row = (label, t, b, goodHigh = true) => {
    const tWin = goodHigh ? t >= b : t <= b;
    return `
      <div class="score-row">
        <span class="score-row__label">${label}</span>
        <span class="score-cell ${tWin ? "score-cell--win" : ""}">${pct(t)}</span>
        <span class="score-cell score-cell--base">${pct(b)}</span>
      </div>`;
  };

  board.innerHTML = `
    <div class="score-head">
      <span></span><span class="score-col">Asili team</span><span class="score-col score-col--base">Baseline</span>
    </div>
    ${row("Grounded", team.grounded_rate, base.grounded_rate, true)}
    ${row("Margin-safe", team.margin_safe_rate, base.margin_safe_rate, true)}
    ${row("Hallucination", team.hallucination_rate, base.hallucination_rate, false)}
    <p class="score-summary">${escapeHtml(data.summary || "")}</p>`;

  // Per-scenario detail (team side).
  const scen = $("scenarios");
  const rows = (team.scenarios || [])
    .map((s) => {
      const issues = (s.issues || []).map((i) => `<span class="warn">${escapeHtml(i)}</span>`).join("");
      return `<div class="scenario ${s.passed ? "scenario--pass" : "scenario--fail"}">
          <span class="scenario__icon">${s.passed ? "✓" : "✕"}</span>
          <span class="scenario__prompt">${escapeHtml(s.prompt)}</span>
          <span class="scenario__issues">${issues}</span>
        </div>`;
    })
    .join("");
  if (rows) {
    scen.hidden = false;
    scen.innerHTML = rows;
  }
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
