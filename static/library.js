const taxonomy = document.getElementById("library-taxonomy");
const termSelect = document.getElementById("library-term");
taxonomy?.addEventListener("change", () => {
  termSelect.value = "";
  for (const option of termSelect.options) {
    if (!option.dataset.table) continue;
    option.disabled = option.hidden = option.dataset.table !== taxonomy.value;
  }
});

const selectAll = document.getElementById("library-select-all");
const selectedCount = document.getElementById("library-selected-count");
const itemBoxes = () => [...document.querySelectorAll(".library-item-select")];
const updateSelection = () => {
  const boxes = itemBoxes();
  const checked = boxes.filter((box) => box.checked).length;
  if (selectedCount) selectedCount.textContent = checked ? `${checked}개 선택됨` : "선택 없음";
  if (selectAll) {
    selectAll.checked = boxes.length > 0 && checked === boxes.length;
    selectAll.indeterminate = checked > 0 && checked < boxes.length;
  }
};
selectAll?.addEventListener("change", (event) => {
  itemBoxes().forEach((box) => { box.checked = event.target.checked; });
  updateSelection();
});
document.addEventListener("change", (event) => {
  if (event.target.classList?.contains("library-item-select")) updateSelection();
});
updateSelection();
