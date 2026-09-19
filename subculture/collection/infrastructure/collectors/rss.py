import feedparser
import requests

from subculture.collection.domain.content_rules import normalize_url
from subculture.collection.infrastructure.collectors.common import save_records
from subculture.collection.infrastructure.collectors.http import pause_between_requests, request_headers


def rss_items(source: dict):
    pause_between_requests(source)
    response = requests.get(
        source["url"], headers=request_headers(), timeout=source.get("timeout_seconds", 15),
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"RSS 해석 실패: {feed.get('bozo_exception')}")
    seen = set()
    limit = int(source.get("max_items", 50))
    if limit <= 0:
        return
    for entry in feed.entries:
        if not entry.get("link"):
            continue
        try:
            url = normalize_url(entry.link, response.url)
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        yield {
            "url": url, "title": entry.get("title") or "(untitled)",
            "summary": entry.get("summary", "")[:500],
            "publishedAt": entry.get("published") or entry.get("updated"),
        }
        if len(seen) >= limit:
            return


def collect_rss(db, source: dict, store=None) -> dict:
    return save_records(rss_items(source), db, source, store)
