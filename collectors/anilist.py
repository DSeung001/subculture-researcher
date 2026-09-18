from datetime import datetime, timedelta, timezone

import requests
from firebase_admin import firestore

from collectors.common import save_records
from collectors.http import USER_AGENT


ANILIST_API = "https://graphql.anilist.co"
CACHE_COLLECTION = "collector_state"
CACHE_DOCUMENT = "anilist_trending"
QUERY = """
query TrendingAnime($page: Int!, $perPage: Int!) {
  Page(page: $page, perPage: $perPage) {
    media(
      type: ANIME
      status_in: [RELEASING, NOT_YET_RELEASED]
      sort: TRENDING_DESC
    ) {
      id
      siteUrl
      title {
        romaji
        english
        native
      }
      trending
      popularity
      favourites
      averageScore
      nextAiringEpisode {
        airingAt
        episode
      }
    }
  }
}
"""


def _title(media: dict) -> str:
    titles = media.get("title") or {}
    return titles.get("native") or titles.get("english") or titles.get("romaji") or f"AniList #{media['id']}"


def anilist_items(source: dict):
    limit = max(1, min(int(source.get("max_items", 30)), 50))
    response = requests.post(
        source.get("url") or ANILIST_API,
        json={"query": QUERY, "variables": {"page": 1, "perPage": limit}},
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        timeout=source.get("timeout_seconds", 20),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise ValueError(f"AniList GraphQL 오류: {payload['errors'][0].get('message', payload['errors'][0])}")

    media_list = (((payload.get("data") or {}).get("Page") or {}).get("media")) or []
    checked_at = datetime.now(timezone.utc)
    for media in media_list:
        item = {
            "url": media.get("siteUrl") or f"https://anilist.co/anime/{media['id']}",
            "title": _title(media),
            "externalId": f"anilist:{media['id']}",
            "entityType": "ANIME",
            "trending": media.get("trending"),
            "popularity": media.get("popularity"),
            "favourites": media.get("favourites"),
            "averageScore": media.get("averageScore"),
            "signalCheckedAt": checked_at,
            "_errors": [],
        }
        airing = media.get("nextAiringEpisode") or {}
        if airing.get("airingAt"):
            item["nextAiringAt"] = datetime.fromtimestamp(
                airing["airingAt"], tz=timezone.utc
            ).isoformat()
            item["episode"] = airing.get("episode")
        yield item


def _cache_is_fresh(db, source: dict) -> tuple[bool, datetime | None]:
    if db is None:
        return False, None
    cache_hours = float(source.get("cache_hours", 24))
    snapshot = db.collection(CACHE_COLLECTION).document(CACHE_DOCUMENT).get()
    if not snapshot.exists:
        return False, None
    data = snapshot.to_dict() or {}
    last_success = data.get("lastSuccessAt")
    if not isinstance(last_success, datetime):
        return False, None
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)
    return (
        datetime.now(timezone.utc) - last_success < timedelta(hours=cache_hours),
        last_success,
    )


def collect_anilist(db, source: dict, store=None) -> dict:
    cached, last_success = _cache_is_fresh(db, source)
    if cached:
        checked = last_success.isoformat() if last_success else "unknown"
        return {
            "processed": 0,
            "inserted": 0,
            "existing": 0,
            "updated": 0,
            "failed": 0,
            "skipped": 1,
            "reason": f"AniList 캐시 사용: 마지막 성공 {checked}",
            "errors": [],
        }

    result = save_records(anilist_items(source), db, source, store)
    if db is not None and result.get("failed", 0) == 0:
        db.collection(CACHE_COLLECTION).document(CACHE_DOCUMENT).set(
            {
                "lastSuccessAt": firestore.SERVER_TIMESTAMP,
                "cacheHours": float(source.get("cache_hours", 24)),
                "source": source.get("name"),
            },
            merge=True,
        )
    return result
