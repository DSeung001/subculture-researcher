"""What a draft is allowed to be: source limits, angle choice and the plain-text body (no I/O)."""

from subculture.shared.content_model import ANGLES as ALLOWED_ANGLES


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


def unique_ids(source_ids) -> list[str]:
    ids = []
    seen = set()
    for raw in source_ids:
        source_id = (raw or "").strip()
        if source_id and source_id not in seen:
            seen.add(source_id)
            ids.append(source_id)
    return ids


def validate_id(source_id: str) -> None:
    """source_id is "CATEGORY:doc_id", the storage path of the Firestore document."""
    category, separator, document_id = source_id.partition(":")
    if not separator or not category or not document_id or "/" in source_id:
        raise DraftError("잘못된 항목 ID입니다.")
