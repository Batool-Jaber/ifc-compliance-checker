/**
 * admin-modal.js
 * ===============
 * ONE reusable confirmation modal for the entire admin section --
 * styled with the project's own design tokens instead of the browser's
 * native confirm(). Every confirm-before-action moment (proposing a
 * condition change, deactivating a user, approving/rejecting a
 * proposal) calls the same confirmAction() function below.
 *
 * Usage from any other admin-*.js file:
 *
 *   confirmAction({
 *     title: "Confirm Proposal",
 *     message: "Submit this change for admin approval?",
 *     confirmLabel: "Submit Proposal",
 *   }).then((confirmed) => {
 *     if (confirmed) { ... }
 *   });
 */

function buildModalDom() {
  if (document.getElementById("admin-modal-overlay")) return;

  const overlay = document.createElement("div");
  overlay.id = "admin-modal-overlay";
  overlay.className = "admin-modal-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="admin-modal" role="dialog" aria-modal="true" aria-labelledby="admin-modal-title">
      <h3 id="admin-modal-title" class="admin-modal__title"></h3>
      <p class="admin-modal__message"></p>
      <div class="admin-modal__actions">
        <button type="button" class="btn admin-modal__cancel">Cancel</button>
        <button type="button" class="btn btn--primary admin-modal__confirm"></button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
}

function confirmAction({ title, message, confirmLabel = "Confirm" }) {
  buildModalDom();

  const overlay = document.getElementById("admin-modal-overlay");
  overlay.querySelector(".admin-modal__title").textContent = title;
  overlay.querySelector(".admin-modal__message").textContent = message;
  overlay.querySelector(".admin-modal__confirm").textContent = confirmLabel;
  overlay.hidden = false;

  return new Promise((resolve) => {
    const confirmBtn = overlay.querySelector(".admin-modal__confirm");
    const cancelBtn = overlay.querySelector(".admin-modal__cancel");

    const cleanup = (result) => {
      overlay.hidden = true;
      confirmBtn.removeEventListener("click", onConfirm);
      cancelBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onOverlayClick);
      document.removeEventListener("keydown", onKeydown);
      resolve(result);
    };

    const onConfirm = () => cleanup(true);
    const onCancel = () => cleanup(false);
    const onOverlayClick = (e) => { if (e.target === overlay) cleanup(false); };
    const onKeydown = (e) => { if (e.key === "Escape") cleanup(false); };

    confirmBtn.addEventListener("click", onConfirm);
    cancelBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onOverlayClick);
    document.addEventListener("keydown", onKeydown);

    confirmBtn.focus();
  });
}