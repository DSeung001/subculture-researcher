"""Bounded browser rendering; site selectors live in sources.yaml."""

from bs4 import BeautifulSoup

from subculture.collection.infrastructure.collectors.common import extract_product_fields
from subculture.collection.infrastructure.collectors.html_links import extract_links
from subculture.collection.infrastructure.collectors.http import USER_AGENT, pause_between_requests
from subculture.collection.infrastructure.collectors.images import detail_image, detail_images


def rendered_items(source: dict, policy):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("동적 수집에는 pip install -r requirements.txt 및 python -m playwright install chromium이 필요합니다.") from exc

    selector = source.get("link_selector", "a[href]")
    wait_selector = source.get("wait_selector", selector)
    timeout = int(source.get("render_timeout_seconds", 30)) * 1000
    limit = int(source.get("max_items", 50))
    max_pages = int(source.get("max_pages", 1))
    if timeout <= 0 or max_pages <= 0:
        raise ValueError("render_timeout_seconds와 max_pages는 양수여야 합니다.")
    seen = set()
    blocked = []

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            raise RuntimeError("Chromium 실행 실패. python -m playwright install chromium 설치를 확인하세요.") from exc
        try:
            context = browser.new_context(user_agent=USER_AGENT, service_workers="block")
            context.set_default_timeout(timeout)

            def route_request(route):
                request = route.request
                # Subresources execute as part of page rendering. Never scrape API URLs directly.
                if request.is_navigation_request() and request.frame.parent_frame is None:
                    try:
                        policy.check(request.url)
                    except Exception as exc:
                        blocked.append(str(exc))
                        route.abort()
                        return
                if request.resource_type in {"image", "media", "font"}:
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", route_request)
            listing = context.new_page()
            detail = (
                context.new_page()
                if source.get("product_mode") or source.get("fetch_detail_image")
                else None
            )

            def navigate(page, url, ready_selector):
                policy.check(url)
                blocked.clear()
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                    if response and response.status >= 400:
                        raise RuntimeError(f"HTTP {response.status}: {url}")
                    policy.check(page.url)
                    page.locator(ready_selector).first.wait_for(state="attached", timeout=timeout)
                except Exception as exc:
                    if blocked:
                        raise RuntimeError(blocked[-1]) from exc
                    raise

            navigate(listing, source["url"], wait_selector)
            for page_index in range(max_pages):
                items = list(extract_links(listing.content(), listing.url, source))
                if not items:
                    raise RuntimeError(f"기사 목록이 비어 있습니다. link_selector를 확인하세요: {selector}")
                for item in items:
                    if item["url"] in seen:
                        continue
                    seen.add(item["url"])
                    product_mode = source.get("product_mode", False)
                    detail_image_mode = source.get("fetch_detail_image", False)
                    if product_mode or detail_image_mode:
                        try:
                            pause_between_requests(source)
                            navigate(detail, item["url"], source.get("detail_wait_selector", "h1"))
                            detail_soup = BeautifulSoup(detail.content(), "html.parser")
                            image_url = (
                                detail_image(detail_soup, detail.url, source)
                                if (product_mode or detail_image_mode) else None
                            )
                            if image_url:
                                item["imageUrl"] = image_url
                            if product_mode:
                                # A rendered browser's own innerText already excludes
                                # CSS-hidden stock-state toggles; no need for the
                                # class/style heuristic the static-HTML path uses.
                                # product_text_selector still helps exclude nav/footer
                                # boilerplate that is visible but unrelated to the item.
                                text_selector = source.get("product_text_selector")
                                full_text = detail.locator(text_selector or "body").inner_text()
                                item.update(extract_product_fields(source, full_text, image_url))
                                if source.get("detail_images_selector"):
                                    item["detailImageUrls"] = detail_images(
                                        detail_soup, detail.url, source, exclude=image_url,
                                    )
                        except Exception as exc:
                            item["_errors"].append(f"상세 페이지 실패: {exc}")
                    yield item
                    if len(seen) >= limit:
                        return
                next_selector = source.get("next_page_selector")
                if page_index + 1 >= max_pages or not next_selector:
                    return
                button = listing.locator(next_selector).first
                if not button.count() or not button.is_enabled() or button.get_attribute("aria-disabled") == "true":
                    return
                previous = listing.locator(selector).evaluate_all("nodes => nodes.map(n => n.getAttribute('href'))")
                # For link pagination, enforce robots before clicking as well as on navigation.
                href = button.get_attribute("href")
                if href:
                    from urllib.parse import urljoin
                    policy.check(urljoin(listing.url, href))
                button.click(timeout=timeout)
                listing.wait_for_function(
                    """({selector, previous}) => {
                        const links = Array.from(document.querySelectorAll(selector), n => n.getAttribute('href'));
                        return links.length > 0 && JSON.stringify(links) !== JSON.stringify(previous);
                    }""",
                    arg={"selector": selector, "previous": previous}, timeout=timeout,
                )
                listing.locator(wait_selector).first.wait_for(state="attached", timeout=timeout)
        finally:
            browser.close()
