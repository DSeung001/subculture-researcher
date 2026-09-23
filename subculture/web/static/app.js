document.querySelectorAll(".auto-submit").forEach((el) => {
  el.addEventListener("change", () => el.form.submit());
});

// A photo link that fails (hotlink block, 404) falls back to the card's empty thumbnail.
const markBrokenThumb = (img) => img.closest(".card-thumb")?.classList.add("is-broken");
document.addEventListener("error", (event) => {
  if (event.target.matches?.("img.card-thumb-img")) markBrokenThumb(event.target);
}, true);
document.querySelectorAll("img.card-thumb-img").forEach((img) => {
  if (img.complete && img.naturalWidth === 0) markBrokenThumb(img);
});

document.addEventListener("click", (event) => {
  const confirmation = event.target.closest("[data-confirm]");
  if (confirmation && !window.confirm(confirmation.dataset.confirm)) {
    event.preventDefault();
    return;
  }
  const toggle = event.target.closest("button.original-toggle");
  if (toggle) {
    const titleEl = toggle.closest(".card-title");
    const translated = titleEl?.querySelector(".title-translated");
    const original = titleEl?.querySelector(".title-original");
    if (!translated || !original) return;

    const showingOriginal = original.hidden;
    translated.hidden = showingOriginal;
    original.hidden = !showingOriginal;
    toggle.setAttribute("aria-pressed", String(showingOriginal));
    toggle.textContent = showingOriginal ? "번역 제목" : "원어 제목";
    return;
  }

  const trigger = event.target.closest("[data-dialog-target]");
  if (trigger) {
    const dialog = document.getElementById(trigger.dataset.dialogTarget);
    if (!dialog) return;
    dialog.showModal();
    const field = dialog.querySelector("textarea, input[type='text']");
    if (field) {
      field.focus();
      if (typeof field.selectionStart === "number") {
        field.selectionStart = field.selectionEnd = field.value.length;
      }
    }
    return;
  }

  const closeBtn = event.target.closest("[data-dialog-close]");
  if (closeBtn) closeBtn.closest("dialog")?.close();
});

const loadMoreEl = document.getElementById("load-more");
if (loadMoreEl) {
  let loading = false;

  const syncPageUrl = (pageUrl) => {
    document.querySelectorAll('input[name="next"]').forEach((input) => {
      input.value = pageUrl;
    });
    history.replaceState(null, "", pageUrl);
  };

  const stillInView = () => loadMoreEl.getBoundingClientRect().top < window.innerHeight + 400;

  const loadMore = async () => {
    const url = loadMoreEl.dataset.moreUrl;
    if (!url || loading) return;

    loading = true;
    loadMoreEl.classList.add("is-loading");

    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("load failed");

      const doc = new DOMParser().parseFromString(await response.text(), "text/html");
      const currentItems = document.querySelector("#item-list");
      const incomingItems = doc.querySelector("#item-list");
      if (!currentItems || !incomingItems) throw new Error("missing items");

      [...incomingItems.children].forEach((node) => {
        currentItems.appendChild(document.importNode(node, true));
      });

      const nextSentinel = doc.querySelector("#load-more");
      const nextUrl = nextSentinel?.dataset.moreUrl;
      // Keep the browser URL on the filter root so refresh starts from the first page.
      const rootUrl = new URL(url, window.location.origin);
      rootUrl.searchParams.delete("after");
      syncPageUrl(rootUrl.pathname + rootUrl.search);
      if (nextUrl) {
        loadMoreEl.dataset.moreUrl = nextUrl;
      } else {
        delete loadMoreEl.dataset.moreUrl;
        loadMoreEl.innerHTML = nextSentinel?.innerHTML ?? "";
      }
    } catch {
      loadMoreEl.innerHTML = `<a class="btn full" href="${url}">더 보기</a>`;
      delete loadMoreEl.dataset.moreUrl;
    } finally {
      loading = false;
      loadMoreEl.classList.remove("is-loading");
      if (loadMoreEl.dataset.moreUrl && stillInView()) loadMore();
    }
  };

  new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadMore();
    },
    { rootMargin: "400px 0px" },
  ).observe(loadMoreEl);
}

const draftForm = document.getElementById("draft-create-form");
if (draftForm) {
  const countEl = draftForm.querySelector(".draft-bar-count");
  const syncDraftBar = () => {
    const selected = document.querySelectorAll(".draft-source:checked").length;
    if (countEl) countEl.textContent = `${selected}개 선택`;
    draftForm.hidden = selected === 0;
    document.body.classList.toggle("has-draft-bar", selected > 0);
  };
  document.addEventListener("change", (event) => {
    if (event.target.matches(".draft-source")) syncDraftBar();
  });
  syncDraftBar();
}

const aiBusy = document.getElementById("ai-draft-busy");
document.querySelectorAll("form.ai-draft-form").forEach((form) => {
  form.addEventListener("submit", () => {
    if (!form.checkValidity()) return;
    if (aiBusy) aiBusy.hidden = false;
    document.body.classList.add("ai-draft-busy-open");
    form.querySelectorAll("button").forEach((button) => {
      button.disabled = true;
    });
  });
});

// A submit button marked data-ai-busy (e.g. 「AI로 글 쓰기」 on a form that also has other buttons)
// shows the same notice. Disabling is deferred: a submitter disabled inside the submit event
// is left out of the form data, which would drop its name/value.
document.addEventListener("submit", (event) => {
  const submitter = event.submitter;
  if (!submitter?.hasAttribute("data-ai-busy") || !event.target.checkValidity()) return;
  if (aiBusy) aiBusy.hidden = false;
  document.body.classList.add("ai-draft-busy-open");
  setTimeout(() => {
    event.target.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    document.querySelectorAll("button[data-ai-busy], .draft-bar button").forEach((button) => { button.disabled = true; });
  }, 0);
});

// Coming back with the browser's back button restores the page from cache with the notice still up.
window.addEventListener("pageshow", (event) => {
  if (event.persisted && aiBusy && !aiBusy.hidden) location.reload();
});

// Draft posts: character counters and copy buttons. A link counts as 23 characters, like on X
// (the same rule as post_length in subculture/drafts/domain/posts.py).
const X_URL_LENGTH = 23;
const postLength = (text) => text.replace(/https?:\/\/\S+/g, "x".repeat(X_URL_LENGTH)).length;

const updatePostCount = (counter) => {
  const source = document.getElementById(counter.dataset.countFor);
  if (!source) return;
  const limit = Number(counter.dataset.limit) || 0;
  const length = postLength(source.value ?? source.textContent);
  counter.textContent = limit ? `${length} / ${limit}자` : `${length}자`;
  counter.classList.toggle("is-over", limit > 0 && length > limit);
};
document.querySelectorAll("[data-count-for]").forEach(updatePostCount);
document.addEventListener("input", (event) => {
  if (!event.target.matches("textarea[id]")) return;
  document.querySelectorAll(`[data-count-for="${event.target.id}"]`).forEach(updatePostCount);
});

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const scratch = document.createElement("textarea");
    scratch.value = text;
    scratch.style.position = "fixed";
    scratch.style.opacity = "0";
    document.body.appendChild(scratch);
    scratch.select();
    try {
      return document.execCommand("copy");
    } finally {
      scratch.remove();
    }
  }
};

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-target]");
  if (!button) return;
  const source = document.getElementById(button.dataset.copyTarget);
  if (!source) return;
  const original = button.textContent;
  button.textContent = (await copyText((source.value ?? source.textContent).trim())) ? "복사됨" : "복사 실패";
  setTimeout(() => { button.textContent = original; }, 1500);
});

// 수집 목록: ▾ opens the row below with the source's newest items (fetched once).
document.addEventListener("click", async (event) => {
  const toggle = event.target.closest("button.source-samples-toggle");
  if (!toggle) return;
  const row = toggle.closest("tr")?.nextElementSibling;
  if (!row?.classList.contains("source-samples-row")) return;
  const opening = row.hidden;
  row.hidden = !opening;
  toggle.classList.toggle("is-open", opening);
  toggle.setAttribute("aria-expanded", String(opening));
  if (!opening || toggle.dataset.loaded) return;
  const cell = row.querySelector("td");
  cell.textContent = "불러오는 중…";
  try {
    const response = await fetch(toggle.dataset.url);
    if (!response.ok) throw new Error("load failed");
    cell.innerHTML = await response.text();
    toggle.dataset.loaded = "1";
  } catch {
    cell.textContent = "불러오지 못했습니다. 다시 눌러 주세요.";
  }
});
