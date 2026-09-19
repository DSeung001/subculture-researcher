"""Entity-relationship diagram data for the local curation DB.

Built from the SQLAlchemy models, so columns and foreign keys always match
`library_models.py`. Only the box positions are hand-placed (LAYOUT); a table
missing from LAYOUT is still drawn, in an extra column on the right.
"""

from sqlalchemy import MetaData

from library_models import Base


TABLE_W = 214
HEADER_H = 34
ROW_H = 24
COL_GAP = 66
SLOT_GAP = 40
MARGIN_X = 58
MARGIN_Y = 24
BULGE = 44

# table -> (grid column, grid slot); "center" centers the box vertically.
LAYOUT = {
    "works": (0, 0), "work_aliases": (0, 1), "product_categories": (0, 2),
    "information_types": (0, 3), "tags": (0, 4),
    "item_works": (1, 0), "item_product_categories": (1, 2),
    "item_information_types": (1, 3), "item_tags": (1, 4),
    "items": (2, "center"),
    "collection_items": (3, "center"), "collections": (4, "center"),
    "saved_filters": (3, 4), "sync_state": (4, 4),
}
KINDS = {
    "items": "core",
    "works": "taxonomy", "work_aliases": "taxonomy", "product_categories": "taxonomy",
    "information_types": "taxonomy", "tags": "taxonomy",
    "item_works": "link", "item_product_categories": "link",
    "item_information_types": "link", "item_tags": "link", "collection_items": "link",
    "collections": "plan", "saved_filters": "plan", "sync_state": "plan",
}
KIND_LABELS = {
    "core": "수집 항목", "taxonomy": "분류 사전", "link": "연결(다대다)",
    "plan": "기획·설정", "other": "기타",
}
NOTES = {
    "items": "Firestore 수집 항목의 로컬 사본. id는 STORAGE_CATEGORY:문서ID이고 원본 필드는 payload(JSON)에 둡니다.",
    "works": "작품·IP 사전. 소재를 모으는 기준 단위입니다.",
    "work_aliases": "작품 매칭 키워드. 제목 일치를 ‘제안’할 뿐, 연결은 사용자가 확정합니다.",
    "product_categories": "제품 종류 분류(피규어, 굿즈 등).",
    "information_types": "정보 유형 분류(예약, 입고, 이벤트 등).",
    "tags": "자유 태그.",
    "item_works": "항목 ↔ 작품. 콜라보 항목은 여러 작품에 연결되고, 미분류도 허용합니다.",
    "item_product_categories": "항목 ↔ 제품 카테고리.",
    "item_information_types": "항목 ↔ 정보 유형.",
    "item_tags": "항목 ↔ 태그.",
    "collections": "손으로 편집하는 기획 묶음.",
    "collection_items": "기획 묶음의 구성 항목. 소개 순서(position)와 메모를 가집니다.",
    "saved_filters": "저장한 탐색 조건(JSON). 다른 테이블과 연결되지 않습니다.",
    "sync_state": "마지막 동기화 기록(id=1 한 행).",
}


def _column(table, column, y):
    foreign = bool(column.foreign_keys)
    return {
        "name": column.name,
        "type": str(column.type),
        "pk": column.primary_key,
        "fk": foreign,
        "unique": bool(column.unique),
        "nullable": bool(column.nullable) and not column.primary_key,
        "cy": y,
    }


def _positions(tables):
    """Fill x/y for every table, in the fixed grid, then extras to the right."""
    slot_h = max(t["h"] for t in tables if LAYOUT.get(t["name"], (0, 0))[1] != "center") + SLOT_GAP
    extra_col = max((col for col, _ in LAYOUT.values()), default=0) + 1
    extra_slot = 0
    placed_bottom = 0
    for table in tables:
        col, slot = LAYOUT.get(table["name"], (extra_col, extra_slot))
        if table["name"] not in LAYOUT:
            extra_slot += 1
        table["x"] = MARGIN_X + col * (TABLE_W + COL_GAP)
        if slot != "center":
            table["y"] = MARGIN_Y + slot * slot_h
            placed_bottom = max(placed_bottom, table["y"] + table["h"])
    centered = [t for t in tables if LAYOUT.get(t["name"], (0, 0))[1] == "center"]
    for table in centered:
        table["y"] = MARGIN_Y + max(0, (placed_bottom - MARGIN_Y - table["h"]) / 2)
    return placed_bottom


def _path(child, child_y, parent, parent_y):
    if child["x"] == parent["x"]:
        sx, ex = child["x"], parent["x"]
        return (f"M{sx} {child_y} C{sx - BULGE} {child_y} {ex - BULGE} {parent_y} {ex} {parent_y}",
                (sx, "left"), (ex, "left"))
    if parent["x"] > child["x"]:
        sx, ex = child["x"] + TABLE_W, parent["x"]
        sides = ("right", "left")
    else:
        sx, ex = child["x"], parent["x"] + TABLE_W
        sides = ("left", "right")
    dx = abs(ex - sx) / 2
    sign = 1 if ex > sx else -1
    return (f"M{sx} {child_y} C{sx + sign * dx} {child_y} {ex - sign * dx} {parent_y} {ex} {parent_y}",
            (sx, sides[0]), (ex, sides[1]))


def build_erd(metadata: MetaData | None = None) -> dict:
    metadata = metadata or Base.metadata
    tables = []
    for table in sorted(metadata.tables.values(), key=lambda t: t.name):
        columns = [_column(table, c, HEADER_H + i * ROW_H + ROW_H / 2)
                   for i, c in enumerate(table.columns)]
        tables.append({
            "name": table.name, "kind": KINDS.get(table.name, "other"),
            "note": NOTES.get(table.name, ""), "w": TABLE_W,
            "h": HEADER_H + len(columns) * ROW_H + 6, "columns": columns,
        })
    bottom = _positions(tables)
    by_name = {t["name"]: t for t in tables}

    relations = []
    for table in sorted(metadata.tables.values(), key=lambda t: t.name):
        for fk in sorted(table.foreign_keys, key=lambda f: f.parent.name):
            child, parent = by_name[table.name], by_name[fk.column.table.name]
            child_col = next(c for c in child["columns"] if c["name"] == fk.parent.name)
            parent_col = next(c for c in parent["columns"] if c["name"] == fk.column.name)
            child_y, parent_y = child["y"] + child_col["cy"], parent["y"] + parent_col["cy"]
            path, (cx, cside), (px, pside) = _path(child, child_y, parent, parent_y)
            relations.append({
                "child": child["name"], "child_column": child_col["name"],
                "parent": parent["name"], "parent_column": parent_col["name"],
                "ondelete": fk.ondelete or "NO ACTION", "path": path,
                # "N" sits at the child end, "1" at the parent end (offset off the box edge).
                "child_mark": {"x": cx + (-12 if cside == "left" else 12), "y": child_y - 7},
                "parent_mark": {"x": px + (-12 if pside == "left" else 12), "y": parent_y - 7},
            })

    width = max(t["x"] for t in tables) + TABLE_W + MARGIN_X
    height = max(bottom, max(t["y"] + t["h"] for t in tables)) + MARGIN_Y
    kind_order = list(KIND_LABELS)
    tables.sort(key=lambda t: (kind_order.index(t["kind"]), t["name"]))  # legend/description order
    return {
        "width": round(width), "height": round(height), "kinds": KIND_LABELS,
        "tables": [{**t, "x": round(t["x"], 1), "y": round(t["y"], 1)} for t in tables],
        "relations": relations,
    }
