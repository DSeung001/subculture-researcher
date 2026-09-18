from datetime import datetime, timezone

import requests

from collectors.common import save_records
from collectors.http import USER_AGENT


ANILIST_API = "https://graphql.anilist.co"
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


def collect_anilist(db, source: dict, store=None) -> dict:
    return save_records(anilist_items(source), db, source, store)
