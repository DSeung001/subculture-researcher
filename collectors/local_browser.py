"""Slow local-only Playwright collector using a persistent browser profile.

This collector is intentionally interactive/headed. Authentication, MFA and bot
challenges are completed by the user in the opened browser; the collector does
not attempt to bypass them.
"""

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from collectors.common import save_records
from content_store import normalize_url


PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+)\s*원")
ABSOLUTE_URL_RE = re.compile(r"https?://[^\s'\"<>]+")
PREORDER_WORDS = ("예약", "PRE-ORDER", "PREORDER", "予約")
SOLD_OUT_WORDS = ("품절", "SOLD OUT", "판매 종료", "마감")


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


def _product_fields(source: dict, text: str, locator=None) -> dict:
    values = [int(value.replace(",", "")) for value in PRICE_RE.findall(text)]
    price = next((value for value in values if value >= 1000), None)
    upper = text.upper()
    if any(word.upper() in upper for word in SOLD_OUT_WORDS):
        status = "SOLD_OUT"
    elif any(word.upper() in upper for word in PREORDER_WORDS):
        status = "PREORDER"
    else:
        status = "IN_STOCK"

    deadline = None
    if any(word in text for word in ("예약", "마감", "종료")):
        match = KOREAN_DATE_RE.search(text)
        if match:
            year, month, day = map(int, match.groups())
            deadline = f"{year:04d}-{month:02d}-{day:02d}"

    image_url = None
    if locator is not None:
        try:
            image_url = locator.evaluate(
                """el => {
                    const node = el.closest('article, li, section, div') || el.parentElement || el;
                    const img = node.querySelector('img');
                    return img ? (img.currentSrc || img.src || null) : null;
                }"""
            )
        except Exception:
            image_url = None

    return {
        "entityType": "PRODUCT",
        "shop": source.get("shop") or source["name"],
        "saleStatus": status,
        "price": price,
        "currency": "KRW" if price is not None else None,
        "preorderEndAt": deadline,
        "imageUrl": image_url,
        "productCheckedAt": datetime.now(timezone.utc),
    }


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
                print()
                print(f"[로컬 브라우저] {source['name']}")
                print(source.get(
                    "interactive_message",
                    "로그인/인증/원하는 화면 이동을 마친 뒤 터미널에서 Enter를 누르세요.",
                ))
                try:
                    input("> 준비되면 Enter: ")
                except EOFError:
                    print("[로컬 브라우저] 입력을 받을 수 없어 현재 페이지에서 계속합니다.")

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
                if source.get("product_mode", False):
                    item.update(_product_fields(source, context_text, locator))

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
