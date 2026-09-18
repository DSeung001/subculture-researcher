document.querySelectorAll(".auto-submit").forEach((el) => {
  el.addEventListener("change", () => el.form.submit());
});

document.querySelectorAll(".original-toggle").forEach((button) => {
  button.addEventListener("click", () => {
    const titleEl = button.closest(".card-title");
    const translated = titleEl?.querySelector(".title-translated");
    const original = titleEl?.querySelector(".title-original");
    if (!translated || !original) return;

    const showingOriginal = original.hidden;
    translated.hidden = showingOriginal;
    original.hidden = !showingOriginal;
    button.setAttribute("aria-pressed", String(showingOriginal));
    button.textContent = showingOriginal ? "번역 제목" : "원어 제목";
  });
});

document.querySelectorAll("[data-dialog-target]").forEach((trigger) => {
  const dialog = document.getElementById(trigger.dataset.dialogTarget);
  if (!dialog) return;
  trigger.addEventListener("click", () => {
    dialog.showModal();
    const field = dialog.querySelector("textarea, input[type='text']");
    if (field) {
      field.focus();
      if (typeof field.selectionStart === "number") {
        field.selectionStart = field.selectionEnd = field.value.length;
      }
    }
  });
});

document.querySelectorAll("[data-dialog-close]").forEach((closeBtn) => {
  const dialog = closeBtn.closest("dialog");
  if (dialog) closeBtn.addEventListener("click", () => dialog.close());
});
