import os
from datetime import datetime, timezone

from firebase_admin import firestore
from flask import Flask, flash, redirect, render_template, request, url_for

from firebase_client import get_db
from content_store import add_manual_content
from presentation import (
    effective_date,
    format_date_kst,
    is_new_today,
    metric_caption,
    sort_items,
    summary_preview,
)


CATEGORIES = ["ANIME", "CHARACTER", "FIGURE", "GOODS", "COLLECTION", "UNKNOWN"]
STATUSES = ["NEW", "KEEP", "HOLD", "IGNORE"]
ANGLES = ["NEWS", "COMPARE", "SIZE", "PRICE", "QUESTION", "GUIDE", "COLLECTION"]
SOURCE_TIERS = ["OFFICIAL", "MEDIA"]

CATEGORY_LABELS = {
    "ANIME": "애니",
    "CHARACTER": "캐릭터",
    "FIGURE": "피규어",
    "GOODS": "굿즈",
    "COLLECTION": "컬렉션",
    "UNKNOWN": "미분류",
}
STATUS_LABELS = {
    "NEW": "새 항목",
    "KEEP": "채택",
    "HOLD": "보류",
    "IGNORE": "무시",
}
ANGLE_LABELS = {
    "NEWS": "뉴스",
    "COMPARE": "비교",
    "SIZE": "크기",
    "PRICE": "가격",
    "QUESTION": "질문/고민",
    "GUIDE": "가이드",
    "COLLECTION": "컬렉션",
}
TIER_LABELS = {
    "OFFICIAL": "공식",
    "MEDIA": "미디어",
}

CHUNK_SIZE = 20

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

_db = None


def db():
    global _db
    if _db is None:
        _db = get_db()
    return _db


def update_content(document_id: str, **fields):
    db().collection("contents").document(document_id).update(fields)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def parse_int(raw, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def safe_next(raw: str | None) -> str:
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return url_for("index")


def current_filters():
    return {
        "category": request.args.get("category", "ALL"),
        "status": request.args.get("status", "ACTIVE"),
        "tier": request.args.get("tier", "ALL"),
        "unposted": request.args.get("unposted", ""),
        "sort": request.args.get("sort", "NEWEST"),
        "limit": clamp(parse_int(request.args.get("limit"), 50), 20, 200),
        "visible": clamp(parse_int(request.args.get("visible"), CHUNK_SIZE), CHUNK_SIZE, 10_000),
    }


def build_url(filters: dict, **overrides) -> str:
    params = {**filters, **overrides}
    if not params.get("unposted"):
        params.pop("unposted", None)
    return url_for("index", **params)


@app.get("/")
def index():
    filters = current_filters()
    unposted_only = filters["unposted"] == "1"

    query = (
        db()
        .collection("contents")
        .order_by("collectedAt", direction=firestore.Query.DESCENDING)
        .limit(filters["limit"])
    )
    docs = list(query.stream())

    items = []
    for snapshot in docs:
        item = snapshot.to_dict()
        item["_id"] = snapshot.id

        if filters["category"] != "ALL" and item.get("category") != filters["category"]:
            continue
        if filters["status"] == "ACTIVE" and item.get("status") == "IGNORE":
            continue
        if filters["status"] != "ACTIVE" and item.get("status") != filters["status"]:
            continue
        if filters["tier"] != "ALL" and item.get("sourceTier") != filters["tier"]:
            continue
        if unposted_only and item.get("postedAt"):
            continue

        items.append(item)

    items = sort_items(items, newest_first=(filters["sort"] == "NEWEST"))
    visible_count = min(filters["visible"], len(items))
    page_items = items[:visible_count]

    next_url = build_url(filters, visible=filters["visible"])

    for item in page_items:
        category_value = item.get("category", "UNKNOWN")
        angle_value = item.get("contentAngle", "NEWS")
        status_value = item.get("status", "NEW")
        tier_value = item.get("sourceTier") or "MEDIA"
        posted_at = item.get("postedAt")

        item["_title"] = item.get("title") or "(제목 없음)"
        item["_badge"] = "🆕 " if is_new_today(item) else ""
        posted_label = (
            f"발행 {format_date_kst(posted_at)}"
            if isinstance(posted_at, datetime)
            else ("발행됨" if posted_at else "미발행")
        )
        item["_meta"] = " · ".join(
            value
            for value in [
                item.get("source"),
                CATEGORY_LABELS.get(category_value, category_value),
                ANGLE_LABELS.get(angle_value, angle_value),
                TIER_LABELS.get(tier_value, tier_value),
                STATUS_LABELS.get(status_value, status_value),
                posted_label,
                format_date_kst(effective_date(item)),
            ]
            if value
        )
        item["_summary"] = summary_preview(item)
        item["_metric_caption"] = metric_caption(item)

    counts = {
        "loaded": len(docs),
        "filtered": len(items),
        "new": sum(1 for item in items if item.get("status") == "NEW"),
        "today": sum(1 for item in items if is_new_today(item)),
    }

    return render_template(
        "index.html",
        items=page_items,
        counts=counts,
        filters=filters,
        categories=CATEGORIES,
        statuses=STATUSES,
        angles=ANGLES,
        source_tiers=SOURCE_TIERS,
        category_labels=CATEGORY_LABELS,
        status_labels=STATUS_LABELS,
        angle_labels=ANGLE_LABELS,
        tier_labels=TIER_LABELS,
        next_url=next_url,
        has_more=visible_count < len(items),
        more_url=build_url(filters, visible=filters["visible"] + CHUNK_SIZE),
        remaining=min(CHUNK_SIZE, len(items) - visible_count),
    )


@app.post("/items/<item_id>/status")
def set_status(item_id):
    status = request.form.get("status")
    if status in STATUSES:
        update_content(item_id, status=status)
    return redirect(safe_next(request.form.get("next")))


@app.post("/items/<item_id>/publish")
def publish_item(item_id):
    update_content(item_id, postedAt=datetime.now(timezone.utc))
    return redirect(safe_next(request.form.get("next")))


@app.post("/items/<item_id>/note")
def save_note(item_id):
    update_content(item_id, note=request.form.get("note", "").strip())
    return redirect(safe_next(request.form.get("next")))


@app.post("/manual")
def manual_add():
    next_url = safe_next(request.form.get("next"))
    url = (request.form.get("url") or "").strip()
    if not url:
        flash("URL을 입력해주세요.", "error")
        return redirect(next_url)

    title = request.form.get("title", "")
    category = request.form.get("category", "UNKNOWN")
    angle = request.form.get("angle", "NEWS")
    source_tier = request.form.get("source_tier", "MEDIA")

    try:
        created = add_manual_content(db(), url, title, category, angle, source_tier)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("저장했습니다." if created else "이미 저장된 URL입니다.", "success" if created else "info")
    return redirect(next_url)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
