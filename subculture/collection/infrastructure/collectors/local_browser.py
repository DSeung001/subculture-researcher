"""Slow local-only Playwright collector using a persistent browser profile.

This collector is intentionally headed. Authentication, MFA and bot challenges
are completed by the user in the opened browser during a random ready wait;
the collector does not attempt to bypass them.
"""

import random
import re
import time
from pathlib import Path

from subculture.collection.infrastructure.collectors.common import extract_product_fields, save_records
from subculture.collection.infrastructure.collectors.images import MIN_SIDE
from subculture.collection.domain.content_rules import normalize_url
from subculture.shared.image_urls import clean_image_url


ABSOLUTE_URL_RE = re.compile(r"https?://[^\s'\"<>]+")
QUOTED_PATH_RE = re.compile(r"['\"](/[^'\"\s<>]*)['\"]")


def _matches_any(patterns: list[str], text: str) -> bool:
    return not patterns or any(re.search(pattern, text, re.I) for pattern in patterns)


def _extract_candidate_url(locator, base_url: str) -> str | None:
    for attribute in ("href", "data-href", "data-url"):
        value = locator.get_attribute(attribute)
        if value and not value.lower().startswith("javascript:"):
            try:
                return normalize_url(value, base_url)
            except ValueError:
                pass

    onclick = locator.get_attribute("onclick") or ""
    match = ABSOLUTE_URL_RE.search(onclick)
    if match:
        try:
            return normalize_url(match.group(0), base_url)
        except ValueError:
            return None
    relative = QUOTED_PATH_RE.search(onclick)
    if relative:
        try:
            return normalize_url(relative.group(1), base_url)
        except ValueError:
            return None
    return None


def _context_text(locator) -> str:
    try:
        return locator.evaluate(
            """el => {
                const node = el.closest('article, li, section, div') || el.parentElement || el;
                return (node.innerText || el.innerText || '').trim();
            }"""
        )
    except Exception:
        try:
            return locator.inner_text()
        except Exception:
            return ""


def _title(locator, context: str) -> str:
    try:
        text = " ".join(locator.inner_text().split())
    except Exception:
        text = ""
    if len(text) >= 4:
        return text[:300]
    for line in context.splitlines():
        line = " ".join(line.split())
        if len(line) >= 4:
            return line[:300]
    return "(제목 없음)"


CARD_IMAGES_JS = """(el, selector) => {
    // Grow from the link to the widest ancestor that still holds only this item's links.
    const found = [];
    let node = el;
    for (let depth = 0; node && depth < 6; depth += 1) {
        if (depth > 0) {
            const links = new Set(Array.from(node.querySelectorAll('a[href]'), a => a.href));
            if (links.size > 1) break;
        }
        node.querySelectorAll(selector).forEach(img => {
            if (found.some(f => f.el === img)) return;
            found.push({
                el: img,
                lazy: img.getAttribute('data-src') || img.getAttribute('data-original') || '',
                src: img.currentSrc || img.getAttribute('src') || '',
                width: img.naturalWidth || 0,
                height: img.naturalHeight || 0,
            });
        });
        if (found.length) break;
        node = node.parentElement;
    }
    return found.map(({el, ...rest}) => rest);
}"""


def _card_image(source: dict, locator, page_url: str) -> str | None:
    """First real photo on the item's card; logos, icons and placeholders are skipped."""
    selector = source.get("list_image_selector") or "img"
    deny = source.get("image_deny_patterns", [])
    try:
        candidates = locator.evaluate(CARD_IMAGES_JS, selector)
    except Exception:
        return None
    for candidate in candidates or []:
        width, height = candidate.get("width") or 0, candidate.get("height") or 0
        if width and height and width < MIN_SIDE and height < MIN_SIDE:
            continue
        url = clean_image_url(candidate.get("lazy") or candidate.get("src"), page_url, deny)
        if url:
            return url
    return None


def _product_fields(source: dict, text: str, image_url: str | None = None) -> dict:
    return extract_product_fields(source, text, image_url)


def _ready_wait_seconds(source: dict) -> float:
    lo = float(source.get("ready_wait_min_seconds", 25))
    hi = float(source.get("ready_wait_max_seconds", 45))
    if hi < lo:
        lo, hi = hi, lo
    return random.uniform(lo, hi)


def _wait_until_ready(source: dict) -> None:
    if not source.get("interactive_ready", False):
        return
    wait = _ready_wait_seconds(source)
    print()
    print(f"[로컬 브라우저] {source['name']}")
    print(source.get(
        "interactive_message",
        "로그인/인증/원하는 화면 이동을 마친 뒤 대기하세요.",
    ))
    print(f"> {wait:.0f}초 후 현재 페이지에서 수집을 시작합니다.")
    time.sleep(wait)


def local_browser_items(source: dict):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "로컬 브라우저 수집에는 playwright 설치와 chromium 설치가 필요합니다."
        ) from exc

    profile_name = source.get("browser_profile") or re.sub(
        r"[^a-zA-Z0-9_-]+", "-", source["name"]
    ).strip("-").lower()
    profile_dir = Path(source.get("profile_dir") or ".local/playwright") / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    timeout_ms = int(source.get("render_timeout_seconds", 45)) * 1000
    slow_mo = int(source.get("slow_mo_ms", 250))
    selector = source.get("link_selector", "a[href], [data-href], [data-url]")
    max_items = max(1, int(source.get("max_items", 30)))
    scroll_steps = max(0, int(source.get("scroll_steps", 6)))
    scroll_delay = max(0.5, float(source.get("scroll_delay_seconds", 3)))
    item_delay = max(0.0, float(source.get("item_delay_seconds", 0.7)))
    allow_patterns = source.get("allow_patterns", [])
    deny_patterns = source.get("deny_patterns", [])
    required_text_patterns = source.get("required_text_patterns", [])

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            slow_mo=slow_mo,
            viewport=None,
            args=["--start-maximized"],
        )
        context.set_default_timeout(timeout_ms)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(source["url"], wait_until="domcontentloaded", timeout=timeout_ms)

            wait_selector = source.get("wait_selector")
            if wait_selector:
                page.locator(wait_selector).first.wait_for(
                    state="attached", timeout=timeout_ms
                )

            if source.get("interactive_ready", False):
                _wait_until_ready(source)

            for _ in range(scroll_steps):
                page.mouse.wheel(0, int(source.get("scroll_pixels", 1400)))
                time.sleep(scroll_delay)

            seen = set()
            locators = page.locator(selector)
            count = min(locators.count(), int(source.get("max_candidates", 600)))
            for index in range(count):
                locator = locators.nth(index)
                try:
                    if not locator.is_visible():
                        continue
                except Exception:
                    continue

                url = _extract_candidate_url(locator, page.url)
                if not url or url in seen:
                    continue
                if allow_patterns and not _matches_any(allow_patterns, url):
                    continue
                if deny_patterns and _matches_any(deny_patterns, url):
                    continue

                context_text = _context_text(locator)
                searchable = f"{url}\n{context_text}"
                if required_text_patterns and not _matches_any(
                    required_text_patterns, searchable
                ):
                    continue

                item = {
                    "url": url,
                    "title": _title(locator, context_text),
                    "summary": " ".join(context_text.split())[:500],
                    "publishedAt": None,
                    "_errors": [],
                }
                if source.get("product_mode", False) or source.get("list_image_selector"):
                    image_url = _card_image(source, locator, page.url)
                    if image_url:
                        item["imageUrl"] = image_url
                if source.get("product_mode", False):
                    item.update(_product_fields(source, context_text, item.get("imageUrl")))

                seen.add(url)
                yield item
                if len(seen) >= max_items:
                    return
                if item_delay:
                    time.sleep(item_delay)
        finally:
            context.close()


def collect_local_browser(db, source: dict, store=None) -> dict:
    return save_records(local_browser_items(source), db, source, store)
