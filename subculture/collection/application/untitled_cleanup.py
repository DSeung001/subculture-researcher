from subculture.shared.content_model import content_id
from subculture.shared.untitled_content import is_untitled_leftover


def delete_untitled_x_contents(db, *, dry_run: bool = False) -> dict:
    """Delete Firestore leftovers stored with title '(제목 없음)': X status posts and the laftel.net home."""
    matched = []
    for snapshot in db.collection_group("contents").stream():
        data = snapshot.to_dict() or {}
        url = data.get("url") or ""
        if not is_untitled_leftover(url, data.get("title") or ""):
            continue
        matched.append({
            "id": content_id(snapshot),
            "url": url,
            "ref": snapshot.reference,
        })
    if not dry_run:
        for item in matched:
            item["ref"].delete()
    return {
        "deleted": 0 if dry_run else len(matched),
        "matched": len(matched),
        "dry_run": dry_run,
        "items": [{"id": item["id"], "url": item["url"]} for item in matched],
    }
