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
