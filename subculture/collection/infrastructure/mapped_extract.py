"""Apply an extract profile to HTML with BeautifulSoup."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from subculture.collection.domain.content_rules import normalize_url
from subculture.collection.domain.extract_fields import apply_parse, product_fields_from_extract
from subculture.shared.image_urls import LAZY_ATTRS, clean_image_url


def _node_value(node, field: dict, base_url: str) -> str:
    attr = field.get("attr")
    if attr:
        if attr in {"href", "src"} or attr in LAZY_ATTRS:
            raw = node.get(attr) or ""
            if attr == "href" or attr == "src" or attr in LAZY_ATTRS:
                return urljoin(base_url, raw) if raw else ""
        return (node.get(attr) or "").strip()
    if node.name == "img":
        return (node.get("alt") or "").strip()
    return node.get_text(" ", strip=True)


def _select_values(root, field: dict, base_url: str) -> list[str]:
    nodes = root.select(field["selector"])
    if field.get("many"):
        return [_node_value(node, field, base_url) for node in nodes if _node_value(node, field, base_url)]
    for node in nodes:
        # Compound selectors (e.g. `.badge, img.sold`) may match an empty first node.
        value = _node_value(node, field, base_url)
        if value:
            return [value]
        # When attr is set but empty (badge text vs img alt), fall back to visible text.
        if field.get("attr"):
            text = node.get_text(" ", strip=True) if node.name != "img" else (node.get("alt") or "")
            if text:
                return [text]
    return []


def read_field(root, field: dict, base_url: str, *, preorder_words: tuple[str, ...] = ()):
    """Read one field from a card/detail root. Returns parsed value or list for many."""
    values = _select_values(root, field, base_url)
    if not values:
        return [] if field.get("many") else None
    if field.get("many"):
        parsed = []
        for value in values:
            item = apply_parse(field.get("parse") or "text", value, preorder_words=preorder_words)
            if item:
                parsed.append(item)
        return parsed
    return apply_parse(field.get("parse") or "text", values[0], preorder_words=preorder_words)


def extract_list_items(html: str, base_url: str, source: dict) -> list[dict]:
    """Build list items from source['extract']['list']. Empty when extract is absent."""
    extract = source.get("extract")
    if not extract or not extract.get("list"):
        return []
    list_cfg = extract["list"]
    fields = list_cfg["fields"]
    preorder = tuple(source.get("preorder_words", ()))
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select(list_cfg["item"]):
        link_field = fields.get("link")
        title_field = fields.get("title")
        if not link_field or not title_field:
            continue
        href_raw = read_field(card, link_field, base_url, preorder_words=preorder)
        title = read_field(card, title_field, base_url, preorder_words=preorder)
        if not href_raw or not title:
            continue
        try:
            url = normalize_url(str(href_raw), base_url)
        except ValueError:
            continue
        allow = source.get("allow_patterns", [])
        deny = source.get("deny_patterns", [])
        if allow and not any(re.search(pattern, url) for pattern in allow):
            continue
        if any(re.search(pattern, url) for pattern in deny):
            continue
        if any(re.search(pattern, str(title)) for pattern in source.get("title_deny_patterns", [])):
            continue
        min_len = int(source.get("min_title_length", 4))
        if len(str(title)) < min_len:
            continue

        item = {"url": url, "title": str(title), "publishedAt": None, "_errors": []}

        if "image" in fields:
            image_raw = read_field(card, fields["image"], base_url, preorder_words=preorder)
            photo = clean_image_url(
                image_raw, base_url, deny=source.get("image_deny_patterns", []),
            )
            if photo:
                item["imageUrl"] = photo

        price = None
        status = None
        deadline = None
        if "price" in fields:
            price = read_field(card, fields["price"], base_url, preorder_words=preorder)
        if "status" in fields:
            status = read_field(card, fields["status"], base_url, preorder_words=preorder)
        if "deadline" in fields:
            deadline = read_field(card, fields["deadline"], base_url, preorder_words=preorder)
        if "published" in fields:
            published = read_field(card, fields["published"], base_url, preorder_words=preorder)
            if published:
                item["publishedAt"] = published

        product = product_fields_from_extract(
            source,
            price=price if isinstance(price, int) else None,
            status=status if isinstance(status, str) else None,
            deadline=deadline if isinstance(deadline, str) else None,
            image_url=item.get("imageUrl"),
        )
        if product:
            item.update(product)
        items.append(item)
    return items


def apply_detail_extract(soup, detail_url: str, source: dict, item: dict) -> None:
    """Mutate `item` with extract.detail fields when configured."""
    extract = source.get("extract") or {}
    detail = extract.get("detail") or {}
    fields = detail.get("fields") or {}
    if not fields:
        return
    preorder = tuple(source.get("preorder_words", ()))
    deny = source.get("image_deny_patterns", [])

    if "image" in fields:
        image_raw = read_field(soup, fields["image"], detail_url, preorder_words=preorder)
        photo = clean_image_url(image_raw, deny=deny)
        if photo:
            item["imageUrl"] = photo

    if "gallery" in fields:
        gallery = read_field(soup, fields["gallery"], detail_url, preorder_words=preorder) or []
        urls = []
        seen = set()
        exclude = item.get("imageUrl")
        for raw in gallery:
            photo = clean_image_url(raw, deny=deny)
            if photo and photo != exclude and photo not in seen:
                seen.add(photo)
                urls.append(photo)
        item["detailImageUrls"] = urls

    price = read_field(soup, fields["price"], detail_url, preorder_words=preorder) if "price" in fields else None
    status = read_field(soup, fields["status"], detail_url, preorder_words=preorder) if "status" in fields else None
    deadline = read_field(soup, fields["deadline"], detail_url, preorder_words=preorder) if "deadline" in fields else None
    if "title" in fields and not item.get("title"):
        title = read_field(soup, fields["title"], detail_url, preorder_words=preorder)
        if title:
            item["title"] = str(title)

    # Only fill product fields when list did not already set them, or detail provides price.
    if price is not None or status is not None or deadline is not None:
        existing_price = item.get("price")
        product = product_fields_from_extract(
            source,
            price=price if isinstance(price, int) else existing_price,
            status=status if isinstance(status, str) else item.get("saleStatus"),
            deadline=deadline if isinstance(deadline, str) else item.get("preorderEndAt"),
            image_url=item.get("imageUrl"),
        )
        if product:
            item.update(product)
