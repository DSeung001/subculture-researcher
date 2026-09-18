"""Bundle the top-scoring unposted content into one AI-written draft."""

from ai_writer import write_draft_body
from drafts_store import create_draft, infer_angle
from presentation import content_score


CANDIDATE_LIMIT = 300
DRAFT_SIZE = 3


def _load_candidates(db) -> list[dict]:
    items = []
    for snapshot in db.collection_group("contents").limit(CANDIDATE_LIMIT).stream():
        data = snapshot.to_dict() or {}
        if data.get("status") == "IGNORE" or data.get("postedAt"):
            continue
        category = data.get("category") or "UNKNOWN"
        data["_id"] = f"{category}:{snapshot.id}"
        items.append(data)
    return items


def create_trending_draft(db, size: int = DRAFT_SIZE) -> str | None:
    """Create one AI-written draft from the items most likely to be widely seen.

    Returns the new draft id, or None when there is no unposted material to
    write about. DraftError (e.g. a duplicate of an existing draft) and
    AiWriterError (e.g. missing GEMINI_API_KEY) propagate to the caller.
    """
    items = _load_candidates(db)
    if not items:
        return None

    items.sort(key=content_score, reverse=True)
    top = items[:size]
    angle = infer_angle(top)
    body = write_draft_body(top, angle)
    source_ids = [item["_id"] for item in top]
    return create_draft(db, source_ids, angle=angle, body=body)
