const state = {
  scenario: "compliant",
  ifcPath: null,
  retrievalMethod: "keyword",
  narrate: false,
  lastReport: null,
};

const $ = (id) => document.getElementById(id);

function showError(message) {
  const banner = $("error-banner");
  banner.textContent = message;
  banner.hidden = false;
}
function clearError() {
  $("error-banner").hidden = true;
}

function showToast(message, kind = "success") {
  const toast = $("status-toast");
  toast.textContent = message;
  toast.dataset.kind = kind;
  toast.hidden = false;
  toast.style.opacity = "1";

  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => { toast.hidden = true; }, 300);
  }, 3000);
}

// ---------- Model selector ----------
document.querySelectorAll(".scenario-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".scenario-btn").forEach((b) => b.dataset.active = "false");
    btn.dataset.active = "true";
    state.scenario = btn.dataset.scenario;
    state.ifcPath = null;
    $("run-btn").disabled = true;

    const isCustom = state.scenario === "custom";
    $("custom-form").hidden = !isCustom;
    $("model-status").textContent = isCustom
      ? "Set your own dimensions below, then click Generate."
      : "No model generated yet for this scenario.";

    if (isCustom) updateCustomPreview();
  });
});

// ---------- Custom form live preview ----------
const CUSTOM_FIELD_IDS = [
  "custom-room-width", "custom-room-length",
  "custom-window-width", "custom-window-height", "custom-sill-height",
];

function updateCustomPreview() {
  const w = parseFloat($("custom-room-width").value) || 0;
  const l = parseFloat($("custom-room-length").value) || 0;
  const ww = parseFloat($("custom-window-width").value) || 0;
  const wh = parseFloat($("custom-window-height").value) || 0;
  const sill = parseFloat($("custom-sill-height").value) || 0;

  const roomArea = w * l;
  const windowArea = ww * wh;
  const ratio = roomArea > 0 ? (windowArea / roomArea) * 100 : 0;

  const roomOk = roomArea >= 12;
  const ratioOk = ratio >= 10;
  const sillOk = sill >= 0.80 && sill <= 1.10;

  $("custom-preview").innerHTML = `
    <span class="${roomOk ? "tag-ok" : "tag-wrong"}">Room: ${roomArea.toFixed(2)} m²</span>
    <span class="${ratioOk ? "tag-ok" : "tag-wrong"}">Window ratio: ${ratio.toFixed(2)}%</span>
    <span class="${sillOk ? "tag-ok" : "tag-wrong"}">Sill: ${sill.toFixed(2)} m</span>
  `;
}

CUSTOM_FIELD_IDS.forEach((id) => $(id).addEventListener("input", updateCustomPreview));

$("generate-btn").addEventListener("click", async () => {
  clearError();
  $("model-status").textContent = "Generating…";

  const body = { scenario: state.scenario };

  if (state.scenario === "custom") {
    body.params = {
      room_width: parseFloat($("custom-room-width").value),
      room_length: parseFloat($("custom-room-length").value),
      window_width: parseFloat($("custom-window-width").value),
      window_height: parseFloat($("custom-window-height").value),
      sill_height: parseFloat($("custom-sill-height").value),
    };
    if (Object.values(body.params).some((v) => Number.isNaN(v))) {
      $("model-status").textContent = "Error: please fill in all custom fields with valid numbers.";
      return;
    }
  }

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Generation failed");

    state.ifcPath = data.ifc_path;
    $("model-status").textContent = `Generated: ${data.ifc_path}  (room ${data.summary.room_area_m2} m², window ${data.summary.window_area_m2} m², walls ${data.summary.wall_count})`;
    $("run-btn").disabled = false;
    showToast("✓ Model generated successfully.", "success");
  } catch (err) {
    $("model-status").textContent = `Error: ${err.message}`;
    showToast(`✗ ${err.message}`, "error");
  }
});

$("file-upload").addEventListener("change", async (e) => {
  clearError();
  const file = e.target.files[0];
  if (!file) return;

  $("upload-filename").textContent = "Uploading…";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload failed");

    state.ifcPath = data.ifc_path;
    $("upload-filename").textContent = `Loaded: ${data.filename}`;
    $("model-status").textContent = `Using uploaded file: ${data.ifc_path}`;
    $("run-btn").disabled = false;

    document.querySelectorAll(".scenario-btn").forEach((b) => b.dataset.active = "false");
    $("custom-form").hidden = true;
    showToast("✓ File uploaded successfully.", "success");
  } catch (err) {
    $("upload-filename").textContent = `Error: ${err.message}`;
    showToast(`✗ ${err.message}`, "error");
  }
});

// ---------- Options ----------
$("retrieval-toggle").addEventListener("click", (e) => {
  const opt = e.target.closest(".toggle-opt");
  if (!opt) return;
  document.querySelectorAll("#retrieval-toggle .toggle-opt").forEach((o) => o.dataset.active = "false");
  opt.dataset.active = "true";
  state.retrievalMethod = opt.dataset.value;
});

$("narrate-switch").addEventListener("change", (e) => {
  state.narrate = e.target.checked;
  $("narrate-hint").textContent = state.narrate
    ? "On — a local LLM (Ollama) will rephrase each result. This may take a few seconds."
    : "Off — results use the deterministic explanation only.";
});

// ---------- Run pipeline ----------
$("run-btn").addEventListener("click", async () => {
  if (!state.ifcPath) return;
  clearError();

  ["data-panel", "results-panel", "report-panel", "retrieval-panel", "ask-panel"].forEach((id) => $(id).hidden = true);
  $("loading-panel").hidden = false;
  $("loading-text").textContent = state.narrate
    ? "Running checks and waiting for the local LLM to narrate results…"
    : "Running compliance checks…";

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ifc_path: state.ifcPath,
        retrieval_method: state.retrievalMethod,
        narrate: state.narrate,
      }),
    });
    const report = await res.json();
    if (!res.ok) throw new Error(report.error || "Run failed");

    state.lastReport = report;
    renderReport(report);
    await loadRetrievalProcess();
    showToast("✓ Compliance check complete — results are ready below.", "success");
  } catch (err) {
    showError(`Run failed: ${err.message}`);
    showToast("✗ Run failed — see the error message above.", "error");
  } finally {
    $("loading-panel").hidden = true;
  }
});

// ---------- Rendering ----------
function renderReport(report) {
  renderExtractedData(report);
  renderConditions(report);
  renderReportTable(report);
  $("data-panel").hidden = false;
  $("results-panel").hidden = false;
  $("report-panel").hidden = false;
  $("ask-panel").hidden = false;
}

function fmt(value, unit = "") {
  return value === null || value === undefined ? "—" : `${value}${unit}`;
}

function renderExtractedData(report) {
  const room = report.room || {};
  const win = report.window || {};

  $("room-area").textContent = fmt(room.floor_area_m2, " m²");
  $("window-area").textContent = fmt(win.area_m2, " m²");
  $("sill-height").textContent = fmt(win.sill_height_m, " m");

  drawDiagram(room, win);
}

function drawDiagram(room, win) {
  const svg = $("diagram");
  const w = room.width_m || 0;
  const l = room.length_m || 0;
  const winW = win.width_m || 0;
  const winH = win.height_m || 0;
  const sill = win.sill_height_m;

  const scale = w > 0 ? 160 / Math.max(w, l) : 20;
  const planW = w * scale, planL = l * scale;
  const wallH = 90, wallW = 200;

  svg.innerHTML = `
    <text x="10" y="16" class="mono" font-size="9" fill="#8B8378">FLOOR PLAN</text>
    <rect x="20" y="30" width="${planW}" height="${planL}" fill="none" stroke="#2B5D8C" stroke-width="2"/>
    <text x="${20 + planW/2}" y="${30 + planL + 16}" text-anchor="middle" class="mono" font-size="10" fill="#1A2B3C">${w} m</text>
    <text x="${20 - 8}" y="${30 + planL/2}" text-anchor="middle" class="mono" font-size="10" fill="#1A2B3C" transform="rotate(-90 ${20-8} ${30+planL/2})">${l} m</text>

    <text x="250" y="16" class="mono" font-size="9" fill="#8B8378">WINDOW WALL ELEVATION</text>
    <rect x="250" y="30" width="${wallW}" height="${wallH}" fill="none" stroke="#8B8378" stroke-width="1.5"/>
    <line x1="250" y1="120" x2="450" y2="120" stroke="#1A2B3C" stroke-width="2"/>
    ${sill !== null && sill !== undefined ? `
      <rect x="${250 + wallW/2 - (winW*30)/2}" y="${120 - (sill*30) - (winH*30)}" width="${winW*30}" height="${winH*30}" fill="#E7EEF4" stroke="#2B5D8C" stroke-width="2"/>
      <line x1="235" y1="120" x2="235" y2="${120 - sill*30}" stroke="#B33A3A" stroke-width="1" stroke-dasharray="3,2"/>
      <text x="228" y="${120 - (sill*30)/2}" text-anchor="end" class="mono" font-size="9" fill="#B33A3A">${sill} m</text>
    ` : `
      <text x="350" y="80" text-anchor="middle" class="mono" font-size="11" fill="#B33A3A">sill height: N/A</text>
    `}
    <text x="350" y="230" text-anchor="middle" class="mono" font-size="10" fill="#1A2B3C">${winW} × ${winH} m</text>
  `;
}

function renderConditions(report) {
  const container = $("condition-cards");
  container.innerHTML = "";

  (report.conditions || []).forEach((c) => {
    const card = document.createElement("div");
    card.className = "condition-card";
    card.dataset.status = c.status;

    card.innerHTML = `
      <span class="badge" data-status="${c.status}">${c.status}</span>
      <h3>${c.condition}</h3>
      <div class="values mono">${fmt(c.calculated_value)} &nbsp;/&nbsp; required ${fmt(c.required_value)}</div>
      <div class="text-block">
        <span class="text-block__label">Explanation (deterministic)</span>
        ${c.explanation || "—"}
      </div>
      ${c.narration ? `
        <div class="text-block">
          <span class="text-block__label">Narration (local LLM)</span>
          ${c.narration}
        </div>` : ""}
    `;
    container.appendChild(card);
  });

  const overall = $("overall-badge");
  overall.dataset.status = report.overall_result;
  overall.textContent = `OVERALL RESULT: ${report.overall_result}`;
}

function renderReportTable(report) {
  const table = $("report-table");
  const rows = (report.conditions || []).map((c) => `
    <tr>
      <td>${c.condition}</td>
      <td>${c.status}</td>
      <td class="mono">${fmt(c.calculated_value)}</td>
      <td class="mono">${fmt(c.required_value)}</td>
      <td>${c.rule_source || "—"}</td>
    </tr>
  `).join("");

  table.innerHTML = `
    <thead><tr><th>Condition</th><th>Status</th><th>Calculated</th><th>Required</th><th>Rule Source</th></tr></thead>
    <tbody>${rows}</tbody>
  `;
  $("report-json").textContent = JSON.stringify(report, null, 2);
}

$("report-view-toggle").addEventListener("click", (e) => {
  const opt = e.target.closest(".toggle-opt");
  if (!opt) return;
  document.querySelectorAll("#report-view-toggle .toggle-opt").forEach((o) => o.dataset.active = "false");
  opt.dataset.active = "true";

  const isJson = opt.dataset.value === "json";
  $("report-table").hidden = isJson;
  $("report-json").hidden = !isJson;
});

// ---------- Print & CSV export ----------
$("print-btn").addEventListener("click", () => window.print());

$("export-csv-btn").addEventListener("click", () => {
  if (!state.lastReport) return;
  const conditions = state.lastReport.conditions || [];

  const header = ["Condition", "Status", "Calculated", "Required", "Rule Source", "Explanation"];
  const rows = conditions.map((c) => [
    c.condition, c.status, c.calculated_value, c.required_value, c.rule_source || "", c.explanation || "",
  ]);

  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "compliance_report.csv";
  a.click();
  URL.revokeObjectURL(url);
});

// ---------- Retrieval Process panel ----------
async function loadRetrievalProcess() {
  try {
    const res = await fetch("/api/retrieval-process");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load retrieval process");

    $("active-method-label").textContent = state.retrievalMethod;
    renderRetrievalCards(data.conditions);
    renderRetrievalCompareTable(data.conditions);
    $("retrieval-panel").hidden = false;
  } catch (err) {
    console.warn("Retrieval process unavailable:", err.message);
  }
}

function renderRetrievalCards(conditions) {
  const container = $("retrieval-cards");
  container.innerHTML = conditions.map((c) => {
    const active = c[state.retrievalMethod];
    const detail = state.retrievalMethod === "keyword"
      ? `Matched keywords: <strong>${active.matched_keywords.join(", ") || "none"}</strong> &nbsp;(score ${active.score})`
      : `Similarity score: <strong>${active.score.toFixed(4)}</strong>`;

    return `
      <div class="retrieval-card">
        <div class="retrieval-card__query mono">"${c.query}"</div>
        <div class="retrieval-card__rule">&rarr; ${active.matched_rule || "no match"}</div>
        <div class="retrieval-card__detail">${detail}</div>
      </div>
    `;
  }).join("");
}

function renderRetrievalCompareTable(conditions) {
  const rows = conditions.map((c) => `
    <tr>
      <td>${c.condition}</td>
      <td class="mono">${c.keyword.matched_keywords.join(", ") || "—"} (score ${c.keyword.score})</td>
      <td class="mono">${c.embeddings.score.toFixed(4)}</td>
    </tr>
  `).join("");

  $("retrieval-compare-table").innerHTML = `
    <thead><tr><th>Condition</th><th>Keyword match (score)</th><th>Embeddings score</th></tr></thead>
    <tbody>${rows}</tbody>
  `;
}

// ---------- RAG comparison (optional panel) ----------
$("compare-btn").addEventListener("click", async () => {
  $("compare-result").innerHTML = `<p class="mono" style="color:#8B8378;font-size:0.8rem;">Running comparison…</p>`;
  try {
    const res = await fetch("/api/compare");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Comparison failed");

    const rows = data.rows.map((r) => `
      <tr>
        <td>${r.difficulty}</td>
        <td>${r.query}</td>
        <td class="${r.keyword_correct ? "tag-ok" : "tag-wrong"}">${r.keyword_correct ? "OK" : "WRONG"}</td>
        <td class="${r.embedding_correct ? "tag-ok" : "tag-wrong"}">${r.embedding_correct ? "OK" : "WRONG"}</td>
      </tr>
    `).join("");

    $("compare-result").innerHTML = `
      <table class="compare-table">
        <thead><tr><th>Difficulty</th><th>Query</th><th>Keyword</th><th>Embeddings</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="compare-summary">
        <div class="figure"><span class="figure__label">Keyword accuracy</span><span class="figure__value mono">${Math.round(data.keyword_accuracy*100)}%</span></div>
        <div class="figure"><span class="figure__label">Embeddings accuracy</span><span class="figure__value mono">${Math.round(data.embedding_accuracy*100)}%</span></div>
      </div>
    `;
  } catch (err) {
    $("compare-result").innerHTML = `<p style="color:#B33A3A;">Error: ${err.message}</p>`;
  }
});

// ---------- Ask about report ----------
$("ask-btn").addEventListener("click", async () => {
  const question = $("ask-input").value.trim();
  if (!question || !state.lastReport) return;

  const answerBox = $("ask-answer");
  answerBox.hidden = false;
  answerBox.textContent = "Thinking… (waiting for the local LLM)";

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report: state.lastReport, question }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to get an answer");
    answerBox.textContent = data.answer;
  } catch (err) {
    answerBox.textContent = `Error: ${err.message}`;
  }
});