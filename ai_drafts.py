"""Bundle the top-scoring unposted content into one AI-written draft."""

from ai_writer import AiWriterError, select_top_items, write_draft_body
from drafts_store import DraftError, create_draft, infer_angle
from presentation import content_score


CANDIDATE_LIMIT = 300
SELECTION_POOL_SIZE = 15
DRAFT_SIZE = 3


def _load_candidates(db, category: str | None = None) -> list[dict]:
    items = []
    for snapshot in db.collection_group("contents").limit(CANDIDATE_LIMIT).stream():
        data = snapshot.to_dict() or {}
        if data.get("status") == "IGNORE" or data.get("postedAt"):
            continue
        item_category = data.get("category") or "UNKNOWN"
        if category is not None and item_category != category:
            continue
        data["_id"] = f"{item_category}:{snapshot.id}"
        items.append(data)
    return items


def create_trending_draft(db, size: int = DRAFT_SIZE, category: str | None = None) -> str | None:
    """Create one AI-written draft from the items most likely to be widely seen.

    When `category` is given, only that category's unposted items are
    considered (e.g. to generate one draft per category instead of one
    mixed draft).

    Returns the new draft id, or None when there is no unposted material to
    write about. DraftError (e.g. a duplicate of an existing draft) and
    AiWriterError (e.g. missing GEMINI_API_KEY) propagate to the caller.
    """
    items = _load_candidates(db, category=category)
    if not items:
        return None

    items.sort(key=content_score, reverse=True)
    pool = items[:SELECTION_POOL_SIZE]
    top = select_top_items(pool, size)
    angle = infer_angle(top)
    body = write_draft_body(top, angle)
    source_ids = [item["_id"] for item in top]
    return create_draft(db, source_ids, angle=angle, body=body)


def run_trending_draft(db, category: str | None = None) -> str:
    """CLI wrapper around create_trending_draft with a one-line status message.

    Used by both `collect.py` (after a real collect) and `draft.py` so the two
    commands share the same selection, writing, and log wording.
    """
    try:
        draft_id = create_trending_draft(db, category=category)
    except DraftError as exc:
        return f"[AI 초안] 건너뜀: {exc}"
    except AiWriterError as exc:
        return f"[AI 초안] 실패: {exc}"
    if draft_id:
        return f"[AI 초안] 임시글 생성: {draft_id}"
    return "[AI 초안] 후보 항목 없음, 건너뜀"
