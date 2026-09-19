const taxonomy = document.getElementById("library-taxonomy");
const termSelect = document.getElementById("library-term");
taxonomy?.addEventListener("change", () => {
  termSelect.value = "";
  for (const option of termSelect.options) {
    if (!option.dataset.table) continue;
    option.disabled = option.hidden = option.dataset.table !== taxonomy.value;
  }
});
document.getElementById("library-select-all")?.addEventListener("change", (event) => {
  document.querySelectorAll(".library-item-select").forEach((box) => { box.checked = event.target.checked; });
});
