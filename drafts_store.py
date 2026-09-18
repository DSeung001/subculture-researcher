"""Temporary posts that bundle one or more contents documents."""

from datetime import datetime, timezone

from firebase_admin import firestore


ALLOWED_ANGLES = ("NEWS", "COMPARE", "SIZE", "PRICE", "QUESTION", "GUIDE", "COLLECTION")
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


def _unique_ids(source_ids) -> list[str]:
    ids = []
    seen = set()
    for raw in source_ids:
        source_id = (raw or "").strip()
        if source_id and source_id not in seen:
            seen.add(source_id)
            ids.append(source_id)
    return ids


def _content_ref(db, source_id: str):
    """source_id is "CATEGORY:doc_id" — the category picks which contents collection to look in."""
    category, _, doc_id = source_id.partition(":")
    if not category or not doc_id:
        raise DraftError("잘못된 항목 ID입니다.")
    return db.collection("categories").document(category).collection("contents").document(doc_id)


def _load_contents(db, source_ids: list[str]) -> list[dict]:
    items = []
    for source_id in source_ids:
        snapshot = _content_ref(db, source_id).get()
        if not snapshot.exists:
            raise DraftError("선택한 항목 중 없는 자료가 있습니다.")
        item = snapshot.to_dict() or {}
        item["_id"] = source_id
        items.append(item)
    return items


def _existing_duplicate(db, source_ids: list[str], angle: str) -> bool:
    wanted = set(source_ids)
    for snapshot in db.collection("drafts").select(["sourceIds", "angle"]).stream():
        data = snapshot.to_dict() or {}
        if data.get("angle") == angle and set(data.get("sourceIds") or []) == wanted:
            return True
    return False


def create_draft(db, source_ids, angle: str | None = None, body: str | None = None) -> str:
    """body overrides the mechanically assembled text (e.g. an AI-written draft)."""
    ids = _unique_ids(source_ids)
    if not ids:
        raise DraftError("항목을 선택해주세요.")
    if len(ids) > MAX_SOURCES:
        raise DraftError(f"한 임시글에 재료는 {MAX_SOURCES}개까지입니다.")

    items = _load_contents(db, ids)
    chosen_angle = angle if angle in ALLOWED_ANGLES else infer_angle(items)

    if chosen_angle == "NEWS" and any(item.get("postedAt") for item in items):
        raise DraftError("이미 발행에 쓰인 재료는 뉴스 임시글로 만들 수 없습니다.")
    if _existing_duplicate(db, ids, chosen_angle):
        raise DraftError("같은 재료와 각도의 임시글이 이미 있습니다.")

    now = datetime.now(timezone.utc)
    ref = db.collection("drafts").document()
    ref.set({
        "sourceIds": ids,
        "angle": chosen_angle,
        "body": body if body is not None else build_body(items, chosen_angle),
        "status": "DRAFT",
        "postedAt": None,
        "createdAt": now,
        "updatedAt": now,
    })
    return ref.id


def list_drafts(db, status: str = "DRAFT", limit: int = 1000) -> list[dict]:
    snapshots = list(
        db.collection("drafts")
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    drafts = []
    source_ids = []
    seen = set()
    for snapshot in snapshots:
        data = snapshot.to_dict() or {}
        data["_id"] = snapshot.id
        if status in {"DRAFT", "POSTED"} and data.get("status") != status:
            continue
        drafts.append(data)
        for source_id in data.get("sourceIds") or []:
            if source_id not in seen:
                seen.add(source_id)
                source_ids.append(source_id)

    sources = {}
    if source_ids:
        # get_all does not preserve input order — key by path, never zip.
        refs = [_content_ref(db, source_id) for source_id in source_ids]
        path_to_id = {ref.path: source_id for source_id, ref in zip(source_ids, refs)}
        for snapshot in db.get_all(refs):
            if not snapshot.exists or snapshot.reference is None:
                continue
            source_id = path_to_id.get(snapshot.reference.path)
            if not source_id:
                continue
            item = snapshot.to_dict() or {}
            item["_id"] = source_id
            sources[source_id] = item

    for draft in drafts:
        bundled = []
        for source_id in draft.get("sourceIds") or []:
            item = sources.get(source_id)
            if item:
                bundled.append({
                    **item,
                    "_title": display_title(item),
                    "_used": bool(item.get("postedAt")),
                })
            else:
                bundled.append({
                    "_id": source_id,
                    "_title": "(없는 항목)",
                    "_used": False,
                    "url": "",
                })
        draft["_sources"] = bundled
    return drafts


def save_body(db, draft_id: str, body: str) -> None:
    ref = db.collection("drafts").document(draft_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise DraftError("임시글을 찾을 수 없습니다.")
    if (snapshot.to_dict() or {}).get("status") == "POSTED":
        raise DraftError("발행된 글은 수정할 수 없습니다.")
    ref.update({"body": body, "updatedAt": datetime.now(timezone.utc)})


def publish_draft(db, draft_id: str) -> None:
    ref = db.collection("drafts").document(draft_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise DraftError("임시글을 찾을 수 없습니다.")
    data = snapshot.to_dict() or {}
    if data.get("status") == "POSTED":
        raise DraftError("이미 발행된 글입니다.")
    now = datetime.now(timezone.utc)
    ref.update({"status": "POSTED", "postedAt": now, "updatedAt": now})
    for source_id in data.get("sourceIds") or []:
        content_ref = _content_ref(db, source_id)
        content = content_ref.get()
        if content.exists and not (content.to_dict() or {}).get("postedAt"):
            content_ref.update({"postedAt": now})


def delete_draft(db, draft_id: str) -> None:
    ref = db.collection("drafts").document(draft_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise DraftError("임시글을 찾을 수 없습니다.")
    if (snapshot.to_dict() or {}).get("status") == "POSTED":
        raise DraftError("발행된 글은 삭제할 수 없습니다.")
    ref.delete()
