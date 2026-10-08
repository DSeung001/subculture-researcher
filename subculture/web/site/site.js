// Read-only list for the static site: data.json already holds every card field
// (presentation.card_view runs at build time), so this only filters, sorts and renders.
const PAGE_SIZE = 30;
const UNCLASSIFIED = "__NONE__";
const state = { q: "", work: "ALL", category: "ALL", days: "ALL", sort: "RECOMMENDED", source: "ALL" };
let allItems = [];
let categoryLabels = {};
let matched = [];
let shown = 0;

const escapeHtml = (value) => String(value ?? "").replace(
  /[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch],
);

const datePrefix = (date) => (
  date ? `<span class="card-date">게시 ${escapeHtml(date)}</span><span class="card-date-sep" aria-hidden="true">|</span>` : ""
);

// Same markup as templates/_item_card.html (no select/actions slots on the read-only site).
function cardHtml(item) {
  const v = item.view;
  const thumb = v.image_url
    ? `<a class="card-thumb" href="${escapeHtml(v.url || v.image_url)}" target="_blank" rel="noopener" tabindex="-1" aria-hidden="true"><img class="card-thumb-img" src="${escapeHtml(v.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer"></a>`
    : `<div class="card-thumb card-thumb-empty" aria-hidden="true"><span>${escapeHtml(v.category_label)}</span></div>`;
  const details = v.detail_image_urls.length
    ? `<div class="card-detail-thumbs" title="상세 이미지 ${v.detail_image_urls.length}장" aria-hidden="true">${
      v.detail_image_urls.slice(0, 6).map((img) => `<a class="card-detail-thumb" href="${escapeHtml(img)}" target="_blank" rel="noopener" tabindex="-1"><img src="${escapeHtml(img)}" alt="" loading="lazy" referrerpolicy="no-referrer"></a>`).join("")
    }${v.detail_image_urls.length > 6 ? `<span class="card-detail-thumb-more">+${v.detail_image_urls.length - 6}</span>` : ""}</div>`
    : "";
  const original = v.original_title
    ? `<span class="title-variant title-original" hidden>${datePrefix(v.original_date)}<strong>${escapeHtml(v.original_text)}</strong></span><button type="button" class="original-toggle" aria-pressed="false">원어 제목</button>`
    : "";
  const reasons = v.score_breakdown.length
    ? `<span class="card-score-reasons" title="점수 근거">${v.score_breakdown.map(([label, points]) => ` · ${escapeHtml(label)} +${escapeHtml(points)}`).join("")}</span>`
    : "";
  const works = item.works.length
    ? `<p class="card-flags">${item.works.map((name) => `<span class="tag">${escapeHtml(name)}</span>`).join(" ")}</p>`
    : "";
  return `<article class="card item-card">
  <div class="card-row">
    <div class="card-thumb-col">${thumb}${details}</div>
    <div class="card-main">
      <p class="card-title">${v.is_new_today ? '<span class="new-badge" title="오늘 수집">N</span>' : ""}<span class="title-variant title-translated">${datePrefix(v.title_date)}${v.lang_tag ? `<span class="lang-tag">[${escapeHtml(v.lang_tag)}]</span>` : ""}<strong>${escapeHtml(v.title_text)}</strong></span>${original}${v.url ? `<a class="original-toggle" href="${escapeHtml(v.url)}" target="_blank" rel="noopener">자세히보기</a>` : ""}</p>
      <div class="card-meta-row">
        <p class="card-meta"><strong>추천 ${escapeHtml(v.signal_score)}</strong>${v.signal_labels.map((label) => ` · ${escapeHtml(label)}`).join("")}${reasons} · ${escapeHtml(v.meta)}</p>
      </div>
      ${works}
      ${v.product_caption ? `<p class="card-summary"><strong>${escapeHtml(v.product_caption)}</strong></p>` : ""}
      ${v.summary ? `<p class="card-summary">${escapeHtml(v.summary)}</p>` : ""}
    </div>
  </div>
</article>`;
}

function applyFilters() {
  const query = state.q.trim().toLowerCase();
  const cutoff = state.days === "ALL" ? 0 : Date.now() - Number(state.days) * 86400000;
  matched = allItems.filter((item) => {
    if (state.work === UNCLASSIFIED ? item.works.length : state.work !== "ALL" && !item.works.includes(state.work)) return false;
    if (state.category !== "ALL" && item.category !== state.category) return false;
    if (state.source !== "ALL" && item.source !== state.source) return false;
    if (cutoff && item._collected < cutoff) return false;
    return !query || item._text.includes(query);
  });
  // Same order rules as presentation.sort_items.
  if (state.sort === "RECOMMENDED") {
    matched.sort((a, b) => b.view.signal_score - a.view.signal_score || b._date - a._date);
  } else {
    matched.sort((a, b) => (state.sort === "NEWEST" ? b._date - a._date : a._date - b._date));
  }
  shown = 0;
  document.getElementById("item-list").innerHTML = "";
  renderMore();
}

function renderMore() {
  const next = matched.slice(shown, shown + PAGE_SIZE);
  document.getElementById("item-list").insertAdjacentHTML("beforeend", next.map(cardHtml).join(""));
  shown += next.length;
  const remaining = matched.length - shown;
  document.getElementById("more").hidden = remaining <= 0;
  document.getElementById("more-button").textContent = `더 보기 (+${Math.min(PAGE_SIZE, remaining)}개)`;
  document.getElementById("site-count").textContent = matched.length
    ? `${matched.length}개 중 ${shown}개 표시`
    : "조건에 맞는 항목이 없습니다.";
}

function bindChips(id, key) {
  const row = document.getElementById(id);
  const sync = () => row.querySelectorAll(".chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.value === state[key]);
  });
  row.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) return;
    event.preventDefault();
    state[key] = chip.dataset.value;
    sync();
    applyFilters();
  });
  sync();
}

function countBy(values) {
  const counts = new Map();
  values.forEach((value) => counts.set(value, (counts.get(value) || 0) + 1));
  return counts;
}

function fillSelect(id, key, options) {
  const select = document.getElementById(id);
  select.innerHTML = options.map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join("");
  select.addEventListener("change", () => {
    state[key] = select.value;
    applyFilters();
  });
}

async function start() {
  const status = document.getElementById("site-status");
  let data;
  try {
    // Revalidate each visit: the file is rebuilt after every collection run.
    const response = await fetch("data.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(String(response.status));
    data = await response.json();
  } catch (error) {
    status.textContent = "목록을 불러오지 못했습니다. 잠시 후 새로고침해주세요.";
    return;
  }
  categoryLabels = data.categoryLabels;
  allItems = data.items;
  allItems.forEach((item) => {
    item._date = Date.parse(item.date) || 0;
    item._collected = Date.parse(item.collected) || 0;
    item._text = [item.view.title_text, item.view.original_title, item.source, ...item.works].join(" ").toLowerCase();
  });

  const built = data.builtAt ? new Date(data.builtAt).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }) : "";
  status.innerHTML = `보기 전용 · ${escapeHtml(built)} 기준 · <span id="site-count"></span>`;

  const workCounts = [...countBy(allItems.flatMap((item) => item.works))].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko"));
  const unclassified = allItems.filter((item) => !item.works.length).length;
  fillSelect("filter-work", "work", [
    ["ALL", `전체 (${allItems.length})`],
    [UNCLASSIFIED, `작품 미분류 (${unclassified})`],
    ...workCounts.map(([name, count]) => [name, `${name} (${count})`]),
  ]);
  const sources = [...countBy(allItems.map((item) => item.source).filter(Boolean))].sort((a, b) => a[0].localeCompare(b[0], "ko"));
  fillSelect("filter-source", "source", [["ALL", "전체"], ...sources.map(([name, count]) => [name, `${name} (${count})`])]);

  const used = new Set(allItems.map((item) => item.category));
  document.getElementById("filter-category").innerHTML = [["ALL", "전체"], ...Object.entries(categoryLabels).filter(([key]) => used.has(key))]
    .map(([value, label]) => `<a href="#" class="chip" data-value="${escapeHtml(value)}">${escapeHtml(label)}</a>`).join("");
  bindChips("filter-category", "category");
  bindChips("filter-days", "days");
  bindChips("filter-sort", "sort");

  document.getElementById("filter-q").addEventListener("input", (event) => {
    state.q = event.target.value;
    applyFilters();
  });
  document.getElementById("more-button").addEventListener("click", (event) => {
    event.preventDefault();
    renderMore();
  });
  applyFilters();
}

start();
