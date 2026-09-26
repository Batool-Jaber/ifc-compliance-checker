/**
 * admin-code-advisory.js
 * ========================
 * Wires each pending proposal's "Check Building Code" button
 * (admin/proposals.html) to POST /admin/proposals/<id>/check-code --
 * a READ-ONLY, purely advisory lookup against the building-code
 * regulations (rag/vector_db.py, audience_role="admin"). NEVER blocks
 * or influences Approve/Reject -- results are always shown under an
 * explicit "Advisory only" badge so no admin mistakes this for an
 * automatic compliance verdict.
 */

function renderAdvisoryResults(container, matches) {
  container.innerHTML = "";
  container.hidden = false;

  const badge = document.createElement("span");
  badge.className = "code-advisory__badge";
  badge.textContent = "Advisory — not a compliance decision";
  container.appendChild(badge);

  if (matches.length === 0) {
    const empty = document.createElement("p");
    empty.className = "code-advisory__empty";
    empty.textContent = "No closely related regulation article found.";
    container.appendChild(empty);
    return;
  }

  matches.forEach((m) => {
    const card = document.createElement("div");
    card.className = "code-advisory-match";
    card.innerHTML = `
      <div class="code-advisory-match__title"></div>
      <div class="code-advisory-match__meta"></div>
      <div class="code-advisory-match__text"></div>
    `;
    card.querySelector(".code-advisory-match__title").textContent = m.title;
    card.querySelector(".code-advisory-match__meta").textContent =
      `Article ${m.article_number ?? "—"} · ${m.chapter_title ?? ""} · score ${m.score}`;
    card.querySelector(".code-advisory-match__text").textContent = m.text;
    container.appendChild(card);
  });
}

document.querySelectorAll(".code-advisory").forEach((box) => {
  const proposalId = box.dataset.proposalId;
  const runBtn = box.querySelector(".code-advisory__run");
  const resultsBox = box.querySelector(".code-advisory__results");
  let errorBox = null;

  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    runBtn.textContent = "Checking…";
    if (errorBox) errorBox.hidden = true;

    try {
      const res = await fetch(`/admin/proposals/${proposalId}/check-code`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Check failed.");
      renderAdvisoryResults(resultsBox, data.matches);
    } catch (err) {
      if (!errorBox) {
        errorBox = document.createElement("div");
        errorBox.className = "code-advisory__error";
        box.appendChild(errorBox);
      }
      errorBox.textContent = err.message;
      errorBox.hidden = false;
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "Check Building Code";
    }
  });
});