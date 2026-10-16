"""Fetch listing/detail HTML for the local extract picker (robots-aware)."""

from subculture.collection.infrastructure.collectors.common import RobotsDenied
from subculture.collection.infrastructure.collectors.http import RobotsPolicy, get_html
from subculture.collection.infrastructure.preview_html import sanitize_preview_html


def fetch_page_html(source: dict, url: str | None = None) -> tuple[str, str]:
    """Return (html, final_url) for `url` or the source listing URL."""
    target = (url or source.get("url") or "").strip()
    if not target:
        raise ValueError("URL이 필요합니다.")
    policy = RobotsPolicy(
        source.get("respect_robots", True),
        source.get("timeout_seconds", 15),
        source,
    )
    if source.get("render_js"):
        return _render_html(source, target, policy)
    return get_html(target, policy, source.get("timeout_seconds", 15), source)


def _render_html(source: dict, url: str, policy: RobotsPolicy) -> tuple[str, str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "JS 렌더 미리보기에는 pip install -r requirements.txt 및 "
            "python -m playwright install chromium이 필요합니다."
        ) from exc

    from subculture.collection.infrastructure.collectors.http import USER_AGENT
    from subculture.collection.infrastructure.collectors.rendered import _list_wait_selector

    wait_selector = source.get("detail_wait_selector") if url != source.get("url") else None
    wait_selector = wait_selector or _list_wait_selector(source)
    timeout = int(source.get("render_timeout_seconds", 30)) * 1000
    blocked: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT, service_workers="block")
            context.set_default_timeout(timeout)

            def route_request(route):
                request = route.request
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
            page = context.new_page()
            policy.check(url)
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if response and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}: {url}")
            policy.check(page.url)
            try:
                page.locator(wait_selector).first.wait_for(state="attached", timeout=timeout)
            except Exception:
                if blocked:
                    raise RuntimeError(blocked[-1])
                # Still return HTML so the user can pick without a ready selector.
            if blocked:
                raise RobotsDenied(blocked[-1])
            return page.content(), page.url
        finally:
            browser.close()


def preview_document(source: dict, url: str | None = None) -> tuple[str, str]:
    """Sanitized HTML ready for same-origin iframe embedding."""
    html, final_url = fetch_page_html(source, url)
    return sanitize_preview_html(html, final_url), final_url
