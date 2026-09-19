"""Temporary posts that bundle one or more stored contents, kept in the local library.

Sources are read from the local `items` copy. Ones that are not synced yet can be
fetched from Firestore in one bulk read (`cloud`), and publishing writes `postedAt`
back to the source documents there so the inbox keeps its 「미발행만 보기」 filter.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import delete, select

from content_model import ANGLES as ALLOWED_ANGLES, content_ref
from image_urls import http_url
from library_models import Draft, DraftItem
from local_library import Library
from presentation import CATEGORY_LABELS


MAX_SOURCES = 20


class DraftError(ValueError):
    pass


def display_title(item: dict) -> str:
    return (item.get("titleKo") or "").strip() or item.get("title") or "(제목 없음)"


def infer_angle(items: list[dict]) -> str:
    if len(items) == 1:
        angle = items[0].get("contentAngle") or "NEWS"
        return angle if angle in ALLOWED_ANGLES else "NEWS"
    if items and all(item.get("contentAngle") == "COLLECTION" for item in items):
        return "COLLECTION"
    return "COMPARE"


def build_body(items: list[dict], angle: str) -> str:
    lines = [f"[{angle}]", ""]
    for item in items:
        source = item.get("source") or ""
        lines.append(f"- ({source}) {display_title(item)}" if source else f"- {display_title(item)}")
        summary = (item.get("summaryKo") or item.get("summary") or "").strip()
        if summary:
            lines.append(f"  {summary[:500]}")
        if item.get("url"):
            lines.append(f"  {item['url']}")
        note = (item.get("note") or "").strip()
        if note:
            lines.append(f"  메모: {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique_ids(source_ids) -> list[str]:
    ids = []
    seen = set()
    for raw in source_ids:
        source_id = (raw or "").strip()
        if source_id and source_id not in seen:
            seen.add(source_id)
            ids.append(source_id)
    return ids


def _validate_id(source_id: str) -> None:
    """source_id is "CATEGORY:doc_id", the storage path of the Firestore document."""
    category, separator, document_id = source_id.partition(":")
    if not separator or not category or not document_id or "/" in source_id:
        raise DraftError("잘못된 항목 ID입니다.")


def _fetch_missing(library: Library, cloud, source_ids: list[str]) -> None:
    """Bring documents that were never synced into the local copy with one bulk read."""
    refs = []
    for source_id in source_ids:
        try:
            refs.append(content_ref(cloud, source_id))
        except ValueError as exc:
            raise DraftError(str(exc)) from exc
    # get_all may return snapshots in any order; upsert_snapshots keys them by their own path.
    library.upsert_snapshots([snapshot for snapshot in cloud.get_all(refs) if snapshot.exists])


def _load_contents(library: Library, source_ids: list[str], cloud=None) -> list[dict]:
    for source_id in source_ids:
        _validate_id(source_id)
    items = library.items_by_id(source_ids)
    missing = [source_id for source_id in source_ids if source_id not in items]
    if missing and cloud is not None:
        _fetch_missing(library, cloud, missing)
        items = library.items_by_id(source_ids)
    if any(source_id not in items for source_id in source_ids):
        raise DraftError("선택한 항목 중 없는 자료가 있습니다. 동기화 후 다시 시도해주세요.")
    return [items[source_id] for source_id in source_ids]


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


def create_draft(
    library: Library, source_ids, angle: str | None = None, body: str | None = None, *,
    body_factory: Callable[[list[dict], str], str] | None = None, cloud=None,
) -> int:
    """Validate once before generating an optional expensive body from fresh sources."""
    if body is not None and body_factory is not None:
        raise ValueError("body와 body_factory는 함께 지정할 수 없습니다.")
    ids = _unique_ids(source_ids)
    if not ids:
        raise DraftError("항목을 선택해주세요.")
    if len(ids) > MAX_SOURCES:
        raise DraftError(f"한 임시글에 재료는 {MAX_SOURCES}개까지입니다.")

    items = _load_contents(library, ids, cloud)
    chosen_angle = angle if angle in ALLOWED_ANGLES else infer_angle(items)

    if chosen_angle == "NEWS" and (
        any(item.get("postedAt") for item in items) or library.posted_item_ids(ids)
    ):
        raise DraftError("이미 발행에 쓰인 재료는 뉴스 임시글로 만들 수 없습니다.")
    with library.connect() as session:
        if _duplicate_exists(session, ids, chosen_angle):
            raise DraftError("같은 재료와 각도의 임시글이 이미 있습니다.")

    if body_factory is not None:
        body = body_factory(items, chosen_angle)

    now = _now()
    with library.connect() as session:
        # Checked again in the writing transaction: the body may have taken a while to write.
        if _duplicate_exists(session, ids, chosen_angle):
            raise DraftError("같은 재료와 각도의 임시글이 이미 있습니다.")
        draft = Draft(
            angle=chosen_angle,
            body=body if body is not None else build_body(items, chosen_angle),
            status="DRAFT", posted_at=None, created_at=now, updated_at=now,
        )
        session.add(draft)
        session.flush()
        session.add_all(
            DraftItem(draft_id=draft.id, item_id=source_id, position=position)
            for position, source_id in enumerate(ids)
        )
        return draft.id


def _parse_time(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def list_drafts(library: Library, status: str = "DRAFT", limit: int = 1000) -> list[dict]:
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

    every_id = [item_id for ids in members.values() for item_id in ids]
    sources = library.items_by_id(every_id)  # one bulk read, matched by id
    used = library.posted_item_ids(every_id)

    for draft in drafts:
        draft["sourceIds"] = members.get(draft["_id"], [])
        bundled = []
        for source_id in draft["sourceIds"]:
            item = sources.get(source_id)
            if item is None:
                bundled.append({"_id": source_id, "_title": "(없는 항목)", "_used": False,
                                "_image": "", "_category": "", "url": ""})
                continue
            category = item.get("category") or "UNKNOWN"
            bundled.append({
                **item,
                "_title": display_title(item),
                # A published draft is itself the use of its sources; only pending drafts warn.
                "_used": draft["status"] == "DRAFT" and (bool(item.get("postedAt")) or source_id in used),
                "_image": http_url(item.get("imageUrl")) or "",
                "_category": CATEGORY_LABELS.get(category, category),
            })
        draft["_sources"] = bundled
    return drafts


def _editable_draft(session, draft_id: int, action: str) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise DraftError("임시글을 찾을 수 없습니다.")
    if draft.status == "POSTED":
        raise DraftError(f"발행된 글은 {action}할 수 없습니다.")
    return draft


def save_body(library: Library, draft_id: int, body: str) -> None:
    with library.connect() as session:
        draft = _editable_draft(session, draft_id, "수정")
        draft.body, draft.updated_at = body, _now()


def publish_draft(library: Library, draft_id: int, cloud=None) -> list[str]:
    """Mark a draft published locally, then record `postedAt` on its source documents in Firestore.

    Returns warnings. A failed Firestore write never undoes the local publish.
    """
    now = datetime.now(timezone.utc)
    with library.connect() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise DraftError("임시글을 찾을 수 없습니다.")
        if draft.status == "POSTED":
            raise DraftError("이미 발행된 글입니다.")
        draft.status, draft.posted_at, draft.updated_at = "POSTED", now.isoformat(), now.isoformat()
        source_ids = list(session.scalars(
            select(DraftItem.item_id).where(DraftItem.draft_id == draft_id).order_by(DraftItem.position)))
    if cloud is None:
        return []
    try:
        refs = [content_ref(cloud, source_id) for source_id in source_ids]
        for snapshot in cloud.get_all(refs):
            if snapshot.exists and not (snapshot.to_dict() or {}).get("postedAt"):
                snapshot.reference.update({"postedAt": now})
    except Exception as exc:
        return [f"재료의 발행 표시를 Firestore에 기록하지 못했습니다(로컬 발행은 완료): {exc}"]
    return []


def delete_draft(library: Library, draft_id: int) -> None:
    with library.connect() as session:
        draft = _editable_draft(session, draft_id, "삭제")
        session.execute(delete(DraftItem).where(DraftItem.draft_id == draft.id))
        session.delete(draft)
