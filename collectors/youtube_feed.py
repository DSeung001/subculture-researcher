import re

import feedparser
import requests

from collectors.common import save_records
from collectors.http import USER_AGENT
from content_store import normalize_url


CHANNEL_ID_RE = re.compile(r'UC[0-9A-Za-z_-]{22}')
CHANNEL_URL_RE = re.compile(r'(?:youtube\.com|youtu\.be)/channel/(UC[0-9A-Za-z_-]{22})')
HTML_CHANNEL_ID_RE = re.compile(
    r'(?:"(?:channelId|externalId|browseId)"\s*:\s*"|/channel/)(UC[0-9A-Za-z_-]{22})'
)


def _channel_id_from_text(text: str, pattern: re.Pattern) -> str | None:
    match = pattern.search(text or "")
    if not match:
        return None
    return match.group(1) if match.lastindex else match.group(0)


def _resolve_channel_id(source: dict) -> str:
    configured = (source.get("channel_id") or "").strip()
    if CHANNEL_ID_RE.fullmatch(configured):
        return configured

    channel_url = source.get("channel_url") or source.get("url") or ""
    from_url = _channel_id_from_text(channel_url, CHANNEL_URL_RE)
    if from_url:
        return from_url

    response = requests.get(
        channel_url,
        headers={"User-Agent": USER_AGENT},
        timeout=source.get("timeout_seconds", 15),
    )
    response.raise_for_status()
    match = HTML_CHANNEL_ID_RE.search(response.text)
    if not match:
        raise ValueError(f"YouTube channel ID를 찾을 수 없음: {channel_url}")
    return match.group(1)


def youtube_feed_items(source: dict):
    channel_id = _resolve_channel_id(source)
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    response = requests.get(
        feed_url,
        headers={"User-Agent": USER_AGENT},
        timeout=source.get("timeout_seconds", 15),
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"YouTube RSS 해석 실패: {feed.get('bozo_exception')}")

    limit = max(1, int(source.get("max_items", 15)))
    for entry in feed.entries[:limit]:
        link = entry.get("link")
        if not link:
            continue
        yield {
            "url": normalize_url(link),
            "title": entry.get("title") or "(untitled)",
            "summary": (entry.get("summary") or "")[:500],
            "publishedAt": entry.get("published") or entry.get("updated"),
            "entityType": "VIDEO",
            "channelId": channel_id,
            "_errors": [],
        }


def collect_youtube_feed(db, source: dict, store=None) -> dict:
    return save_records(youtube_feed_items(source), db, source, store)
