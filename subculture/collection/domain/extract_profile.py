"""Validate extractor profile shapes (no I/O)."""

from subculture.collection.domain.extract_fields import (
    DETAIL_FIELD_NAMES,
    LIST_FIELD_NAMES,
    PARSE_KINDS,
)

REQUIRED_LIST_FIELDS = frozenset({"link", "title"})


class ExtractProfileError(ValueError):
    pass


def _field_spec(name: str, raw, allowed_names: frozenset[str]) -> dict:
    if name not in allowed_names:
        raise ExtractProfileError(f"알 수 없는 필드: {name}")
    if not isinstance(raw, dict):
        raise ExtractProfileError(f"필드 {name}은 객체여야 합니다.")
    selector = (raw.get("selector") or "").strip()
    if not selector:
        raise ExtractProfileError(f"필드 {name}에 selector가 필요합니다.")
    parse = (raw.get("parse") or "text").strip()
    if parse not in PARSE_KINDS:
        raise ExtractProfileError(f"필드 {name}의 parse가 잘못되었습니다: {parse}")
    attr = raw.get("attr")
    if attr is not None and not isinstance(attr, str):
        raise ExtractProfileError(f"필드 {name}의 attr은 문자열이어야 합니다.")
    many = bool(raw.get("many", False))
    if many and name != "gallery":
        raise ExtractProfileError("many는 gallery 필드에만 쓸 수 있습니다.")
    return {
        "selector": selector,
        "parse": parse,
        "attr": (attr or "").strip() or None,
        "many": many,
    }


def normalize_extract(raw) -> dict | None:
    """Return a normalized extract map, or None when absent."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ExtractProfileError("extract는 객체여야 합니다.")
    list_raw = raw.get("list")
    if not isinstance(list_raw, dict):
        raise ExtractProfileError("extract.list가 필요합니다.")
    item = (list_raw.get("item") or "").strip()
    if not item:
        raise ExtractProfileError("extract.list.item 셀렉터가 필요합니다.")
    fields_raw = list_raw.get("fields")
    if not isinstance(fields_raw, dict) or not fields_raw:
        raise ExtractProfileError("extract.list.fields가 필요합니다.")
    fields = {name: _field_spec(name, spec, LIST_FIELD_NAMES) for name, spec in fields_raw.items()}
    missing = REQUIRED_LIST_FIELDS - fields.keys()
    if missing:
        raise ExtractProfileError(f"필수 목록 필드가 없습니다: {', '.join(sorted(missing))}")

    result = {"list": {"item": item, "fields": fields}}
    detail_raw = raw.get("detail")
    if detail_raw is not None:
        if not isinstance(detail_raw, dict):
            raise ExtractProfileError("extract.detail은 객체여야 합니다.")
        detail_fields_raw = detail_raw.get("fields") or {}
        if not isinstance(detail_fields_raw, dict):
            raise ExtractProfileError("extract.detail.fields는 객체여야 합니다.")
        detail_fields = {
            name: _field_spec(name, spec, DETAIL_FIELD_NAMES)
            for name, spec in detail_fields_raw.items()
        }
        result["detail"] = {"fields": detail_fields}
    return result


def slug_for_name(name: str) -> str:
    """Filesystem-safe stem derived from a source display name."""
    cleaned = []
    for char in name.strip():
        if char.isalnum() or char in "._-":
            cleaned.append(char)
        elif char.isspace() or char in "/\\|":
            cleaned.append("_")
    stem = "".join(cleaned).strip("._-") or "source"
    return stem[:80]
