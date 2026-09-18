import hashlib
from datetime import datetime, timezone
from typing import Any

import feedparser
from firebase_admin import firestore


def _doc_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def collect_rss(db, source: dict[str, Any]) -> dict[str, int]:
    feed = feedparser.parse(source["url"])
    inserted = 0
    processed = 0

    for entry in feed.entries:
        url = entry.get("link")
        if not url:
            continue

        processed += 1
        ref = db.collection("contents").document(_doc_id(url))
        snapshot = ref.get()

        if snapshot.exists:
            continue

        ref.set(
            {
                "url": url,
                "title": entry.get("title", "(untitled)"),
                "summary": entry.get("summary", ""),
                "source": source["name"],
                "sourceType": "rss",
                "category": source.get("category", "UNKNOWN"),
                "contentAngle": "NEWS",
                "status": "NEW",
                "publishedAt": entry.get("published") or entry.get("updated"),
                "collectedAt": firestore.SERVER_TIMESTAMP,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )
        inserted += 1

    return {"processed": processed, "inserted": inserted}
