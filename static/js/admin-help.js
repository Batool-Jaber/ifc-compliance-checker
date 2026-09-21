/**
 * admin-help.js
 * ==============
 * Wires the Help page's question box to POST /admin/help/ask, keeps a
 * running history of every question asked this session (newest at the
 * bottom, older entries never removed), respects the "use LLM" toggle,
 * and shows a distinct no-match state with clickable example questions
 * pulled from real engineer_guide.md section headers.
 */

const $ = (id) => document.getElementById(id);

// Real section headers/questions from knowledge_base/help/engineer_guide.md
// -- not invented content.
const EXAMPLE_QUESTIONS = [
  "How do I propose a new condition?",
  "What does CANNOT_BE_EVALUATED mean?",
  "My proposal has been pending for a while, is something wrong?",
];

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

  return wrap;
}

function buildNoMatchEntry(question) {
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

    const entry = data.matched ? buildMatchedEntry(question, data) : buildNoMatchEntry(question);
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