"""Pick the article or product photo from list cards and detail pages.

Site-specific selectors live in sources.yaml (`list_image_selector`,
`image_selector`, `image_deny_patterns`); this module only holds the shared rules.
"""

from urllib.parse import urljoin

from image_urls import LAZY_ATTRS, clean_image_url

MIN_SIDE = 80  # smaller <img> are badges/icons, not photos
MAX_CARD_DEPTH = 8
HEAD_IMAGE_QUERIES = (
    'meta[property="og:image"]',
    'meta[property="og:image:url"]',
    'meta[name="twitter:image"]',
    'link[rel="image_src"]',
)


def _is_tiny(img) -> bool:
    try:
        return int(img.get("width")) < MIN_SIDE and int(img.get("height")) < MIN_SIDE
    except (TypeError, ValueError):
        return False


def img_url(img, base_url: str, deny=()) -> str | None:
    """The real photo URL of an <img>: lazy-load attributes, then src, then srcset."""
    if _is_tiny(img):
        return None
    for attr in LAZY_ATTRS:
        url = clean_image_url(img.get(attr), base_url, deny)
        if url:
            return url
    srcset = (img.get("srcset") or img.get("data-srcset") or "").split(",")[0].strip().split(" ")[0]
    return clean_image_url(srcset, base_url, deny)


def first_image(root, selector: str, base_url: str, deny=()) -> str | None:
    for node in root.select(selector):
        if node.name != "img":
            continue
        url = img_url(node, base_url, deny)
        if url:
            return url
    return None


def card_of(anchor, link_selector: str, base_url: str):
    """The widest ancestor of a list link that still holds only that item's links.

    Walking up until a second distinct article link appears finds the item's own
    card without a per-site card selector, and never crosses into a neighbour.
    """
    card = None
    for depth, node in enumerate(anchor.parents):
        if depth >= MAX_CARD_DEPTH or node.name in {"body", "html", "[document]"}:
            break
        hrefs = {
            urljoin(base_url, link.get("href", "")).split("#")[0]
            for link in node.select(link_selector) if link.get("href")
        }
        if len(hrefs) > 1:
            break
        card = node
    return card


def list_image(anchor, source: dict, base_url: str) -> str | None:
    """Photo shown on the list card of `anchor` (its own <img>, else its card's)."""
    selector = source.get("list_image_selector")
    if not selector:
        return None
    deny = source.get("image_deny_patterns", [])
    url = first_image(anchor, selector, base_url, deny)
    if url:
        return url
    card = card_of(anchor, source.get("link_selector", "a[href]"), base_url)
    return first_image(card, selector, base_url, deny) if card is not None else None


def detail_image(soup, base_url: str, source: dict) -> str | None:
    """Photo of a detail page: explicit selector first, then og:image / twitter:image."""
    deny = source.get("image_deny_patterns", [])
    selector = source.get("image_selector")
    if selector:
        url = first_image(soup, selector, base_url, deny)
        if url:
            return url
    for query in HEAD_IMAGE_QUERIES:
        for node in soup.select(query):
            url = clean_image_url(node.get("content") or node.get("href"), base_url, deny)
            if url:
                return url
    return None
