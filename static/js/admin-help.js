/**
 * admin-help.js
 * ==============
 * Two tabs on the Help page:
 * 1. "Ask the Guide" -- unchanged RAG question box (history, LLM
 *    toggle, no-match state with example chips).
 * 2. "My Proposals Status" -- NEW, tool-use: fetches
 *    GET /admin/help/proposals-status (a direct DB query, no RAG) and
 *    lists the engineer's own proposals with their real status.
 *
 * TAB-CONFUSION SAFETY NET: every /admin/help/ask response includes
 * possible_status_question (a simple keyword check done server-side).
 * When true, a soft hint is appended under that answer, with a button
 * that switches to the Status tab -- the Ask tab's own answer is never
 * replaced or hidden, this is purely an additive suggestion.
 */

const $ = (id) => document.getElementById(id);

const EXAMPLE_QUESTIONS = [
  "How do I propose a new condition?",
  "What does CANNOT_BE_EVALUATED mean?",
  "My proposal has been pending for a while, is something wrong?",
];

// ---------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------

function switchToTab(tabName) {
  document.querySelectorAll(".help-tab").forEach((btn) => {
    btn.classList.toggle("help-tab--active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".help-tab-panel").forEach((panel) => {
    panel.hidden = panel.dataset.tabPanel !== tabName;
  });
  if (tabName === "status") {
    loadProposalsStatus();
  }
}

document.querySelectorAll(".help-tab").forEach((btn) => {
  btn.addEventListener("click", () => switchToTab(btn.dataset.tab));
});

// ---------------------------------------------------------------------
// Tab 1: Ask the Guide (unchanged RAG flow, plus the status hint)
// ---------------------------------------------------------------------

function setLoading(isLoading) {
  $("help-loading").hidden = !isLoading;
  $("help-question").disabled = isLoading;
  $("help-ask-btn").disabled = isLoading;
}

function showHelpError(message) {
  const banner = $("help-error");
  banner.textContent = message;
  banner.hidden = false;
}

function clearHelpError() {
  $("help-error").hidden = true;
}

function maybeAddStatusHint(wrap, data) {
  if (!data.possible_status_question) return;
  const hint = document.createElement("div");
  hint.className = "help-status-hint";
  hint.innerHTML = `
    It looks like you might be asking about your own proposals, not the guide.
    <button type="button" class="btn btn--ghost help-status-hint__btn">Check My Proposals Status</button>
  `;
  hint.querySelector("button").addEventListener("click", () => switchToTab("status"));
  wrap.appendChild(hint);
}

function buildMatchedEntry(question, data) {
  const wrap = document.createElement("div");
  wrap.className = "help-entry";

  const q = document.createElement("div");
  q.className = "help-entry__question mono";
  q.textContent = `Q: ${question}`;
  wrap.appendChild(q);

  const card = document.createElement("div");
  card.className = "retrieval-card";
  card.innerHTML = `
    <div class="retrieval-card__query">Matched section <span class="help-score mono">score ${data.similarity_score}</span></div>
    <div class="retrieval-card__rule"></div>
    <div class="retrieval-card__detail"></div>
  `;
  card.querySelector(".retrieval-card__rule").textContent = data.section_title;
  card.querySelector(".retrieval-card__detail").textContent = data.section_text;
  wrap.appendChild(card);

  if (data.used_llm && data.answer) {
    const answer = document.createElement("div");
    answer.className = "ask-answer";
    answer.textContent = data.answer;
    wrap.appendChild(answer);
  }

  maybeAddStatusHint(wrap, data);
  return wrap;
}

function buildNoMatchEntry(question, data) {
  const wrap = document.createElement("div");
  wrap.className = "help-entry";

  const q = document.createElement("div");
  q.className = "help-entry__question mono";
  q.textContent = `Q: ${question}`;
  wrap.appendChild(q);

  const noMatch = document.createElement("div");
  noMatch.className = "help-no-match";
  noMatch.innerHTML = `
    <div class="help-no-match__title">No closely related section found</div>
    <p class="help-no-match__text">Try rephrasing, or check with an admin. A few questions the guide can answer:</p>
    <div class="help-examples"></div>
  `;
  const examplesWrap = noMatch.querySelector(".help-examples");
  EXAMPLE_QUESTIONS.forEach((eq) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "help-example-chip";
    chip.textContent = eq;
    chip.addEventListener("click", () => {
      $("help-question").value = eq;
      $("help-question").focus();
    });
    examplesWrap.appendChild(chip);
  });
  wrap.appendChild(noMatch);

  maybeAddStatusHint(wrap, data);
  return wrap;
}

async function askHelpQuestion() {
  const question = $("help-question").value.trim();
  if (!question) return;

  clearHelpError();
  setLoading(true);
  const useLlm = $("help-use-llm").checked;

  try {
    const res = await fetch("/admin/help/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, use_llm: useLlm }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to get an answer.");

    const entry = data.matched ? buildMatchedEntry(question, data) : buildNoMatchEntry(question, data);
    $("help-history").appendChild(entry);
    $("help-question").value = "";
  } catch (err) {
    showHelpError(err.message);
  } finally {
    setLoading(false);
  }
}

$("help-ask-btn").addEventListener("click", askHelpQuestion);
$("help-question").addEventListener("keydown", (e) => {
  if (e.key === "Enter") askHelpQuestion();
});

// ---------------------------------------------------------------------
// Tab 2: My Proposals Status (tool-use, no RAG)
// ---------------------------------------------------------------------

function renderProposalsStatus(proposals) {
  const list = $("help-status-list");
  list.innerHTML = "";

  if (proposals.length === 0) {
    list.innerHTML = `<p class="field__hint">You haven't submitted any proposals yet.</p>`;
    return;
  }

  proposals.forEach((p) => {
    const item = document.createElement("div");
    item.className = "help-status-item";
    item.innerHTML = `
      <div class="help-status-item__header">
        <span>${p.type === "new" ? "New: " : "Edit: "}${p.title ?? "(untitled)"}</span>
        <span class="mono" data-status="${p.status}">${p.status}</span>
      </div>
      <div class="help-status-item__meta mono">
        Submitted ${p.submitted_at}${p.reviewed_at ? ` · Reviewed ${p.reviewed_at}` : ""}
        ${p.reopened_from_id ? ` · reopened from #${p.reopened_from_id}` : ""}
      </div>
      ${p.review_note ? `<div class="help-status-item__note">${p.review_note}</div>` : ""}
    `;
    list.appendChild(item);
  });
}

async function loadProposalsStatus() {
  $("help-status-loading").hidden = false;
  $("help-status-list").innerHTML = "";

  try {
    const res = await fetch("/admin/help/proposals-status");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load your proposals.");
    renderProposalsStatus(data.proposals);
  } catch (err) {
    $("help-status-list").innerHTML = `<div class="help-error">${err.message}</div>`;
  } finally {
    $("help-status-loading").hidden = true;
  }
}