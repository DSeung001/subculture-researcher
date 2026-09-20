const taxonomy = document.getElementById("library-taxonomy");
const termSelect = document.getElementById("library-term");
taxonomy?.addEventListener("change", () => {
  termSelect.value = "";
  for (const option of termSelect.options) {
    if (!option.dataset.table) continue;
    option.disabled = option.hidden = option.dataset.table !== taxonomy.value;
  }
});

const workSearch = document.getElementById("work-search");
const workSearchEmpty = document.getElementById("work-search-empty");
const workRows = () => [...document.querySelectorAll(".work-row")];
const normalizeSearch = (value) => value.toLowerCase().replace(/\s+/g, "");
const filterWorks = () => {
  if (!workSearch) return;
  const query = normalizeSearch(workSearch.value);
  let visible = 0;
  for (const row of workRows()) {
    const match = !query || normalizeSearch(row.dataset.search || "").includes(query);
    row.hidden = !match;
    if (match) visible += 1;
  }
  if (workSearchEmpty) workSearchEmpty.hidden = !query || visible > 0;
};
workSearch?.addEventListener("input", filterWorks);
workSearch?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") event.preventDefault();
});

const selectAll = document.getElementById("library-select-all");
const selectedCount = document.getElementById("library-selected-count");
const itemBoxes = () => [...document.querySelectorAll(".library-item-select")];
// Bottom bar that turns the selection into a draft (limit mirrors drafts.domain.rules.MAX_SOURCES).
const draftBar = document.getElementById("library-draft-bar");
const draftCount = draftBar?.querySelector(".draft-bar-count");
const draftMax = Number(draftCount?.dataset.max) || 20;
const updateDraftBar = (checked) => {
  if (!draftBar) return;
  const over = checked > draftMax;
  draftBar.hidden = checked === 0;
  document.body.classList.toggle("has-draft-bar", checked > 0);
  draftCount.textContent = over ? `${checked}개 선택 · 글 하나에 ${draftMax}개까지` : `${checked}개 선택`;
  draftCount.classList.toggle("is-over", over);
  draftBar.querySelectorAll("button").forEach((button) => { button.disabled = over; });
};

const updateSelection = () => {
  const boxes = itemBoxes();
  const checked = boxes.filter((box) => box.checked).length;
  if (selectedCount) selectedCount.textContent = checked ? `${checked}개 선택됨` : "선택 없음";
  updateDraftBar(checked);
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
