/**
 * admin-proposal-tester.js
 * ==========================
 * Wires each pending proposal's "Test" control (admin/proposals.html)
 * to POST /admin/proposals/<id>/test -- a READ-ONLY preview that runs
 * a sample IFC scenario against the full hypothetical condition set
 * (every live condition, with this proposal's values applied), and
 * renders EVERY condition's result, not just the proposed one -- so
 * the admin can see if the change would break something else.
 *
 * Never writes anything -- calling "Test" any number of times, on any
 * proposal, changes nothing in the database.
 */

function renderTesterResults(container, results) {
  container.innerHTML = "";
  results.forEach((r) => {
    const card = document.createElement("div");
    card.className = "proposal-tester-result";
    card.dataset.status = r.status;
    card.innerHTML = `
      <div class="proposal-tester-result__title">
        ${r.condition}
        <span class="proposal-tester-result__status">${r.status}</span>
      </div>
      <div class="proposal-tester-result__values">${r.calculated_value ?? "—"} / required ${r.required_value}</div>
      <div class="proposal-tester-result__explanation">${r.explanation}</div>
    `;
    container.appendChild(card);
  });
}

document.querySelectorAll(".proposal-tester").forEach((tester) => {
  const proposalId = tester.dataset.proposalId;
  const runBtn = tester.querySelector(".proposal-tester__run");
  const scenarioSelect = tester.querySelector(".proposal-tester__scenario");
  const toggleBtn = tester.querySelector(".proposal-tester__toggle");
  const toggleLabel = tester.querySelector(".proposal-tester__toggle-label");
  const collapsible = tester.querySelector(".proposal-tester__collapsible");
  const resultsBox = tester.querySelector(".proposal-tester__results");
  const overallBox = tester.querySelector(".proposal-tester__overall");
  let errorBox = null;

  function showError(message) {
    if (!errorBox) {
      errorBox = document.createElement("div");
      errorBox.className = "proposal-tester__error";
      tester.appendChild(errorBox);
    }
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  toggleBtn.addEventListener("click", () => {
    const expanded = collapsible.dataset.expanded === "true";
    collapsible.dataset.expanded = expanded ? "false" : "true";
    toggleBtn.setAttribute("aria-expanded", expanded ? "false" : "true");
    toggleLabel.textContent = expanded ? "Show" : "Hide";
  });

  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    runBtn.textContent = "Testing…";
    if (errorBox) errorBox.hidden = true;

    try {
      const res = await fetch(`/admin/proposals/${proposalId}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `scenario=${encodeURIComponent(scenarioSelect.value)}`,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Test failed.");

      renderTesterResults(resultsBox, data.results);
      overallBox.textContent = `Overall: ${data.overall_result}`;
      overallBox.dataset.status = data.overall_result;

      toggleBtn.hidden = false;
      collapsible.dataset.expanded = "true";
      toggleBtn.setAttribute("aria-expanded", "true");
      toggleLabel.textContent = "Hide";
    } catch (err) {
      showError(err.message);
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "Test";
    }
  });
});


