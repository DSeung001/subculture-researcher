import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from subculture.collection.infrastructure.collectors.common import save_records
from subculture.collection.infrastructure.collectors.http import RobotsPolicy, get_html
from subculture.collection.infrastructure.collectors.images import detail_image
from subculture.collection.domain.content_rules import DEFAULT_DETAIL_REFRESH_HOURS, normalize_url


DETAIL_LINK_RE = re.compile(r"/shop/detail\.php\?")
DEADLINE_RE = re.compile(r"예약마감일\s*:?\s*(\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일")
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+)원")
RELEASE_RE = re.compile(r"^\[([^\]]*입고[^\]]*)\]")
FIGURE_KEYWORDS = (
    "피규어", "넨도로이드", "POP UP PARADE", "Figuarts", "룩업", "TENITOL",
    "누들스토퍼", "ESPRESTO", "Relax time", "BiCute", "Coreful", "Luminasta",
)


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _first_meta(soup: BeautifulSoup, prop: str) -> str:
    node = soup.select_one(f'meta[property="{prop}"]')
    return _clean(node.get("content", "")) if node else ""


def _product_title(soup: BeautifulSoup) -> str:
    meta_title = _first_meta(soup, "og:title")
    if meta_title and meta_title not in {"피규어팜", "정품 피규어 쇼핑몰 피규어팜"}:
        return meta_title

    selectors = (
        "h1", "h2", ".product_name", ".prd_name", ".goods_name",
        ".item_name", ".name",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        value = _clean(node.get_text(" ", strip=True)) if node else ""
        if len(value) >= 8 and value != "상품상세":
            return value

    candidates = []
    for line in soup.get_text("\n", strip=True).splitlines():
        value = _clean(line)
        if len(value) >= 12 and any(keyword.lower() in value.lower() for keyword in FIGURE_KEYWORDS):
            candidates.append(value)
    return max(candidates, key=len, default="")


def _labeled_value(soup: BeautifulSoup, label: str) -> str:
    lines = [_clean(line) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    for index, line in enumerate(lines):
        normalized = line.replace("|", " ").strip()
        if normalized == label and index + 1 < len(lines):
            return lines[index + 1]
        if normalized.startswith(label):
            tail = normalized[len(label):].strip(" :")
            if tail:
                return tail
    return ""


def _parse_deadline(text: str) -> str | None:
    match = DEADLINE_RE.search(text)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    return f"20{year:02d}-{month:02d}-{day:02d}"


def _parse_price(text: str) -> int | None:
    values = [int(value.replace(",", "")) for value in PRICE_RE.findall(text)]
    plausible = [value for value in values if value >= 5000]
    return plausible[0] if plausible else (values[0] if values else None)


def _list_title(anchor) -> str:
    """Product name shown on the list card (`.ffm-product-card .name`); "" when the markup has none."""
    card = anchor.find_parent(class_="ffm-product-card")
    node = card.select_one(".name") if card is not None else None
    return _clean(node.get_text(" ", strip=True)) if node else ""


def _is_figure(title: str) -> bool:
    return any(keyword.lower() in title.lower() for keyword in FIGURE_KEYWORDS)


def _detail_urls(listing_html: str, base_url: str, limit: int):
    """(detail URL, list-card title) pairs, deduplicated, at most `limit`."""
    soup = BeautifulSoup(listing_html, "html.parser")
    seen = set()
    for anchor in soup.select('a[href*="/shop/detail.php"], a[href*="detail.php"]'):
        href = anchor.get("href")
        if not href:
            continue
        url = normalize_url(urljoin(base_url, href))
        if not DETAIL_LINK_RE.search(url) or url in seen:
            continue
        seen.add(url)
        yield url, _list_title(anchor)
        if len(seen) >= limit:
            return


def figurefarm_items(source: dict, store=None):
    limit = max(1, int(source.get("max_items", 20)))
    timeout = int(source.get("timeout_seconds", 15))
    policy = RobotsPolicy(source.get("respect_robots", True), timeout, source)

    listing_html, listing_url = get_html(source["url"], policy, timeout, source)
    refresh_hours = float(source.get("detail_refresh_hours", DEFAULT_DETAIL_REFRESH_HOURS))
    for url, list_title in _detail_urls(listing_html, listing_url, limit):
        # Non-figure products are never stored, so without this they would be fetched every run.
        if source.get("figure_only", True) and list_title and not _is_figure(list_title):
            continue
        if store is not None and not store.needs_detail(url, product_mode=True, refresh_hours=refresh_hours):
            yield {"url": url, "title": list_title or url, "_errors": []}
            continue
        try:
            html, final_url = get_html(url, policy, timeout, source)
            soup = BeautifulSoup(html, "html.parser")
            full_text = soup.get_text("\n", strip=True)
            title = _product_title(soup)
            if not title:
                yield {
                    "url": final_url,
                    "title": "(상품명 파싱 실패)",
                    "_errors": ["상품명을 찾을 수 없음"],
                }
                continue

            if source.get("figure_only", True) and not _is_figure(title):
                continue

            deadline = _parse_deadline(full_text)
            release_match = RELEASE_RE.search(title)
            sold_out = "SOLD OUT" in full_text.upper() or "품절" in full_text
            preorder = "본 상품은 예약상품" in full_text or deadline is not None

            sale_status = "SOLD_OUT" if sold_out else ("PREORDER" if preorder else "IN_STOCK")
            price = _parse_price(full_text)

            item = {
                "url": final_url,
                "title": title,
                "entityType": "PRODUCT",
                "shop": "FigureFarm",
                "saleStatus": sale_status,
                "preorderEndAt": deadline,
                "releaseWindowText": release_match.group(1) if release_match else "",
                "manufacturer": _labeled_value(soup, "제조사"),
                "sizeText": _labeled_value(soup, "치수"),
                "price": price,
                "currency": "KRW" if price is not None else None,
                "imageUrl": detail_image(soup, final_url, source),
                "productCheckedAt": datetime.now(timezone.utc),
                "_errors": [],
            }
            yield item
        except Exception as exc:
            yield {
                "url": url,
                "title": "(피규어팜 상품 수집 실패)",
                "_errors": [f"상세 페이지 실패: {exc}"],
            }


def collect_figurefarm(db, source: dict, store=None) -> dict:
    return save_records(figurefarm_items(source, store), db, source, store)
