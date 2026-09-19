from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import random
import time

import requests

from collectors.common import RobotsDenied


# Identifies the collector for robots.txt; still send browser-like Accept headers.
USER_AGENT = "SubcultureResearcher/0.1 (+https://github.com/DSeung001/subculture-researcher)"
# Default gap between HTTP fetches so detail-page loops are not a burst.
DEFAULT_REQUEST_DELAY = (1.5, 3.5)
_last_fetch_at = 0.0


def request_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
    }


def request_delay_range(source: dict | None = None) -> tuple[float, float]:
    source = source or {}
    lo = float(source.get("request_delay_min_seconds", DEFAULT_REQUEST_DELAY[0]))
    hi = float(source.get("request_delay_max_seconds", DEFAULT_REQUEST_DELAY[1]))
    if hi < lo:
        lo, hi = hi, lo
    return max(0.0, lo), max(0.0, hi)


def pause_between_requests(source: dict | None = None) -> float:
    """Wait a jittered gap since the previous HTTP fetch. Returns seconds slept."""
    global _last_fetch_at
    lo, hi = request_delay_range(source)
    if hi <= 0:
        _last_fetch_at = time.monotonic()
        return 0.0
    elapsed = time.monotonic() - _last_fetch_at
    wait = random.uniform(lo, hi) - elapsed
    if wait > 0:
        time.sleep(wait)
    else:
        wait = 0.0
    _last_fetch_at = time.monotonic()
    return wait


class RobotsPolicy:
    def __init__(self, enabled=True, timeout=15, source: dict | None = None):
        self.enabled = enabled
        self.timeout = timeout
        self.source = source
        self.cache = {}

    def check(self, url: str):
        if not self.enabled:
            return
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.cache:
            parser, reason = None, ""
            try:
                pause_between_requests(self.source)
                response = requests.get(
                    f"{origin}/robots.txt",
                    headers=request_headers(),
                    timeout=self.timeout,
                )
                if response.status_code == 404:
                    parser = True
                elif response.status_code >= 400:
                    reason = f"robots.txt 응답 오류: HTTP {response.status_code}"
                else:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
            except requests.RequestException as exc:
                reason = f"robots.txt를 확인할 수 없음: {exc}"
            self.cache[origin] = (parser, reason)
        parser, reason = self.cache[origin]
        if parser is True:
            return
        if parser is None or not parser.can_fetch(USER_AGENT, url):
            raise RobotsDenied(f"{url}: {reason or 'robots.txt에서 자동 수집을 허용하지 않음'}")


def get_html(url: str, policy: RobotsPolicy, timeout: int = 15, source: dict | None = None) -> tuple[str, str]:
    # Check each redirect destination before requesting it.
    from urllib.parse import urljoin

    source = source if source is not None else getattr(policy, "source", None)
    for _ in range(10):
        policy.check(url)
        pause_between_requests(source)
        response = requests.get(
            url, headers=request_headers(), timeout=timeout, allow_redirects=False,
        )
        response.raise_for_status()
        if response.is_redirect:
            url = urljoin(url, response.headers["Location"])
            continue
        return response.text, response.url
    raise RuntimeError("페이지 리디렉션 횟수를 초과했습니다.")
