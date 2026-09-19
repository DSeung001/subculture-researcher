"""Which stored items an IP draft draws on (pure ranking rules, no I/O)."""

from subculture.drafts.domain.rules import MAX_SOURCES, DraftError
from subculture.shared.presentation import content_score


SELECTION_POOL_SIZE = 15
DRAFT_SIZE = 3
WORK_DRAFT_TYPES = ("FIGURE", "ANIME", "MIXED")
WORK_DRAFT_LABELS = {"FIGURE": "피규어", "ANIME": "애니", "MIXED": "혼합"}


def _item_usable(item: dict) -> bool:
    data = item.get("data") or {}
    return data.get("status") != "IGNORE" and not data.get("postedAt")


def _score_linked_item(item: dict) -> float:
    return content_score(item.get("data") or {})


def _diversify_mixed(items: list[dict], size: int) -> list[dict]:
    """Prefer covering at least two storage categories within `size` slots."""
    if len(items) <= size:
        return items
    picked = []
    seen_cats = set()
    remaining = list(items)
    # First pass: one best item per category until size or categories run out.
    for item in list(remaining):
        cat = item["storage_category"]
        if cat in seen_cats:
            continue
        picked.append(item)
        seen_cats.add(cat)
        remaining.remove(item)
        if len(picked) >= size:
            return picked
    for item in remaining:
        if len(picked) >= size:
            break
        picked.append(item)
    return picked


def pick_work_source_ids(
    groups: list[dict],
    draft_type: str,
    size: int = DRAFT_SIZE,
    exclude_ids: set[str] | None = None,
) -> list[str]:
    """Pick source ids for one IP draft type from confirmed work groups.

    Storage category is the item-id prefix. Unlinked items are never present
    in `groups`. Returns [] when no suitable work remains.
    """
    if draft_type not in WORK_DRAFT_TYPES:
        raise ValueError(f"지원하지 않는 작품 초안 유형: {draft_type}")
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_SOURCES:
        raise DraftError(f"초안 재료 수는 1~{MAX_SOURCES}개여야 합니다.")
    exclude = exclude_ids or set()
    ranked = []

    for group in groups:
        usable = [
            item for item in group.get("items") or []
            if item["id"] not in exclude and _item_usable(item)
        ]
        if draft_type in ("FIGURE", "ANIME"):
            usable = [item for item in usable if item["storage_category"] == draft_type]
            if not usable:
                continue
            usable.sort(key=_score_linked_item, reverse=True)
            chosen = usable[:size]
        else:
            if len({item["storage_category"] for item in usable}) < 2:
                continue
            usable.sort(key=_score_linked_item, reverse=True)
            chosen = _diversify_mixed(usable, size)
            if len({item["storage_category"] for item in chosen}) < 2:
                continue
        score = max(_score_linked_item(item) for item in chosen)
        ranked.append((score, [item["id"] for item in chosen]))

    if not ranked:
        return []
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    return ranked[0][1]
