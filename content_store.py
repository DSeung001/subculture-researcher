"""One URL identity and atomic write path for every collector and manual entry."""

import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from translate import enrich_translation
from content_model import category_collection, content_id
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
# Also carries imageUrl/detailCheckedAt: these refresh on re-collection of an existing document.
PRODUCT_FIELDS = (
    "entityType", "shop", "saleStatus", "preorderEndAt", "releaseWindowText",
    "manufacturer", "sizeText", "price", "currency", "imageUrl", "productCheckedAt",
    "detailCheckedAt",
)
# Fields read into the per-run URL index so collectors can skip detail pages they need not refetch.
INDEX_FIELDS = ("url", "status", "imageUrl", "price", "productCheckedAt", "detailCheckedAt")
DEFAULT_DETAIL_REFRESH_HOURS = 72.0


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


UNTITLED_TITLE = "(제목 없음)"
_X_STATUS_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}


def is_untitled_x_post(url: str, title: str) -> bool:
    """True only for X/Twitter status URLs stored with the untitled placeholder."""
    if (title or "") != UNTITLED_TITLE:
        return False
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host not in _X_STATUS_HOSTS:
        return False
    return "/status/" in (parsed.path or "")


_LAFTEL_HOSTS = {"laftel.net", "www.laftel.net"}


def is_untitled_laftel_home(url: str, title: str) -> bool:
    """True only for the bare laftel.net home stored with the untitled placeholder.

    The retired 「라프텔 인기·신작」 browser collection left these behind; real
    Laftel product pages have their own path and title.
    """
    if (title or "") != UNTITLED_TITLE:
        return False
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return False
    return (parsed.hostname or "").lower() in _LAFTEL_HOSTS and parsed.path in ("", "/")


def is_untitled_leftover(url: str, title: str) -> bool:
    return is_untitled_x_post(url, title) or is_untitled_laftel_home(url, title)


def delete_untitled_x_contents(db, *, dry_run: bool = False) -> dict:
    """Delete Firestore leftovers stored with title '(제목 없음)': X status posts and the laftel.net home."""
    matched = []
    for snapshot in db.collection_group("contents").stream():
        data = snapshot.to_dict() or {}
        url = data.get("url") or ""
        if not is_untitled_leftover(url, data.get("title") or ""):
            continue
        matched.append({
            "id": content_id(snapshot),
            "url": url,
            "ref": snapshot.reference,
        })
    if not dry_run:
        for item in matched:
            item["ref"].delete()
    return {
        "deleted": 0 if dry_run else len(matched),
        "matched": len(matched),
        "dry_run": dry_run,
        "items": [{"id": item["id"], "url": item["url"]} for item in matched],
    }


class ContentStore:
    def __init__(self, db=None):
        """db=None is an isolated dry run; no Firestore access or credentials."""
        self.db = db
        self.by_url: dict[str, list[dict]] = {}
        self.invalid_urls: list[str] = []
        self.preview: list[dict] = []
        if db is not None:
            # collection_group reads every category's "contents" subcollection in one query.
            for snapshot in db.collection_group("contents").select(list(INDEX_FIELDS)).stream():
                data = snapshot.to_dict() or {}
                try:
                    url = normalize_url(data.get("url") or "")
                except ValueError:
                    self.invalid_urls.append(snapshot.id)
                    continue
                self.by_url.setdefault(url, []).append({
                    "id": snapshot.id, "status": data.get("status"), "ref": snapshot.reference,
                    "imageUrl": data.get("imageUrl"), "price": data.get("price"),
                    "checkedAt": data.get("detailCheckedAt") or data.get("productCheckedAt"),
                })

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

    def needs_detail(
        self, url: str, *, product_mode: bool = False,
        refresh_hours: float | None = DEFAULT_DETAIL_REFRESH_HOURS,
    ) -> bool:
        """Whether a detail page must be fetched for this listed URL.

        A new URL always needs it. Product pages are refreshed once per
        `refresh_hours` (price/sale status change). Photo-only pages never change,
        so they are refetched only while the photo is missing, and then no more
        often than `refresh_hours` so a page that has no photo is not hit every run.
        `refresh_hours` of 0 turns skipping off.
        """
        if self.db is None:
            return True
        try:
            normalized = normalize_url(url)
        except ValueError:
            return True
        docs = self.by_url.get(normalized)
        if not docs or not refresh_hours or refresh_hours <= 0:
            return True
        # Same document choice as save().
        canonical_id = doc_id(normalized)
        doc = min(docs, key=lambda d: (d["id"] != canonical_id, d["id"]))
        if not product_mode and doc.get("imageUrl"):
            return False
        checked = doc.get("checkedAt")
        if not isinstance(checked, datetime):
            return True
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - checked >= timedelta(hours=refresh_hours)

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
