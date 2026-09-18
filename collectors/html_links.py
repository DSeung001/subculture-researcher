import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from firebase_admin import firestore


USER_AGENT = (
    "SubcultureResearcher/0.1 "
    "(+https://github.com/DSeung001/subculture-researcher)"
)
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


def _doc_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _normalize_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, href)
    absolute, _ = urldefrag(absolute)
    parsed = urlparse(absolute)

    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in TRACKING_PARAMS
    ]

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            urlencode(query, doseq=True),
            "",
        )
    )


def _robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    parser = RobotFileParser()
    parser.set_url(robots_url)

    try:
        parser.read()
        return parser.can_fetch(USER_AGENT, url)
    except Exception:
        # 보수적으로 동작한다. robots.txt 확인에 실패하면 자동 수집하지 않는다.
        return False


def _matches(url: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    return any(re.search(pattern, url) for pattern in patterns)


def collect_html_links(db, source: dict) -> dict[str, int]:
    source_url = source["url"]

    if source.get("respect_robots", True) and not _robots_allows(source_url):
        return {
            "processed": 0,
            "inserted": 0,
            "skipped": 1,
            "reason": "robots.txt에서 자동 수집을 허용하지 않거나 확인할 수 없음",
        }

    response = requests.get(
        source_url,
        headers={"User-Agent": USER_AGENT},
        timeout=source.get("timeout_seconds", 15),
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    selector = source.get("link_selector", "a[href]")
    allow_patterns = source.get("allow_patterns", [])
    deny_patterns = source.get("deny_patterns", [])
    max_items = int(source.get("max_items", 50))
    min_title_length = int(source.get("min_title_length", 4))

    processed = 0
    inserted = 0
    seen_urls: set[str] = set()

    for anchor in soup.select(selector):
        href = anchor.get("href")
        if not href:
            continue

        url = _normalize_url(source_url, href)

        if url in seen_urls:
            continue
        if not _matches(url, allow_patterns):
            continue
        if deny_patterns and _matches(url, deny_patterns):
            continue

        title = " ".join(anchor.get_text(" ", strip=True).split())
        if len(title) < min_title_length:
            continue

        seen_urls.add(url)
        processed += 1

        ref = db.collection("contents").document(_doc_id(url))
        if ref.get().exists:
            if processed >= max_items:
                break
            continue

        ref.set(
            {
                "url": url,
                "title": title,
                "summary": "",
                "source": source["name"],
                "sourceType": "html",
                "sourceUrl": source_url,
                "region": source.get("region"),
                "category": source.get("category", "UNKNOWN"),
                "contentAngle": source.get("content_angle", "NEWS"),
                "status": "NEW",
                "publishedAt": None,
                "collectedAt": firestore.SERVER_TIMESTAMP,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )
        inserted += 1

        if processed >= max_items:
            break

    return {
        "processed": processed,
        "inserted": inserted,
        "skipped": 0,
        "reason": "",
    }
