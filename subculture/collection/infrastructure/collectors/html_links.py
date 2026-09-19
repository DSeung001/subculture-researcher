import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bs4 import BeautifulSoup

from subculture.collection.domain.content_rules import DEFAULT_DETAIL_REFRESH_HOURS, METRICS, normalize_url
from subculture.collection.infrastructure.collectors.common import RobotsDenied, extract_product_fields, save_records
from subculture.collection.infrastructure.collectors.http import RobotsPolicy, get_html, page_url
from subculture.collection.infrastructure.collectors.images import card_of, detail_image, list_image


RELATIVE_KOREAN_PATTERN = re.compile(r"^(\d+)\s*(초|분|시간|일|주|개월|년)\s*전$")
RELATIVE_KOREAN_UNITS = {
    "초": lambda n: timedelta(seconds=n), "분": lambda n: timedelta(minutes=n),
    "시간": lambda n: timedelta(hours=n), "일": lambda n: timedelta(days=n),
    "주": lambda n: timedelta(weeks=n), "개월": lambda n: timedelta(days=30 * n),
    "년": lambda n: timedelta(days=365 * n),
}


def parse_relative_korean_date(text: str) -> str | None:
    """'3시간 전' 같은 상대 표기를 오늘 기준 날짜로 환산한다. 해석 불가 시 None."""
    text = text.strip()
    if text in ("방금", "방금 전"):
        return datetime.now(timezone.utc).date().isoformat()
    if text == "어제":
        return (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    match = RELATIVE_KOREAN_PATTERN.match(text)
    if not match:
        return None
    amount, unit = match.groups()
    delta = RELATIVE_KOREAN_UNITS[unit](int(amount))
    return (datetime.now(timezone.utc) - delta).date().isoformat()


def parse_count(text: str) -> int:
    """Parse a count element, never arbitrary numbers from article/body text."""
    match = re.fullmatch(r"\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([kKmM만천]?)\s*(?:회|개)?\s*", text)
    if not match:
        raise ValueError(f"반응 수치를 해석할 수 없음: {text!r}")
    number, unit = match.groups()
    multiplier = {"": 1, "k": 1000, "m": 1000000, "만": 10000, "천": 1000}[unit.lower()]
    value = Decimal(number.replace(",", "")) * multiplier
    if value != value.to_integral_value():
        raise ValueError(f"반응 수치가 정수가 아님: {text!r}")
    return int(value)


def extract_metrics(root, selectors: dict, *, required=False) -> tuple[dict, list[str]]:
    values, errors = {}, []
    for field, selector in selectors.items():
        if field not in METRICS:
            raise ValueError(f"지원하지 않는 수치 필드: {field}")
        node = root.select_one(selector)
        if node is None:
            if required:
                errors.append(f"{field} 요소를 찾을 수 없음: {selector}")
            continue
        try:
            values[field] = parse_count(node.get_text(" ", strip=True))
            values[f"{field}CheckedAt"] = datetime.now(timezone.utc)
        except ValueError as exc:
            errors.append(str(exc))
    return values, errors


HIDDEN_CLASS_HINTS = ("displaynone", "d-none", "hidden", "hide", "invisible")


def visible_text(soup: BeautifulSoup) -> str:
    """Drop CSS-hidden nodes before extracting text.

    Product templates often render every stock-state button/badge
    (재고 있음/품절/예약) and toggle visibility with a class or inline
    style; a static (non-JS) fetch can't tell which one is actually shown,
    so scanning raw get_text() picks up disabled states as if they were
    live. Stripping obviously-hidden nodes first avoids that.
    """
    for node in soup.find_all(True):
        attrs = getattr(node, "attrs", None)
        if not attrs:
            continue  # already decomposed as part of an ancestor's subtree
        classes = " ".join(attrs.get("class", [])).lower()
        style = (attrs.get("style") or "").lower().replace(" ", "")
        if any(hint in classes for hint in HIDDEN_CLASS_HINTS) or "display:none" in style:
            node.decompose()
    return soup.get_text("\n", strip=True)


def list_product_fields(anchor, source: dict, base_url: str, image_url: str | None) -> dict:
    """Price and sale status read from the list card itself, so no detail request is needed.

    The link's own text is used when it already carries the price (whole card is the
    link); otherwise the item's card — the widest ancestor holding only this item's link.
    """
    fields = extract_product_fields(source, " ".join(anchor.get_text(" ", strip=True).split()), image_url)
    if fields:
        return fields
    card = card_of(anchor, source.get("link_selector", "a[href]"), base_url)
    if card is None:
        return {}
    return extract_product_fields(source, " ".join(card.get_text(" ", strip=True).split()), image_url)


def extract_links(html: str, base_url: str, source: dict):
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select(source.get("link_selector", "a[href]")):
        href = anchor.get("href")
        if not href:
            continue
        try:
            url = normalize_url(href, base_url)
        except ValueError:
            continue
        allow = source.get("allow_patterns", [])
        deny = source.get("deny_patterns", [])
        if allow and not any(re.search(pattern, url) for pattern in allow):
            continue
        if any(re.search(pattern, url) for pattern in deny):
            continue
        title_node = anchor.select_one(source["title_selector"]) if source.get("title_selector") else anchor
        if title_node is None:
            continue
        title = " ".join(title_node.get_text(" ", strip=True).split())
        if source.get("title_strip_pattern"):
            # Card anchors often carry price/badge text after the name.
            title = re.sub(source["title_strip_pattern"], "", title).strip()
        if len(title) < int(source.get("min_title_length", 4)):
            continue
        if any(re.search(pattern, title) for pattern in source.get("title_deny_patterns", [])):
            continue
        item = {"url": url, "title": title, "publishedAt": None, "_errors": []}
        image = list_image(anchor, source, base_url)
        if image:
            item["imageUrl"] = image
        if source.get("list_product_mode"):
            item.update(list_product_fields(anchor, source, base_url, item.get("imageUrl")))
        if source.get("published_selector"):
            date_node = anchor.select_one(source["published_selector"])
            if date_node is not None:
                date = date_node.get("datetime") or date_node.get_text(" ", strip=True)
                try:
                    item["publishedAt"] = (
                        datetime.strptime(date, source["published_format"]).date().isoformat()
                        if source.get("published_format") else date
                    )
                except ValueError:
                    relative = parse_relative_korean_date(date)
                    if relative:
                        item["publishedAt"] = relative
                    else:
                        item["_errors"].append(f"게시일 형식 오류: {date}")
        values, errors = extract_metrics(anchor, source.get("list_metrics", {}))
        item.update(values)
        item["_errors"].extend(errors)
        yield item


def html_items(source: dict, store=None):
    limit = int(source.get("max_items", 50))
    if limit <= 0:
        return
    policy = RobotsPolicy(
        source.get("respect_robots", True),
        source.get("timeout_seconds", 15),
        source,
    )
    policy.check(source["url"])
    if source.get("render_js", False):
        # Static/RSS/manual paths do not import or launch Playwright.
        from subculture.collection.infrastructure.collectors.rendered import rendered_items
        yield from rendered_items(source, policy)
        return
    page_param = source.get("page_param")
    max_pages = max(1, int(source.get("max_pages", 1))) if page_param else 1
    seen = set()
    for page in range(1, max_pages + 1):
        try:
            html, final_url = get_html(
                page_url(source["url"], page_param, page), policy,
                source.get("timeout_seconds", 15), source,
            )
        except RobotsDenied:
            if page == 1:
                raise
            break  # later pages may be disallowed; keep what earlier pages gave
        new_links = 0
        for item in extract_links(html, final_url, source):
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            new_links += 1
            fetch_detail(item, source, policy, store)
            yield item
            if len(seen) >= limit:
                return
        if not new_links:
            break  # the site ignored the page number or ran out of pages


def fetch_detail(item: dict, source: dict, policy: RobotsPolicy, store=None) -> None:
    """Add detail-page fields (metrics, photo, product info) to a listed item in place."""
    detail_selectors = {k: v for k, v in source.get("detail_metrics", {}).items() if k not in item}
    product_mode = source.get("product_mode", False)
    detail_image_mode = source.get("fetch_detail_image", False)
    if not (detail_selectors or product_mode or detail_image_mode):
        return
    # Metrics change all the time, so pages that read them are never skipped.
    if not detail_selectors and store is not None and not store.needs_detail(
        item["url"], product_mode=product_mode,
        refresh_hours=float(source.get("detail_refresh_hours", DEFAULT_DETAIL_REFRESH_HOURS)),
    ):
        return
    try:
        detail_html, detail_url = get_html(
            item["url"], policy, source.get("timeout_seconds", 15), source,
        )
        detail_soup = BeautifulSoup(detail_html, "html.parser")
        if detail_selectors:
            values, errors = extract_metrics(detail_soup, detail_selectors, required=True)
            item.update(values)
            item["_errors"].extend(errors)
        # The detail page's own photo wins over the list thumbnail.
        image_url = detail_image(detail_soup, detail_url, source) if (product_mode or detail_image_mode) else None
        if product_mode:
            # Full-page text picks up nav/footer boilerplate (site-wide
            # "예약"/"마감" links, unrelated prices) as false product
            # signals; product_text_selector scopes to the product panel.
            text_selector = source.get("product_text_selector")
            text_root = detail_soup.select_one(text_selector) if text_selector else detail_soup
            full_text = visible_text(text_root) if text_root else ""
            item.update(extract_product_fields(source, full_text, image_url))
        if image_url:
            item["imageUrl"] = image_url
        item["detailCheckedAt"] = datetime.now(timezone.utc)
    except Exception as exc:
        item["_errors"].append(f"상세 페이지 실패: {exc}")


def collect_html_links(db, source: dict, store=None) -> dict:
    return save_records(html_items(source, store), db, source, store)
