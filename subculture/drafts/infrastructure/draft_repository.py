"""SQLAlchemy reads and writes of `drafts` / `draft_items` in the local library."""

from datetime import datetime

from sqlalchemy import delete, select

from subculture.drafts.domain.rules import DraftError
from subculture.library.infrastructure.local_library import Library
from subculture.library.infrastructure.models import Draft, DraftItem


DUPLICATE_MESSAGE = "같은 재료와 각도의 임시글이 이미 있습니다."


def _duplicate_exists(session, source_ids: list[str], angle: str) -> bool:
    wanted = set(source_ids)
    grouped: dict[int, set[str]] = {}
    rows = session.execute(
        select(DraftItem.draft_id, DraftItem.item_id)
        .join(Draft, Draft.id == DraftItem.draft_id)
        .where(Draft.angle == angle)
    )
    for draft_id, item_id in rows:
        grouped.setdefault(draft_id, set()).add(item_id)
    return any(members == wanted for members in grouped.values())


def ensure_no_duplicate(library: Library, source_ids: list[str], angle: str) -> None:
    with library.connect() as session:
        if _duplicate_exists(session, source_ids, angle):
            raise DraftError(DUPLICATE_MESSAGE)


def insert_draft(library: Library, source_ids: list[str], angle: str, body: str, now: str) -> int:
    with library.connect() as session:
        # Checked again in the writing transaction: the body may have taken a while to write.
        if _duplicate_exists(session, source_ids, angle):
            raise DraftError(DUPLICATE_MESSAGE)
        draft = Draft(
            angle=angle, body=body,
            status="DRAFT", posted_at=None, created_at=now, updated_at=now,
        )
        session.add(draft)
        session.flush()
        session.add_all(
            DraftItem(draft_id=draft.id, item_id=source_id, position=position)
            for position, source_id in enumerate(source_ids)
        )
        return draft.id


def _parse_time(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def fetch_drafts(library: Library, status: str, limit: int) -> tuple[list[dict], dict[int, list[str]]]:
    """Draft rows (newest first) and, per draft id, its source ids in order."""
    query = select(Draft).order_by(Draft.created_at.desc(), Draft.id.desc()).limit(limit)
    if status in {"DRAFT", "POSTED"}:
        query = query.where(Draft.status == status)
    with library.connect() as session:
        rows = session.scalars(query).all()
        drafts = [{
            "_id": row.id, "angle": row.angle, "body": row.body, "status": row.status,
            "createdAt": _parse_time(row.created_at), "postedAt": _parse_time(row.posted_at),
        } for row in rows]
        members = {}
        if drafts:
            links = session.execute(
                select(DraftItem.draft_id, DraftItem.item_id)
                .where(DraftItem.draft_id.in_([draft["_id"] for draft in drafts]))
                .order_by(DraftItem.draft_id, DraftItem.position)
            )
            for draft_id, item_id in links:
                members.setdefault(draft_id, []).append(item_id)
    return drafts, members


def _editable_draft(session, draft_id: int, action: str) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise DraftError("임시글을 찾을 수 없습니다.")
    if draft.status == "POSTED":
        raise DraftError(f"발행된 글은 {action}할 수 없습니다.")
    return draft


def update_body(library: Library, draft_id: int, body: str, now: str) -> None:
    with library.connect() as session:
        draft = _editable_draft(session, draft_id, "수정")
        draft.body, draft.updated_at = body, now


def mark_posted(library: Library, draft_id: int, posted_at: str) -> list[str]:
    """Mark the draft published and return its source ids in order."""
    with library.connect() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise DraftError("임시글을 찾을 수 없습니다.")
        if draft.status == "POSTED":
            raise DraftError("이미 발행된 글입니다.")
        draft.status, draft.posted_at, draft.updated_at = "POSTED", posted_at, posted_at
        return list(session.scalars(
            select(DraftItem.item_id).where(DraftItem.draft_id == draft_id).order_by(DraftItem.position)))


def remove_draft(library: Library, draft_id: int) -> None:
    with library.connect() as session:
        draft = _editable_draft(session, draft_id, "삭제")
        session.execute(delete(DraftItem).where(DraftItem.draft_id == draft.id))
        session.delete(draft)
