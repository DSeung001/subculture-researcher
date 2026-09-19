"""One URL identity and atomic write path for every collector and manual entry."""

import hashlib
from datetime import datetime, timezone
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from translate import enrich_translation
from content_model import category_collection
from image_urls import http_url


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
PRODUCT_FIELDS = (
    "entityType", "shop", "saleStatus", "preorderEndAt", "releaseWindowText",
    "manufacturer", "sizeText", "price", "currency", "imageUrl", "productCheckedAt",
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
        # Only plain http(s) image links are ever stored or rendered.
        image_url = http_url(item.get("imageUrl"))
        item = {k: v for k, v in item.items() if k != "imageUrl"}
        if image_url:
            item["imageUrl"] = image_url
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
        product_fields = {
            field: item.get(field)
            for field in PRODUCT_FIELDS
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
            updates = {**metrics, **signals, **product_fields}
            if not created and updates:
                ref.update(updates)

        if not existing:
            self.by_url[url] = [{"id": target_id, "status": "NEW" if created else None, "ref": ref}]
        return {
            "inserted": int(created),
            "existing": int(not created),
            "updated": int(not created and bool(metrics or signals or product_fields)),
        }


# Shops whose product URLs are saved by hand as products: (host, path prefix, source label, shop).
# The Naver brand store is here because its robots.txt forbids automatic collection.
MANUAL_SHOPS = (
    ("laftel.net", "", "Laftel Store", "Laftel"),
    ("brand.naver.com", "/kotobukiyamall", "Kotobukiya Mall (Naver)", "코토부키야 몰(네이버)"),
)


def manual_shop(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    for suffix, prefix, source, shop in MANUAL_SHOPS:
        if (host == suffix or host.endswith("." + suffix)) and parsed.path.startswith(prefix):
            return source, shop
    return None


def add_manual_content(
    db, url: str, title: str, category: str, angle: str, source_tier: str = "MEDIA",
    image_url: str = "",
) -> bool:
    # Refresh the legacy index on submission, not on every page render.
    normalized = normalize_url(url)
    image_url = (image_url or "").strip()
    if image_url and not http_url(image_url):
        raise ValueError("이미지 URL은 http:// 또는 https:// 주소여야 합니다.")
    shop = manual_shop(normalized) if category == "FIGURE" else None
    result = ContentStore(db).save({
        "url": normalized, "title": title.strip() or "(제목 없음)", "summary": "",
        "source": shop[0] if shop else "수동 입력",
        "sourceType": "manual_product" if shop else "manual",
        "category": category,
        "contentAngle": angle, "sourceTier": source_tier,
        "entityType": "PRODUCT" if shop else None,
        "shop": shop[1] if shop else None,
        "saleStatus": "UNKNOWN" if shop else None,
        "imageUrl": image_url or None,
        "note": "", "postedAt": None, "publishedAt": None,
    })
    return bool(result["inserted"])
