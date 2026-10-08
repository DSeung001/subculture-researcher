"""One URL identity and atomic write path for every collector and manual entry."""

from datetime import datetime, timedelta, timezone

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from subculture.collection.domain.content_rules import (
    DEFAULT_DETAIL_REFRESH_HOURS, INDEX_FIELDS, PRODUCT_FIELDS, doc_id, normalize_url,
)
from subculture.collection.infrastructure.translate import enrich_translation
from subculture.shared.content_model import category_collection
from subculture.shared.image_urls import http_url


def _clean_detail_image_urls(raw, *, exclude: str | None = None) -> list[str]:
    """http(s) gallery URLs only, deduped, optionally dropping the main photo."""
    if not isinstance(raw, list):
        return []
    urls: list[str] = []
    seen: set[str] = set()
    if exclude:
        seen.add(exclude)
    for value in raw:
        url = http_url(value)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


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
                    "imageUrl": data.get("imageUrl"),
                    "detailImageUrls": data.get("detailImageUrls"),
                    "price": data.get("price"),
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
        want_detail_images: bool = False,
    ) -> bool:
        """Whether a detail page must be fetched for this listed URL.

        A new URL always needs it. Product pages are refreshed once per
        `refresh_hours` (price/sale status change). Photo-only pages never change,
        so they are refetched only while the photo is missing, and then no more
        often than `refresh_hours` so a page that has no photo is not hit every run.
        When `want_detail_images` is set and the stored gallery is empty, the page
        is fetched once even inside the refresh window (backfill).
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
        if want_detail_images and doc.get("detailImageUrls") is None:
            return True
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
        has_detail_images = "detailImageUrls" in item
        detail_urls = (
            _clean_detail_image_urls(item.get("detailImageUrls"), exclude=image_url)
            if has_detail_images else None
        )
        item = {k: v for k, v in item.items() if k not in {"imageUrl", "detailImageUrls"}}
        if image_url:
            item["imageUrl"] = image_url
        if has_detail_images:
            # Empty list marks "checked, none found" so needs_detail backfill stops.
            item["detailImageUrls"] = detail_urls
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
            updates = product_fields
            if not created and updates:
                ref.update(updates)

        if not existing:
            self.by_url[url] = [{"id": target_id, "status": "NEW" if created else None, "ref": ref}]
        return {
            "inserted": int(created),
            "existing": int(not created),
            "updated": int(not created and bool(product_fields)),
        }
