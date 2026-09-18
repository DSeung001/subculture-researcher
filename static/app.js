document.querySelectorAll(".auto-submit").forEach((el) => {
  el.addEventListener("change", () => el.form.submit());
});
