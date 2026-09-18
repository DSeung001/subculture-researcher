import re
from datetime import datetime, timezone
from decimal import Decimal

from bs4 import BeautifulSoup

from content_store import METRICS, normalize_url
from collectors.common import save_records
from collectors.http import RobotsPolicy, get_html


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
        if len(title) < int(source.get("min_title_length", 4)):
            continue
        item = {"url": url, "title": title, "publishedAt": None, "_errors": []}
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
                    item["_errors"].append(f"게시일 형식 오류: {date}")
        values, errors = extract_metrics(anchor, source.get("list_metrics", {}))
        item.update(values)
        item["_errors"].extend(errors)
        yield item


def html_items(source: dict):
    limit = int(source.get("max_items", 50))
    if limit <= 0:
        return
    policy = RobotsPolicy(source.get("respect_robots", True), source.get("timeout_seconds", 15))
    policy.check(source["url"])
    if source.get("render_js", False):
        # Static/RSS/manual paths do not import or launch Playwright.
        from collectors.rendered import rendered_items
        yield from rendered_items(source, policy)
        return
    html, final_url = get_html(source["url"], policy, source.get("timeout_seconds", 15))
    seen = set()
    for item in extract_links(html, final_url, source):
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        detail_selectors = {k: v for k, v in source.get("detail_metrics", {}).items() if k not in item}
        if detail_selectors:
            try:
                detail_html, _ = get_html(item["url"], policy, source.get("timeout_seconds", 15))
                values, errors = extract_metrics(BeautifulSoup(detail_html, "html.parser"), detail_selectors, required=True)
                item.update(values)
                item["_errors"].extend(errors)
            except Exception as exc:
                item["_errors"].append(f"상세 페이지 실패: {exc}")
        yield item
        if len(seen) >= limit:
            break


def collect_html_links(db, source: dict, store=None) -> dict:
    return save_records(html_items(source), db, source, store)
