"""Temporary posts that bundle one or more stored contents, kept in the local library.

Sources are read from the local `items` copy. Ones that are not synced yet can be
fetched from Firestore in one bulk read (`cloud`), and publishing writes `postedAt`
back to the source documents there so the inbox keeps its 「미발행만 보기」 filter.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from subculture.drafts.domain.posts import DraftPosts
from subculture.drafts.domain.rules import (
    MAX_SOURCES, DraftError, build_posts, display_title, infer_angle, unique_ids, validate_id,
)
from subculture.drafts.infrastructure import draft_repository
from subculture.library.infrastructure.local_library import Library
from subculture.shared.content_model import ANGLES as ALLOWED_ANGLES, content_ref
from subculture.shared.image_urls import http_url
from subculture.shared.presentation import CATEGORY_LABELS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        validate_id(source_id)
    items = library.items_by_id(source_ids)
    missing = [source_id for source_id in source_ids if source_id not in items]
    if missing and cloud is not None:
        _fetch_missing(library, cloud, missing)
        items = library.items_by_id(source_ids)
    if any(source_id not in items for source_id in source_ids):
        raise DraftError("선택한 항목 중 없는 자료가 있습니다. 동기화 후 다시 시도해주세요.")
    return [items[source_id] for source_id in source_ids]


def create_draft(
    library: Library, source_ids, angle: str | None = None, body: str | None = None,
    reply: str | None = None, *,
    body_factory: Callable[[list[dict], str], DraftPosts] | None = None, cloud=None,
) -> int:
    """Validate once before generating optional expensive posts from fresh sources.

    A draft is two posts: the body (facts, no links) and the reply (links). `body_factory` writes
    both; a given `body` (and optional `reply`) is stored as is.
    """
    if (body is not None or reply is not None) and body_factory is not None:
        raise ValueError("body/reply와 body_factory는 함께 지정할 수 없습니다.")
    ids = unique_ids(source_ids)
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
    draft_repository.ensure_no_duplicate(library, ids, chosen_angle)

    if body_factory is not None:
        posts = body_factory(items, chosen_angle)
    elif body is not None:
        posts = DraftPosts(body, reply or "")
    else:
        posts = build_posts(items, chosen_angle)
        if reply is not None:
            posts = DraftPosts(posts.body, reply)

    return draft_repository.insert_draft(library, ids, chosen_angle, posts.body, posts.reply, _now())


def list_drafts(library: Library, status: str = "DRAFT", limit: int = 1000) -> list[dict]:
    drafts, members = draft_repository.fetch_drafts(library, status, limit)

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


def save_posts(library: Library, draft_id: int, body: str, reply: str) -> None:
    draft_repository.update_posts(library, draft_id, body, reply, _now())


def publish_draft(library: Library, draft_id: int, cloud=None) -> list[str]:
    """Mark a draft published locally, then record `postedAt` on its source documents in Firestore.

    Returns warnings. A failed Firestore write never undoes the local publish.
    """
    now = datetime.now(timezone.utc)
    source_ids = draft_repository.mark_posted(library, draft_id, now.isoformat())
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
    draft_repository.remove_draft(library, draft_id)
