"""Shared content vocabulary and stable Firestore document identities."""

CATEGORIES = ("ANIME", "CHARACTER", "FIGURE", "GOODS", "COLLECTION", "FESTIVAL", "UNKNOWN")
STATUSES = ("NEW", "KEEP", "HOLD", "IGNORE")
ANGLES = ("NEWS", "COMPARE", "SIZE", "PRICE", "QUESTION", "GUIDE", "COLLECTION")
SOURCE_TIERS = ("OFFICIAL", "MEDIA")


def category_collection(db, category: str):
    return db.collection("categories").document(category or "UNKNOWN").collection("contents")


def content_ref(db, source_id: str):
    category, separator, document_id = source_id.partition(":")
    if not separator or not category or not document_id or "/" in source_id:
        raise ValueError("잘못된 항목 ID입니다.")
    return category_collection(db, category).document(document_id)


def content_id(snapshot) -> str:
    # The category field may change; the document's storage path does not.
    return f"{snapshot.reference.parent.parent.id}:{snapshot.id}"
