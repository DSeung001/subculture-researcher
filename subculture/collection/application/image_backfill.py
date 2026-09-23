"""Fill photos on stored documents that have none (`collect.py --backfill-images`).

Only an empty `imageUrl` is ever written; an existing photo is never replaced.
Source: detail pages of sources with `fetch_detail_image` (robots.txt and request
pacing as in collection).
"""

from bs4 import BeautifulSoup

from subculture.collection.infrastructure.collectors.http import RobotsPolicy, get_html
from subculture.collection.infrastructure.collectors.images import detail_image
from subculture.shared.image_urls import http_url

DEFAULT_DETAIL_LIMIT = 60


def backfill_images(db, sources: list[dict], *, detail_limit: int = DEFAULT_DETAIL_LIMIT) -> dict:
    by_name = {source.get("name"): source for source in sources}
    counts = dict(processed=0, updated=0, still_missing=0, failed=0)
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
        source = by_name.get(data.get("source"))
        if source and source.get("fetch_detail_image") and data.get("url"):
            detail_docs.append((snapshot.reference, title, data["url"], source))
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
