/**
 * admin-forms.js
 * ===============
 * Generic: wires ANY form marked data-confirm-message to the shared
 * confirmation modal (admin-modal.js). Submit is intercepted, the
 * modal shows the message from the data attribute, and the form only
 * actually submits if the user confirms.
 *
 * Loaded once, globally, from base_admin.html -- so every current and
 * future admin form (propose edit, propose new, approve/reject a
 * proposal, deactivate a user, ...) gets this for free just by adding
 * the data-confirm-* attributes, no extra JS per page.
 */

document.querySelectorAll("form[data-confirm-message]").forEach((form) => {
  form.addEventListener("submit", (e) => {
    // Second pass, after the user already confirmed: let it through.
    if (form.dataset.confirmed === "true") {
      form.dataset.confirmed = "false";
      return;
    }

    e.preventDefault();

    confirmAction({
      title: form.dataset.confirmTitle || "Confirm",
      message: form.dataset.confirmMessage,
      confirmLabel: form.dataset.confirmLabel || "Confirm",
    }).then((confirmed) => {
      if (confirmed) {
        form.dataset.confirmed = "true";
        form.requestSubmit();
      }
    });
  });
});