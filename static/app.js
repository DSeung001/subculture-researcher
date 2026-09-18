document.querySelectorAll(".auto-submit").forEach((el) => {
  el.addEventListener("change", () => el.form.submit());
});

document.addEventListener("click", (event) => {
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
      const currentItems = document.querySelector(".items");
      const incomingItems = doc.querySelector(".items");
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
