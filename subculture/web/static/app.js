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

// 검토 화면: ticking cards shows the bar that turns them into a comparison post.
const compareForm = document.getElementById("compare-form");
if (compareForm) {
  const selected = new Set();
  const countEl = compareForm.querySelector(".draft-bar-count");
  const submit = compareForm.querySelector('[type="submit"]');
  const error = document.getElementById("compare-error");
  const panel = document.getElementById("compare-panel");
  const message = document.getElementById("compare-message");
  const maximum = Number(compareForm.dataset.maxSources);
  let loading = false;
  let revision = 0;
  const sync = () => {
    document.querySelectorAll(".draft-source").forEach((box) => { box.checked = selected.has(box.value); });
    countEl.textContent = `${selected.size}개 선택`;
    compareForm.hidden = selected.size === 0 && !loading;
    submit.disabled = loading || selected.size === 0;
    document.body.classList.toggle("has-draft-bar", !compareForm.hidden);
  };
  const changed = () => {
    revision++;
    error.textContent = "";
    if (!panel.hidden) message.textContent = "선택이 변경되었습니다. 비교글을 다시 생성해주세요. 편집 내용은 유지됩니다.";
    sync();
  };
  document.addEventListener("change", (event) => {
    if (!event.target.matches(".draft-source")) return;
    const box = event.target;
    if (box.checked && !selected.has(box.value) && selected.size >= maximum) {
      error.textContent = `비교글 재료는 ${maximum}개까지입니다.`;
      sync();
      return;
    }
    if (box.checked) selected.add(box.value); else selected.delete(box.value);
    changed();
  });
  document.getElementById("compare-clear").addEventListener("click", () => { selected.clear(); changed(); });
  document.getElementById("compare-close").addEventListener("click", () => { panel.hidden = true; });
  // Newly loaded or duplicated cards reflect the same in-memory selection.
  new MutationObserver(sync).observe(document.getElementById("item-list"), { childList: true });
  window.addEventListener("pageshow", sync);
  document.getElementById("post-body").value = "";
  document.getElementById("post-reply").value = "";
  compareForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (loading || !selected.size) return;
    const requestedRevision = revision;
    const data = new FormData();
    selected.forEach((id) => data.append("source_ids", id));
    loading = true;
    error.textContent = "생성 중…";
    sync();
    try {
      const response = await fetch(compareForm.action, { method: "POST", headers: { Accept: "application/json" }, body: data });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "비교글을 만들지 못했습니다.");
      if (requestedRevision !== revision) throw new Error("선택이 변경되었습니다. 다시 생성해주세요.");
      document.getElementById("post-body").value = result.body;
      document.getElementById("post-reply").value = result.reply;
      panel.querySelector('[data-count-for="post-body"]').dataset.limit = result.bodyTarget;
      panel.querySelectorAll("[data-count-for]").forEach(updatePostCount);
      message.textContent = `${result.count}개 항목 · 현재 화면에서만 표시됩니다. 새로고침하면 초기화됩니다.` +
        (result.missingCount ? ` 찾을 수 없는 ${result.missingCount}개 항목은 제외했습니다.` : "");
      panel.hidden = false;
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
      document.getElementById("post-body").focus({ preventScroll: true });
      error.textContent = "";
    } catch (failure) {
      error.textContent = failure.message || "비교글을 만들지 못했습니다. 다시 시도해주세요.";
    } finally {
      loading = false;
      sync();
    }
  });
  sync();
}

// 비교글: character counters, copy buttons and the X compose link. A link counts as 23
// characters, like on X (the same rule as post_length in subculture/shared/compare_post.py).
const X_URL_LENGTH = 23;
const postLength = (text) => text.replace(/https?:\/\/\S+/g, "x".repeat(X_URL_LENGTH)).length;

const updatePostCount = (counter) => {
  const source = document.getElementById(counter.dataset.countFor);
  if (!source) return;
  const limit = Number(counter.dataset.limit) || 0;
  const length = postLength(source.value);
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
  const copyButton = event.target.closest("[data-copy-target]");
  if (copyButton) {
    const source = document.getElementById(copyButton.dataset.copyTarget);
    if (!source) return;
    const original = copyButton.textContent;
    copyButton.textContent = (await copyText(source.value.trim())) ? "복사됨" : "복사 실패";
    setTimeout(() => { copyButton.textContent = original; }, 1500);
    return;
  }
  const postButton = event.target.closest("[data-x-post-target]");
  if (postButton) {
    const source = document.getElementById(postButton.dataset.xPostTarget);
    if (!source) return;
    window.open(`https://x.com/intent/post?text=${encodeURIComponent(source.value.trim())}`, "_blank", "noopener");
  }
});
