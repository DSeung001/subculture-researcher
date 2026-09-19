"""Fill photos on stored documents that have none (`collect.py --backfill-images`).

Only an empty `imageUrl` is ever written; an existing photo is never replaced.
Sources: a YouTube video URL (thumbnail derived from the id), AniList media ids
(one batched API call per 50) and detail pages of sources with `fetch_detail_image`
(robots.txt and request pacing as in collection).
"""

from bs4 import BeautifulSoup

from collectors.anilist import anilist_covers
from collectors.http import RobotsPolicy, get_html
from collectors.images import detail_image
from collectors.youtube_feed import youtube_thumbnail
from image_urls import http_url

DEFAULT_DETAIL_LIMIT = 60
ANILIST_PREFIX = "anilist:"


def _anilist_id(data: dict) -> int | None:
    external = data.get("externalId") or ""
    if external.startswith(ANILIST_PREFIX) and external[len(ANILIST_PREFIX):].isdigit():
        return int(external[len(ANILIST_PREFIX):])
    return None


def backfill_images(db, sources: list[dict], *, detail_limit: int = DEFAULT_DETAIL_LIMIT) -> dict:
    by_name = {source.get("name"): source for source in sources}
    anilist_source = next((s for s in sources if s.get("type") == "anilist"), {})
    counts = dict(processed=0, updated=0, still_missing=0, failed=0)
    anilist_docs: dict[int, list] = {}
    detail_docs = []

    def fill(reference, url: str, title: str):
        reference.update({"imageUrl": url})
        counts["updated"] += 1
        print(f"[이미지] {title} -> {url}")

    for snapshot in db.collection_group("contents").stream():
        data = snapshot.to_dict() or {}
        if http_url(data.get("imageUrl")):
            continue
        counts["processed"] += 1
        title = data.get("title") or data.get("url") or snapshot.id
        thumbnail = youtube_thumbnail(data.get("url") or "")
        media_id = _anilist_id(data)
        source = by_name.get(data.get("source"))
        if thumbnail:
            fill(snapshot.reference, thumbnail, title)
        elif media_id is not None:
            anilist_docs.setdefault(media_id, []).append((snapshot.reference, title))
        elif source and source.get("fetch_detail_image") and data.get("url"):
            detail_docs.append((snapshot.reference, title, data["url"], source))
        else:
            counts["still_missing"] += 1

    if anilist_docs:
        try:
            covers = anilist_covers(list(anilist_docs), anilist_source)
        except Exception as exc:
            counts["failed"] += sum(len(docs) for docs in anilist_docs.values())
            print(f"[오류] AniList 표지 조회 실패: {exc}")
            covers = {}
        for media_id, docs in anilist_docs.items():
            for reference, title in docs:
                if media_id in covers:
                    fill(reference, covers[media_id], title)
                else:
                    counts["still_missing"] += 1

    policies: dict[str, RobotsPolicy] = {}
    for position, (reference, title, url, source) in enumerate(detail_docs):
        if position >= detail_limit:
            counts["still_missing"] += len(detail_docs) - position
            print(f"[중단] 상세 페이지 {detail_limit}건 제한. 나머지는 다시 실행하세요.")
            break
        policy = policies.setdefault(source["name"], RobotsPolicy(
            source.get("respect_robots", True), source.get("timeout_seconds", 15), source))
        try:
            html, final_url = get_html(url, policy, source.get("timeout_seconds", 15), source)
            photo = detail_image(BeautifulSoup(html, "html.parser"), final_url, source)
        except Exception as exc:
            counts["failed"] += 1
            print(f"[오류] {url}: {exc}")
            continue
        if photo:
            fill(reference, photo, title)
        else:
            counts["still_missing"] += 1

    print(
        "이미지 보완 종료: " + " ".join(f"{key}={value}" for key, value in counts.items())
    )
    return counts
