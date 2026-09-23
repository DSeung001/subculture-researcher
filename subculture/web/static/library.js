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

// Image export popup: starts a background job, then polls its progress.
const exportForm = document.getElementById("image-export-form");
const exportEl = (id) => document.getElementById(`image-export-${id}`);
const EXPORT_JOB_KEY = "library-image-export-job";
let exportTimer = null;

const updateExportSelection = (checked) => {
  const radio = exportEl("selected");
  if (!radio) return;
  exportEl("selected-label").textContent = `선택한 항목 (${checked}개)`;
  radio.disabled = checked === 0;
  if (radio.disabled && radio.checked) exportForm.querySelector('input[name="scope"][value="filter"]').checked = true;
};

const rememberJob = (jobId) => {
  try {
    if (jobId) sessionStorage.setItem(EXPORT_JOB_KEY, jobId);
    else sessionStorage.removeItem(EXPORT_JOB_KEY);
  } catch { /* storage unavailable: resuming after reload just won't work */ }
};
const storedJob = () => {
  try { return sessionStorage.getItem(EXPORT_JOB_KEY); } catch { return null; }
};

const formatBytes = (bytes) => (bytes >= 1024 * 1024
  ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
  : `${Math.round(bytes / 1024)} KB`);

const setExportRunning = (running) => {
  exportForm.querySelectorAll("fieldset").forEach((set) => { set.disabled = running; });
  exportEl("start").hidden = running;
  exportEl("cancel").hidden = !running;
};

const showExportError = (message) => {
  const box = exportEl("error");
  box.textContent = message || "";
  box.hidden = !message;
};

const renderExport = (job) => {
  const p = job.progress;
  exportEl("status").hidden = false;
  exportEl("progress").max = Math.max(1, p.items_total);
  exportEl("progress").value = p.items_done;
  exportEl("summary").textContent =
    `${p.items_done} / ${p.items_total} 항목 · 새로 받음 ${p.files_ok} · 건너뜀 ${p.files_skipped} · 실패 ${p.files_error} · ${formatBytes(p.bytes)}`;
  const outcome = {
    running: "진행 중…",
    done: p.stop_reason === "size_limit" ? "총용량 상한에 도달해 멈췄습니다." : "완료했습니다.",
    cancelled: "취소했습니다. 그때까지 받은 이미지는 저장됐습니다.",
    failed: `실패: ${job.error || "알 수 없는 오류"}`,
  }[job.state];
  exportEl("result").textContent = job.directory ? `${outcome} 저장 위치: ${job.directory}` : outcome;
  setExportRunning(job.state === "running");
};

const exportUrl = (kind, jobId) => exportForm.dataset[`${kind}Url`].replace("__JOB__", jobId);

const pollExport = async (jobId) => {
  clearTimeout(exportTimer);
  try {
    const response = await fetch(exportUrl("status", jobId));
    if (response.status === 404) { rememberJob(null); setExportRunning(false); return; }
    const job = await response.json();
    renderExport(job);
    if (job.state === "running") exportTimer = setTimeout(() => pollExport(jobId), 1000);
  } catch {
    exportTimer = setTimeout(() => pollExport(jobId), 3000);
  }
};

exportForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  showExportError("");
  const data = new FormData(exportForm);
  if (data.get("scope") === "selected") {
    itemBoxes().filter((box) => box.checked).forEach((box) => data.append("item_ids", box.value));
  }
  setExportRunning(true);
  try {
    const response = await fetch(exportForm.dataset.startUrl, { method: "POST", body: data });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "내보내기를 시작하지 못했습니다.");
    rememberJob(job.id);
    renderExport(job);
    pollExport(job.id);
  } catch (error) {
    setExportRunning(false);
    showExportError(error.message);
  }
});

exportEl("cancel")?.addEventListener("click", async () => {
  const jobId = storedJob();
  if (!jobId) return;
  await fetch(exportUrl("cancel", jobId), { method: "POST" }).catch(() => {});
  pollExport(jobId);
});

if (exportForm && storedJob()) pollExport(storedJob());

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
  updateExportSelection(checked);
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
