document.querySelectorAll(".auto-submit").forEach((el) => {
  el.addEventListener("change", () => el.form.submit());
});

document.querySelectorAll(".original-toggle").forEach((button) => {
  button.addEventListener("click", () => {
    const original = button.nextElementSibling;
    const open = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", String(!open));
    button.textContent = open ? "원본 보기" : "원본 숨기기";
    if (original) {
      original.hidden = open;
    }
  });
});
