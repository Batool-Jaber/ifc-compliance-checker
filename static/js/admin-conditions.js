/**
 * admin-conditions.js
 * =====================
 * Specific to the "propose new condition" page only: toggles between
 * the Minimum/Range field sets, matching the existing .toggle-group
 * pattern already used elsewhere in the app's own app.js.
 *
 * (The generic "wire a form to the confirmation modal" logic used to
 * live in this file -- it's now in admin-forms.js, loaded globally
 * from base_admin.html, since every admin form needs it, not just
 * this page.)
 */

const typeToggle = document.getElementById("type-toggle");
if (typeToggle) {
  const typeHidden = document.getElementById("type-hidden");
  const minimumFields = document.querySelector(".type-minimum-fields");
  const rangeFields = document.querySelector(".type-range-fields");

  typeToggle.addEventListener("click", (e) => {
    const btn = e.target.closest(".toggle-opt");
    if (!btn) return;

    typeToggle.querySelectorAll(".toggle-opt").forEach((o) => (o.dataset.active = "false"));
    btn.dataset.active = "true";
    typeHidden.value = btn.dataset.value;

    const isRange = btn.dataset.value === "range";
    minimumFields.hidden = isRange;
    rangeFields.hidden = !isRange;
  });
}