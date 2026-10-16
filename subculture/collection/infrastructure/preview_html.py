"""Sanitize remote HTML for the opaque-origin picker iframe (no remote script execution)."""

from urllib.parse import urljoin

from bs4 import BeautifulSoup


EVENT_ATTR_PREFIX = "on"
REMOVE_TAGS = ("script", "noscript", "template", "iframe", "object", "embed")


def _absolutize(tag, attr: str, base_url: str) -> None:
    value = tag.get(attr)
    if not value or not isinstance(value, str):
        return
    stripped = value.strip()
    if not stripped or stripped.startswith(("data:", "javascript:", "mailto:", "#")):
        return
    tag[attr] = urljoin(base_url, stripped)


def sanitize_preview_html(html: str, base_url: str) -> str:
    """Strip executable markup and make relative URLs absolute for a sandbox iframe."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag_name in REMOVE_TAGS:
        for node in soup.find_all(tag_name):
            node.decompose()
    # Stylesheets keep the shop's layout recognisable; preload/import/manifest links do not.
    for node in soup.find_all("link"):
        rel = node.get("rel") or []
        if isinstance(rel, str):
            rel = rel.split()
        if "stylesheet" in [value.lower() for value in rel] and node.get("href"):
            _absolutize(node, "href", base_url)
        else:
            node.decompose()

    for tag in soup.find_all(True):
        # Drop inline event handlers.
        for attr in list(tag.attrs):
            if attr.lower().startswith(EVENT_ATTR_PREFIX):
                del tag[attr]
            elif attr.lower() == "href" and str(tag.get(attr) or "").strip().lower().startswith("javascript:"):
                del tag[attr]
            elif attr.lower() == "srcdoc":
                del tag[attr]

        if tag.name == "a":
            _absolutize(tag, "href", base_url)
            tag["target"] = "_blank"
            # Keep navigation from escaping the picker; parent listens for clicks.
            existing = tag.get("rel") or []
            if isinstance(existing, str):
                existing = existing.split()
            tag["rel"] = list(dict.fromkeys([*existing, "noopener", "noreferrer"]))
        if tag.name == "img":
            for attr in ("src", "data-src", "data-original", "data-lazy-src"):
                if tag.get(attr):
                    _absolutize(tag, attr, base_url)
        if tag.name == "base":
            tag.decompose()

    # Inject a tiny click bridge so the parent can capture element selectors.
    bridge = soup.new_tag("script")
    bridge.string = """
(function () {
  function cssPath(el) {
    if (!el || el.nodeType !== 1) return "";
    if (el.id) return "#" + CSS.escape(el.id);
    var parts = [];
    while (el && el.nodeType === 1 && el.tagName.toLowerCase() !== "html") {
      var tag = el.tagName.toLowerCase();
      var parent = el.parentElement;
      if (!parent) { parts.unshift(tag); break; }
      var siblings = Array.prototype.filter.call(parent.children, function (c) {
        return c.tagName === el.tagName;
      });
      if (siblings.length > 1) {
        var index = siblings.indexOf(el) + 1;
        parts.unshift(tag + ":nth-of-type(" + index + ")");
      } else {
        parts.unshift(tag);
      }
      el = parent;
      if (parts.length > 12) break;
    }
    return parts.join(" > ");
  }
  function relativePath(el, root) {
    if (!root || !root.contains(el)) return cssPath(el);
    if (el === root) return "";
    var parts = [];
    while (el && el !== root && el.nodeType === 1) {
      var tag = el.tagName.toLowerCase();
      var parent = el.parentElement;
      var siblings = Array.prototype.filter.call(parent.children, function (c) {
        return c.tagName === el.tagName;
      });
      if (siblings.length > 1) {
        parts.unshift(tag + ":nth-of-type(" + (siblings.indexOf(el) + 1) + ")");
      } else {
        parts.unshift(tag);
      }
      el = parent;
      if (parts.length > 10) break;
    }
    return parts.join(" > ");
  }
  var lastHover = null;
  document.addEventListener("mouseover", function (ev) {
    var t = ev.target;
    if (lastHover && lastHover !== t) lastHover.style.outline = "";
    if (t && t.style) t.style.outline = "2px solid #3b82f6";
    lastHover = t;
  }, true);
  document.addEventListener("click", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    var t = ev.target;
    if (!t || t.nodeType !== 1) return;
    var text = (t.innerText || t.textContent || "").trim().slice(0, 200);
    var card = null;
    try {
      card = window.__extractItemRootSelector && t.closest ? t.closest(window.__extractItemRootSelector) : null;
    } catch (_err) {
      card = null;
    }
    var payload = {
      type: "extract-pick",
      selector: cssPath(t),
      relative: card && card !== t ? relativePath(t, card) : "",
      tag: t.tagName.toLowerCase(),
      text: text,
      href: t.getAttribute("href") || (t.closest && t.closest("a") && t.closest("a").getAttribute("href")) || "",
      src: t.getAttribute("src") || t.getAttribute("data-src") || "",
      alt: t.getAttribute("alt") || "",
    };
    parent.postMessage(payload, "*");
  }, true);
  window.addEventListener("message", function (ev) {
    if (ev.source !== parent || !ev.data || ev.data.type !== "extract-set-item") return;
    window.__extractItemRootSelector = ev.data.selector || "";
  });
})();
"""
    if soup.body:
        soup.body.append(bridge)
    elif soup.html:
        soup.html.append(bridge)
    else:
        soup.append(bridge)

    # Prefer a <base> so residual relative URLs resolve (we already absolutized common ones).
    if soup.head is None and soup.html:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    if soup.head is not None:
        base = soup.new_tag("base", href=base_url)
        soup.head.insert(0, base)

    return str(soup)
