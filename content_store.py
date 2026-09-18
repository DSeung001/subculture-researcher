"""One URL identity and atomic write path for every collector and manual entry."""

import hashlib
from datetime import datetime, timezone
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from translate import enrich_translation


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "dclid", "msclkid",
}
METRICS = ("viewCount", "likeCount")
SIGNAL_FIELDS = (
    "trending", "popularity", "favourites", "averageScore",
    "nextAiringAt", "episode", "signalCheckedAt",
)


def normalize_url(url: str, base_url: str = "") -> str:
    parsed = urlsplit(urljoin(base_url, url.strip()))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("http:// 또는 https:// 기사 URL을 입력해주세요.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("인증 정보가 포함된 URL은 저장할 수 없습니다.")
    # Validate the port, but preserve it along with path/query spelling and order.
    _ = parsed.port
    query = "&".join(
        part for part in parsed.query.split("&")
        if unquote_plus(part.split("=", 1)[0]).lower() not in TRACKING_PARAMS
    )
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, query, ""))


def doc_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def category_collection(db, category: str):
    """Each category lives in its own Firestore collection: categories/{CATEGORY}/contents."""
    return db.collection("categories").document(category or "UNKNOWN").collection("contents")


class ContentStore:
    def __init__(self, db=None):
        """db=None is an isolated dry run; no Firestore access or credentials."""
        self.db = db
        self.by_url: dict[str, list[dict]] = {}
        self.invalid_urls: list[str] = []
        self.preview: list[dict] = []
        if db is not None:
            # collection_group reads every category's "contents" subcollection in one query.
            for snapshot in db.collection_group("contents").select(["url", "status"]).stream():
                data = snapshot.to_dict() or {}
                try:
                    url = normalize_url(data.get("url") or "")
                except ValueError:
                    self.invalid_urls.append(snapshot.id)
                    continue
                self.by_url.setdefault(url, []).append(
                    {"id": snapshot.id, "status": data.get("status"), "ref": snapshot.reference}
                )

    def duplicates(self) -> list[dict]:
        return [
            {
                "url": url,
                "documents": sorted(
                    ({"id": d["id"], "status": d["status"]} for d in docs),
                    key=lambda d: d["id"],
                ),
            }
            for url, docs in sorted(self.by_url.items()) if len(docs) > 1
        ]

    def save(self, item: dict) -> dict[str, int]:
        url = normalize_url(item["url"])
        canonical_id = doc_id(url)
        existing = self.by_url.get(url, [])
        # All processes choose the same legacy document, without changing its ID.
        target = min(
            existing,
            key=lambda doc: (doc["id"] != canonical_id, doc["id"]),
            default=None,
        )
        target_id = target["id"] if target else canonical_id
        category = item.get("category") or "UNKNOWN"
        metrics = {}
        for field in METRICS:
            value = item.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                metrics[field] = value
                metrics[f"{field}CheckedAt"] = item.get(f"{field}CheckedAt") or datetime.now(timezone.utc)

        signals = {
            field: item.get(field)
            for field in SIGNAL_FIELDS
            if item.get(field) is not None
        }

        data = {
            **{k: v for k, v in item.items() if not k.startswith("_")},
            "url": url,
            "status": "NEW",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "collectedAt": firestore.SERVER_TIMESTAMP,
        }
        for field in METRICS:
            data[field] = metrics.get(field)
            data.pop(f"{field}CheckedAt", None)
        data.update(metrics)

        created = False
        ref = None
        if self.db is None:
            created = not existing
            self.preview.append({k: v for k, v in data.items() if k != "collectedAt"})
        else:
            # A document keeps living in the category collection it was first saved under.
            ref = target["ref"] if target else category_collection(self.db, category).document(target_id)
            if not existing:
                data.update(enrich_translation(item))
                try:
                    ref.create(data)
                    created = True
                except AlreadyExists:
                    # Another collector/manual submission created this URL first.
                    pass
            updates = {**metrics, **signals}
            if not created and updates:
                ref.update(updates)

        if not existing:
            self.by_url[url] = [{"id": target_id, "status": "NEW" if created else None, "ref": ref}]
        return {
            "inserted": int(created),
            "existing": int(not created),
            "updated": int(not created and bool(metrics or signals)),
        }


def add_manual_content(
    db, url: str, title: str, category: str, angle: str, source_tier: str = "MEDIA",
) -> bool:
    # Refresh the legacy index on submission, not on every page render.
    result = ContentStore(db).save({
        "url": url, "title": title.strip() or "(제목 없음)", "summary": "",
        "source": "수동 입력", "sourceType": "manual", "category": category,
        "contentAngle": angle, "sourceTier": source_tier,
        "note": "", "postedAt": None, "publishedAt": None,
    })
    return bool(result["inserted"])
