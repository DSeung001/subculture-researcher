from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from collectors.common import RobotsDenied


USER_AGENT = "SubcultureResearcher/0.1 (+https://github.com/DSeung001/subculture-researcher)"


class RobotsPolicy:
    def __init__(self, enabled=True, timeout=15):
        self.enabled = enabled
        self.timeout = timeout
        self.cache = {}

    def check(self, url: str):
        if not self.enabled:
            return
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.cache:
            parser, reason = None, ""
            try:
                response = requests.get(f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
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


def get_html(url: str, policy: RobotsPolicy, timeout: int = 15) -> tuple[str, str]:
    # Check each redirect destination before requesting it.
    from urllib.parse import urljoin

    for _ in range(10):
        policy.check(url)
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=False)
        response.raise_for_status()
        if response.is_redirect:
            url = urljoin(url, response.headers["Location"])
            continue
        return response.text, response.url
    raise RuntimeError("페이지 리디렉션 횟수를 초과했습니다.")
