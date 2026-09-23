"""Bundle the top-scoring unposted content into one AI-written draft."""

from subculture.drafts.application.drafts import create_draft
from subculture.drafts.domain.rules import MAX_SOURCES, DraftError, infer_angle
from subculture.drafts.domain.selection import (
    DRAFT_SIZE, SELECTION_POOL_SIZE, WORK_DRAFT_LABELS, WORK_DRAFT_TYPES, pick_work_source_ids,
)
from subculture.drafts.infrastructure.ai_writer import AiWriterError, select_top_items, write_draft_posts
from subculture.library.infrastructure.local_library import Library
from subculture.shared.presentation import content_score


def create_trending_draft(library: Library, size: int = DRAFT_SIZE, category: str | None = None, cloud=None) -> int | None:
    """Create one AI-written draft from the items most likely to be widely seen.

    Candidates are the locally synced items that are not ignored, posted, or already
    part of a draft. When `category` is given, only that category's items are considered (e.g. to
    generate one draft per category instead of one mixed draft).

    Returns the new draft id, or None when there is no unposted material to
    write about. DraftError (e.g. a duplicate of an existing draft) and
    AiWriterError (e.g. missing GEMINI_API_KEY) propagate to the caller.
    """
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_SOURCES:
        raise DraftError(f"초안 재료 수는 1~{MAX_SOURCES}개여야 합니다.")
    # Items already in an unpublished draft would only re-pick the same set and hit the duplicate check
    # after the Gemini calls were spent.
    drafted = library.drafted_item_ids()
    items = [item for item in library.draft_candidates(category) if item["_id"] not in drafted]
    if not items:
        return None

    items.sort(key=content_score, reverse=True)
    pool = items[:max(SELECTION_POOL_SIZE, size)]
    top = select_top_items(pool, size)
    angle = infer_angle(top)
    source_ids = [item["_id"] for item in top]
    return create_draft(library, source_ids, angle=angle, body_factory=write_draft_posts, cloud=cloud)


def run_trending_draft(library: Library, category: str | None = None) -> str:
    """CLI wrapper around create_trending_draft with a one-line status message.

    Used by `collect.py`/`collect_manual.py` (after a real collect) and `draft.py`
    so the commands share the same selection, writing, and log wording.
    """
    try:
        draft_id = create_trending_draft(library, category=category)
    except DraftError as exc:
        return f"[AI 초안] 건너뜀: {exc}"
    except AiWriterError as exc:
        return f"[AI 초안] 실패: {exc}"
    if draft_id:
        return f"[AI 초안] 임시글 생성: {draft_id}"
    return "[AI 초안] 후보 항목 없음, 건너뜀"


def run_local_trending_draft(db_path=None, category: str | None = None) -> str:
    """run_trending_draft for entry points that only have a path: a closed local DB is a message, not a crash."""
    try:
        library = Library(db_path)
    except Exception as exc:
        lines = str(exc).strip().splitlines()
        return f"[AI 초안] 실패: 로컬 DB를 열 수 없습니다: {(lines[0] if lines else type(exc).__name__)[:160]}"
    return run_trending_draft(library, category=category)


def create_work_drafts(
    library: Library, size: int = DRAFT_SIZE, work_id: int | None = None,
) -> list[tuple[str, int | None, str | None]]:
    """Create up to one FIGURE and one MIXED draft from local work links.

    When `work_id` is set, only that work's linked items are considered.
    Returns a list of `(draft_type, draft_id_or_None, error_or_None)`. Source
    ids are not shared across the drafts in one run, and sources of a
    published draft are left out. Bodies are written by `create_draft` after selection.
    """
    groups = library.linked_work_items()
    if work_id is not None:
        groups = [g for g in groups if g["work_id"] == work_id]
    used: set[str] = set(library.posted_item_ids())
    results = []
    for draft_type in WORK_DRAFT_TYPES:
        try:
            source_ids = pick_work_source_ids(groups, draft_type, size=size, exclude_ids=used)
        except DraftError as exc:
            results.append((draft_type, None, str(exc)))
            continue
        if not source_ids:
            results.append((draft_type, None, None))
            continue
        try:
            draft_id = create_draft(library, source_ids, body_factory=write_draft_posts)
        except DraftError as exc:
            results.append((draft_type, None, str(exc)))
            continue
        except AiWriterError as exc:
            results.append((draft_type, None, str(exc)))
            # Daily quota / hard API failure: stop further Gemini calls.
            break
        used.update(source_ids)
        results.append((draft_type, draft_id, None))
    # Fill skipped types after an early AiWriterError break.
    seen = {draft_type for draft_type, _, _ in results}
    for draft_type in WORK_DRAFT_TYPES:
        if draft_type not in seen:
            results.append((draft_type, None, None))
    return results


def run_work_drafts(library: Library) -> str:
    """CLI wrapper that prints one status line per FIGURE/MIXED attempt."""
    lines = []
    for draft_type, draft_id, error in create_work_drafts(library):
        label = WORK_DRAFT_LABELS[draft_type]
        if error:
            lines.append(f"[작품 초안·{label}] 건너뜀: {error}")
        elif draft_id:
            lines.append(f"[작품 초안·{label}] 임시글 생성: {draft_id}")
        else:
            lines.append(f"[작품 초안·{label}] 후보 항목 없음, 건너뜀")
    return "\n".join(lines)
