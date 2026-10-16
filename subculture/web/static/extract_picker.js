(() => {
  const root = document.getElementById("extract-root");
  if (!root) return;

  const previewUrl = root.dataset.previewUrl;
  const sampleUrl = root.dataset.sampleUrl;
  const saveUrl = root.dataset.saveUrl;
  const listUrl = root.dataset.listUrl;

  const frame = document.getElementById("extract-frame");
  const statusEl = document.getElementById("preview-status");
  const pickBanner = document.getElementById("pick-banner");
  const pickEmpty = document.getElementById("pick-empty");
  const pickSelector = document.getElementById("pick-selector");
  const pickText = document.getElementById("pick-text");
  const itemInput = document.getElementById("field-item");
  const listFieldsEl = document.getElementById("list-fields");
  const detailFieldsEl = document.getElementById("detail-fields");
  const sampleWrap = document.getElementById("sample-wrap");
  const sampleTable = document.getElementById("sample-table").querySelector("tbody");
  const saveStatus = document.getElementById("save-status");

  const LIST_FIELDS = [
    { key: "link", label: "링크", parse: "text", attrHint: "href",
      help: "필수. 카드 안에서 상품 상세 페이지로 가는 <a>. 상품 이미지나 이름을 감싼 링크를 고르세요. attr은 href." },
    { key: "title", label: "제목", parse: "text",
      help: "필수. 상품명 글자가 들어 있는 요소. 브랜드·카테고리 라벨이 아닌 상품 이름 자체를 고르세요." },
    { key: "price", label: "가격", parse: "krw",
      help: "판매가가 적힌 요소. krw가 \"12,000원\"에서 숫자만 뽑습니다. 정가와 할인가가 함께 있으면 실제 판매가 쪽만 고르세요." },
    { key: "image", label: "대표 사진", parse: "text", attrHint: "src",
      help: "카드의 썸네일 <img>. attr은 src. 지연 로딩이라 src가 빈 그림이면 data-src나 data-original을 넣으세요." },
    { key: "status", label: "판매 상태", parse: "sale_status",
      help: "\"예약\", \"품절\" 같은 배지나 글자. 품절 → SOLD_OUT, 예약 → PREORDER, 그 외 → IN_STOCK. 배지가 이미지면 attr을 alt로." },
    { key: "deadline", label: "예약 마감", parse: "date",
      help: "예약 주문 마감일이 적힌 요소. date가 날짜를 읽습니다. 목록에 없으면 비워 두고 상세에서 채우세요." },
    { key: "published", label: "게시일", parse: "date",
      help: "상품 등록일이나 글 게시일. 최신순 정렬과 신규 판별에 씁니다. 없으면 비워 두세요." },
  ];
  const DETAIL_FIELDS = [
    { key: "gallery", label: "상세 갤러리", parse: "text", attrHint: "src", many: true,
      help: "상세 페이지의 상품 사진들. 셀렉터에 걸리는 이미지를 모두 모읍니다. 사진 하나를 고른 뒤 nth-of-type 부분을 지워 여러 장이 걸리게 하세요." },
    { key: "price", label: "가격", parse: "krw",
      help: "상세 페이지의 판매가. 값이 있으면 목록에서 읽은 가격보다 우선합니다." },
    { key: "status", label: "판매 상태", parse: "sale_status",
      help: "상세 페이지의 예약/품절 표시. 값이 있으면 목록 값보다 우선합니다." },
    { key: "deadline", label: "예약 마감", parse: "date",
      help: "상세 페이지에만 있는 예약 마감일. 값이 있으면 목록 값보다 우선합니다." },
    { key: "image", label: "대표 사진", parse: "text", attrHint: "src",
      help: "상세 페이지의 큰 대표 사진. 찾으면 목록 썸네일 대신 이 사진을 씁니다." },
    { key: "title", label: "제목", parse: "text",
      help: "목록에서 제목을 못 읽었을 때만 상세 페이지 제목으로 채웁니다." },
  ];

  let state = {
    item: "",
    list: {},
    detail: {},
  };
  let lastPick = null;
  let previewKind = "list";
  let detailSampleUrl = "";

  function parseInitial() {
    try {
      const raw = JSON.parse(root.dataset.initialExtract || "{}");
      state.item = (raw.list && raw.list.item) || "";
      const listFields = (raw.list && raw.list.fields) || {};
      const detailFields = (raw.detail && raw.detail.fields) || {};
      for (const f of LIST_FIELDS) {
        state.list[f.key] = listFields[f.key]
          ? { ...listFields[f.key] }
          : { selector: "", parse: f.parse, attr: f.attrHint || null, many: false };
      }
      for (const f of DETAIL_FIELDS) {
        state.detail[f.key] = detailFields[f.key]
          ? { ...detailFields[f.key] }
          : { selector: "", parse: f.parse, attr: f.attrHint || null, many: !!f.many };
      }
    } catch (_err) {
      for (const f of LIST_FIELDS) {
        state.list[f.key] = { selector: "", parse: f.parse, attr: f.attrHint || null, many: false };
      }
      for (const f of DETAIL_FIELDS) {
        state.detail[f.key] = { selector: "", parse: f.parse, attr: f.attrHint || null, many: !!f.many };
      }
    }
    itemInput.value = state.item;
  }

  function fieldRow(section, def) {
    const bag = section === "list" ? state.list : state.detail;
    const current = bag[def.key] || { selector: "", parse: def.parse, attr: def.attrHint || null };
    const wrap = document.createElement("div");
    wrap.className = "field-map-row" + (current.selector ? " is-set" : "");
    wrap.dataset.section = section;
    wrap.dataset.key = def.key;
    wrap.innerHTML = `
      <div class="field-map-head">
        <span class="field-map-label">${def.label}
          <button type="button" class="help-tip" data-help-for="help-${section}-${def.key}"
            aria-label="${def.label} 설명" aria-describedby="help-${section}-${def.key}">?</button>
        </span>
        <button type="button" class="btn btn-sm field-pick" data-section="${section}" data-key="${def.key}"
          ${lastPick ? "" : "disabled"} title="선택한 요소를 이 필드에 넣기">넣기</button>
      </div>
      <input type="text" aria-label="${def.label} 셀렉터" data-section="${section}" data-key="${def.key}" data-role="selector"
        value="${escapeAttr(current.selector || "")}" placeholder="${def.attrHint ? def.attrHint + " 속성 셀렉터" : "CSS 셀렉터"}">
      <p class="field-help" id="help-${section}-${def.key}" hidden>${escapeAttr(def.help)}</p>
      <div class="field-map-opts">
        <label>parse
          <select data-section="${section}" data-key="${def.key}" data-role="parse">
            ${["text", "krw", "sale_status", "date"].map((p) =>
              `<option value="${p}" ${ (current.parse || def.parse) === p ? "selected" : "" }>${p}</option>`
            ).join("")}
          </select>
        </label>
        <label>attr
          <input type="text" data-section="${section}" data-key="${def.key}" data-role="attr"
            value="${escapeAttr(current.attr || "")}" placeholder="없음">
        </label>
      </div>
    `;
    return wrap;
  }

  function escapeAttr(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function renderFields() {
    listFieldsEl.innerHTML = "";
    detailFieldsEl.innerHTML = "";
    LIST_FIELDS.forEach((def) => listFieldsEl.appendChild(fieldRow("list", def)));
    DETAIL_FIELDS.forEach((def) => detailFieldsEl.appendChild(fieldRow("detail", def)));
  }

  function syncStateFromInputs() {
    state.item = itemInput.value.trim();
    root.querySelectorAll("[data-role]").forEach((input) => {
      const section = input.dataset.section;
      const key = input.dataset.key;
      const role = input.dataset.role;
      const bag = section === "list" ? state.list : state.detail;
      if (!bag[key]) bag[key] = { selector: "", parse: "text", attr: null, many: key === "gallery" };
      if (role === "selector") bag[key].selector = input.value.trim();
      if (role === "parse") bag[key].parse = input.value;
      if (role === "attr") bag[key].attr = input.value.trim() || null;
    });
  }

  function buildExtract() {
    syncStateFromInputs();
    const listFields = {};
    for (const [key, spec] of Object.entries(state.list)) {
      if (!spec.selector) continue;
      listFields[key] = {
        selector: spec.selector,
        parse: spec.parse || "text",
      };
      if (spec.attr) listFields[key].attr = spec.attr;
    }
    const detailFields = {};
    for (const [key, spec] of Object.entries(state.detail)) {
      if (!spec.selector) continue;
      detailFields[key] = {
        selector: spec.selector,
        parse: spec.parse || "text",
      };
      if (spec.attr) detailFields[key].attr = spec.attr;
      if (key === "gallery") detailFields[key].many = true;
    }
    const extract = {
      list: {
        item: state.item,
        fields: listFields,
      },
    };
    if (Object.keys(detailFields).length) {
      extract.detail = { fields: detailFields };
    }
    return extract;
  }

  function relativeToItem(absoluteSelector) {
    const item = itemInput.value.trim();
    if (!item || !absoluteSelector) return absoluteSelector;
    // Prefer a short path when the absolute selector contains the item root.
    const marker = item + " > ";
    const idx = absoluteSelector.indexOf(marker);
    if (idx !== -1) {
      return absoluteSelector.slice(idx + marker.length);
    }
    // Fallback: last path segment(s) after a matching tag chain is too brittle; keep absolute.
    return absoluteSelector;
  }

  function loadPreview() {
    const url = new URL(previewUrl, window.location.origin);
    if (previewKind === "detail") {
      if (!detailSampleUrl) {
        statusEl.textContent = "샘플 추출로 상품 URL을 먼저 확인하세요.";
        frame.removeAttribute("src");
        return;
      }
      url.searchParams.set("url", detailSampleUrl);
    }
    statusEl.textContent = "불러오는 중…";
    frame.src = url.toString();
  }

  // The preview runs in an opaque-origin sandbox, so talk to it only through postMessage.
  function sendItemRoot(selector) {
    if (frame.contentWindow) {
      frame.contentWindow.postMessage({ type: "extract-set-item", selector: selector || "" }, "*");
    }
  }

  frame.addEventListener("load", () => {
    statusEl.textContent = previewKind === "list" ? "목록 미리보기 — 요소를 클릭하세요." : "상세 미리보기 — 요소를 클릭하세요.";
    if (itemInput.value.trim()) sendItemRoot(itemInput.value.trim());
  });

  window.addEventListener("message", (event) => {
    if (!event.data || event.data.type !== "extract-pick") return;
    if (frame.contentWindow && event.source !== frame.contentWindow) return;
    lastPick = event.data;
    let selector = event.data.selector || "";
    if (previewKind === "list" && itemInput.value.trim()) {
      selector = event.data.relative || relativeToItem(selector);
    }
    lastPick.relativeSelector = selector;
    pickBanner.hidden = false;
    pickEmpty.hidden = true;
    root.querySelectorAll(".field-pick").forEach((btn) => { btn.disabled = false; });
    pickSelector.textContent = selector;
    const bits = [event.data.text, event.data.alt, event.data.href, event.data.src].filter(Boolean);
    pickText.textContent = bits.slice(0, 2).join(" · ").slice(0, 240);
  });

  document.getElementById("btn-set-item").addEventListener("click", () => {
    if (!lastPick) return;
    const selector = lastPick.selector || lastPick.relativeSelector;
    itemInput.value = selector;
    state.item = selector;
    sendItemRoot(selector);
    saveStatus.textContent = "상품 카드 셀렉터를 설정했습니다.";
  });

  function assignPick(section, key) {
    if (!lastPick) return;
    // Keep anything typed by hand before re-rendering the rows.
    syncStateFromInputs();
    const bag = section === "detail" ? state.detail : state.list;
    if (!bag[key]) return;
    let selector = lastPick.selector || "";
    if (section === "list") {
      selector = lastPick.relative || relativeToItem(selector);
    }
    bag[key].selector = selector;
    if (lastPick.tag === "img" && (key === "image" || key === "gallery" || key === "status")) {
      if (key === "image" || key === "gallery") bag[key].attr = bag[key].attr || "src";
      if (key === "status" && lastPick.alt) bag[key].attr = bag[key].attr || "alt";
    }
    if (key === "link" && (lastPick.href || lastPick.tag === "a")) {
      bag[key].attr = "href";
    }
    renderFields();
    const row = root.querySelector(`.field-map-row[data-section="${section}"][data-key="${key}"]`);
    if (row) {
      row.classList.add("just-assigned");
      setTimeout(() => row.classList.remove("just-assigned"), 1200);
    }
    const label = (section === "detail" ? DETAIL_FIELDS : LIST_FIELDS).find((f) => f.key === key);
    saveStatus.textContent = `${label ? label.label : key} 필드에 넣었습니다.`;
  }

  // One floating tooltip outside the scrolling panel, so long help is never clipped.
  const tooltip = document.createElement("div");
  tooltip.className = "help-tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;
  document.body.appendChild(tooltip);

  function showHelp(tip) {
    const help = document.getElementById(tip.dataset.helpFor);
    if (!help) return;
    tooltip.innerHTML = help.innerHTML;
    tooltip.hidden = false;
    const rect = tip.getBoundingClientRect();
    const box = tooltip.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left - 8, window.innerWidth - box.width - 8));
    let top = rect.bottom + 6;
    if (top + box.height > window.innerHeight - 8) top = Math.max(8, rect.top - box.height - 6);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function hideHelp() {
    tooltip.hidden = true;
  }

  root.addEventListener("mouseover", (event) => {
    const tip = event.target.closest(".help-tip");
    if (tip) showHelp(tip);
  });
  root.addEventListener("mouseout", (event) => {
    const tip = event.target.closest(".help-tip");
    if (tip && !tip.contains(event.relatedTarget)) hideHelp();
  });
  root.addEventListener("focusin", (event) => {
    const tip = event.target.closest(".help-tip");
    if (tip) showHelp(tip);
  });
  root.addEventListener("focusout", (event) => {
    if (event.target.closest(".help-tip")) hideHelp();
  });
  window.addEventListener("scroll", hideHelp, true);

  // Hand-edited card selectors (e.g. after dropping :nth-of-type) apply to the next pick.
  itemInput.addEventListener("change", () => sendItemRoot(itemInput.value.trim()));

  root.addEventListener("click", (event) => {
    if (event.target.closest(".help-tip")) return;
    const btn = event.target.closest(".field-pick");
    if (btn) assignPick(btn.dataset.section, btn.dataset.key);
  });

  document.getElementById("btn-preview-list").addEventListener("click", () => {
    previewKind = "list";
    document.getElementById("btn-preview-list").classList.add("active");
    document.getElementById("btn-preview-detail").classList.remove("active");
    loadPreview();
  });
  document.getElementById("btn-preview-detail").addEventListener("click", () => {
    previewKind = "detail";
    document.getElementById("btn-preview-detail").classList.add("active");
    document.getElementById("btn-preview-list").classList.remove("active");
    loadPreview();
  });
  document.getElementById("btn-reload-preview").addEventListener("click", loadPreview);

  document.getElementById("btn-sample").addEventListener("click", async () => {
    syncStateFromInputs();
    saveStatus.textContent = "샘플 추출 중…";
    try {
      const res = await fetch(sampleUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ extract: buildExtract() }),
      });
      const data = await res.json();
      if (!res.ok) {
        saveStatus.textContent = data.error || "샘플 추출 실패";
        return;
      }
      sampleWrap.hidden = false;
      sampleTable.innerHTML = "";
      for (const item of data.items || []) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${escapeAttr(item.title || "")}</td>
          <td>${item.price != null ? item.price.toLocaleString() : ""}</td>
          <td>${escapeAttr(item.saleStatus || "")}</td>
          <td class="url-cell"><a href="${escapeAttr(item.url || "")}" target="_blank" rel="noopener">${escapeAttr(item.url || "")}</a></td>
        `;
        sampleTable.appendChild(tr);
      }
      if (data.items && data.items[0] && data.items[0].url) {
        detailSampleUrl = data.items[0].url;
      }
      saveStatus.textContent = `${data.count || 0}건 샘플`;
    } catch (err) {
      saveStatus.textContent = String(err);
    }
  });

  document.getElementById("btn-save").addEventListener("click", async () => {
    syncStateFromInputs();
    saveStatus.textContent = "저장 중…";
    try {
      const res = await fetch(saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ extract: buildExtract() }),
      });
      const data = await res.json();
      if (!res.ok) {
        saveStatus.textContent = data.error || "저장 실패";
        return;
      }
      saveStatus.textContent = data.path ? `저장됨: ${data.path}` : "저장했습니다.";
    } catch (err) {
      saveStatus.textContent = String(err);
    }
  });

  parseInitial();
  renderFields();
  loadPreview();
})();
