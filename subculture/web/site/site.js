// Read-only list for the static site. Card text and comparison pieces are computed at
// build time (presentation.card_view, compare_post.post_piece). This file filters, sorts,
// renders, and numbers a comparison post in the browser. Nothing is stored or sent back.
const PAGE_SIZE = 60;
const UNCLASSIFIED = "__NONE__";
const state = { q: "", work: "ALL", category: "ALL", days: "ALL", sort: "RECOMMENDED", source: "ALL" };
let allItems = [];
let compareConfig = { maxSources: 20, bodyTarget: 260, productHeader: "상품 페이지 참고 ↓", plainHeader: "링크 ↓" };
const selected = [];
const normalizeSearch = (value) => String(value).normalize("NFKC").toLowerCase().replace(/:/g, " ").replace(/\s+/g, " ").trim();
let categoryLabels = {};
let matched = [];
let shown = 0;

const escapeHtml = (value) => String(value ?? "").replace(
  /[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch],
);

const datePrefix = (date) => (
  date ? `<span class="card-date">게시 ${escapeHtml(date)}</span><span class="card-date-sep" aria-hidden="true">|</span>` : ""
);

// Same markup as templates/_item_card.html. The select slot is the comparison checkbox.
function cardHtml(item) {
  const v = item.view;
  const checked = selected.includes(item.id) ? " checked" : "";
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
    <div class="card-select"><label class="card-select-label"><input type="checkbox" class="draft-source" value="${escapeHtml(item.id)}"${checked} aria-label="비교글에 포함"></label></div>
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
  const query = normalizeSearch(state.q);
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
  if (next.length) {
    document.getElementById("item-list").insertAdjacentHTML("beforeend", next.map(cardHtml).join(""));
    shown += next.length;
  }
  document.getElementById("more").hidden = shown >= matched.length;
  const count = document.getElementById("site-count");
  if (count) {
    count.textContent = matched.length
      ? `${matched.length}개 중 ${shown}개 표시`
      : "조건에 맞는 항목이 없습니다.";
  }
}

function comparePosts(items) {
  const body = [];
  const links = [];
  items.forEach((item, index) => {
    const number = index + 1;
    const piece = item.post;
    body.push(`${number}. ${piece.name}`);
    if (piece.facts) body.push(`   ${piece.facts}`);
    if (piece.url) links.push(`${number}. ${piece.name}\n${piece.url}`);
  });
  const header = items.some((item) => item.post.product) ? compareConfig.productHeader : compareConfig.plainHeader;
  const reply = links.length ? `${[header, ...links].join("\n\n")}\n` : "";
  return { body: body.length ? `${body.join("\n")}\n` : "", reply };
}

function setupCompare() {
  const form = document.getElementById("compare-form");
  const panel = document.getElementById("compare-panel");
  const message = document.getElementById("compare-message");
  const error = document.getElementById("compare-error");
  const countEl = form.querySelector(".draft-bar-count");
  const maximum = compareConfig.maxSources;
  let revision = 0;
  const sync = () => {
    document.querySelectorAll(".draft-source").forEach((box) => { box.checked = selected.includes(box.value); });
    countEl.textContent = `${selected.length}개 선택`;
    form.hidden = selected.length === 0;
    document.body.classList.toggle("has-draft-bar", selected.length > 0);
  };
  const changed = () => {
    revision += 1;
    error.textContent = "";
    if (!panel.hidden) message.textContent = "선택이 변경되었습니다. 비교글을 다시 생성해주세요. 편집 내용은 유지됩니다.";
    sync();
  };
  document.addEventListener("change", (event) => {
    if (!event.target.matches(".draft-source")) return;
    const id = event.target.value;
    const index = selected.indexOf(id);
    if (event.target.checked) {
      if (index === -1 && selected.length >= maximum) {
        event.target.checked = false;
        error.textContent = `비교글 재료는 ${maximum}개까지입니다.`;
        sync();
        return;
      }
      if (index === -1) selected.push(id);
    } else if (index !== -1) {
      selected.splice(index, 1);
    }
    changed();
  });
  document.getElementById("compare-clear").addEventListener("click", () => { selected.splice(0, selected.length); changed(); });
  document.getElementById("compare-close").addEventListener("click", () => { panel.hidden = true; });
  new MutationObserver(sync).observe(document.getElementById("item-list"), { childList: true });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!selected.length) return;
    const items = selected.map((id) => allItems.find((item) => item.id === id)).filter(Boolean);
    const posts = comparePosts(items);
    const body = document.getElementById("post-body");
    const reply = document.getElementById("post-reply");
    body.value = posts.body;
    reply.value = posts.reply;
    panel.querySelector('[data-count-for="post-body"]').dataset.limit = compareConfig.bodyTarget;
    body.dispatchEvent(new Event("input", { bubbles: true }));
    reply.dispatchEvent(new Event("input", { bubbles: true }));
    message.textContent = `${items.length}개 항목 · 이 화면에서만 표시됩니다. 새로고침하면 초기화됩니다.`;
    panel.hidden = false;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    body.focus({ preventScroll: true });
    error.textContent = "";
  });
  sync();
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

function searchMenu(key, options) {
  const container = document.getElementById(`filter-${key}`);
  const input = document.getElementById(`search-${key}`);
  const selected = document.getElementById(`selected-${key}`);
  const render = () => {
    const query = normalizeSearch(input.value);
    const candidates = options.filter((option) => option.value === "ALL" || option.value === UNCLASSIFIED ||
      normalizeSearch([option.label, ...(option.aliases || [])].join(" ")).includes(query));
    container.innerHTML = candidates.map((option) => `<button type="button" class="chip" data-value="${escapeHtml(option.value)}" aria-pressed="${state[key] === option.value}">${escapeHtml(option.label)}</button>`).join("") +
      (query && !candidates.some((option) => option.value !== "ALL" && option.value !== UNCLASSIFIED) ? '<p role="status">검색 결과가 없습니다.</p>' : "");
    selected.textContent = `선택: ${options.find((option) => option.value === state[key])?.label || "전체"}`;
  };
  input.addEventListener("input", render);
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") { event.preventDefault(); container.querySelector('button[data-value]:not([data-value="ALL"]):not([data-value="__NONE__"])')?.focus(); }
    if (event.key === "Escape") { input.value = ""; render(); }
  });
  container.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    state[key] = button.dataset.value;
    render();
    [...container.querySelectorAll("button")].find((candidate) => candidate.dataset.value === state[key])?.focus();
    applyFilters();
  });
  render();
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
  compareConfig = data.compare;
  allItems = data.items;
  const aliases = new Map((data.works || []).map((work) => [work.name, work.aliases]));
  allItems.forEach((item) => {
    item._date = Date.parse(item.date) || 0;
    item._collected = Date.parse(item.collected) || 0;
    item._text = normalizeSearch([item.view.title_text, item.view.original_title, item.source, ...item.works, ...item.works.flatMap((name) => aliases.get(name) || [])].join(" "));
  });

  const built = data.builtAt ? new Date(data.builtAt).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }) : "";
  status.innerHTML = `${escapeHtml(built)} 기준 · <span id="site-count"></span>`;

  const workCounts = [...countBy(allItems.flatMap((item) => item.works))].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko"));
  const unclassified = allItems.filter((item) => !item.works.length).length;
  searchMenu("work", [
    { value: "ALL", label: `전체 · 선택 해제 (${allItems.length})` },
    { value: UNCLASSIFIED, label: `작품 미분류 (${unclassified})` },
    ...workCounts.map(([name, count]) => ({ value: name, label: `${name} (${count})`, aliases: aliases.get(name) || [] })),
  ]);
  const sources = [...countBy(allItems.map((item) => item.source).filter(Boolean))].sort((a, b) => a[0].localeCompare(b[0], "ko"));
  searchMenu("source", [{ value: "ALL", label: `전체 · 선택 해제 (${allItems.length})` }, ...sources.map(([name, count]) => ({ value: name, label: `${name} (${count})` }))]);

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
  const moreEl = document.getElementById("more");
  new IntersectionObserver((entries) => {
    if (shown < matched.length && entries.some((entry) => entry.isIntersecting)) renderMore();
  }, { rootMargin: "600px 0px" }).observe(moreEl);
  setupCompare();
  applyFilters();
}

start();
