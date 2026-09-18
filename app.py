import os
from datetime import datetime, timezone

from firebase_admin import firestore
from flask import Flask, flash, redirect, render_template, request, url_for

from firebase_client import get_db
from content_store import add_manual_content
from sources_config import load_sources
from presentation import (
    date_caption,
    format_date_kst,
    is_new_today,
    metric_caption,
    sort_items,
    split_leading_date,
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
REGION_LABELS = {
    "JP": "일본",
    "KR": "국내",
}
LANGUAGE_TAGS = {
    "en": "EN",
    "ja": "JA",
    "zh": "CH",
    "zh-cn": "CH",
    "zh-tw": "CH",
    "ko": "KO",
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
        "source": request.args.get("source", "ALL"),
        "unposted": request.args.get("unposted", ""),
        "sort": request.args.get("sort", "NEWEST"),
        "limit": clamp(parse_int(request.args.get("limit"), 200), 20, 200),
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
    all_sources = set()
    for snapshot in docs:
        item = snapshot.to_dict()
        item["_id"] = snapshot.id
        if item.get("source"):
            all_sources.add(item["source"])

        if filters["category"] != "ALL" and item.get("category") != filters["category"]:
            continue
        if filters["status"] == "ACTIVE" and item.get("status") == "IGNORE":
            continue
        if filters["status"] != "ACTIVE" and item.get("status") != filters["status"]:
            continue
        if filters["tier"] != "ALL" and item.get("sourceTier") != filters["tier"]:
            continue
        if filters["source"] != "ALL" and item.get("source") != filters["source"]:
            continue
        if unposted_only and item.get("postedAt"):
            continue

        items.append(item)

    source_options = sorted(all_sources)

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

        original_title = item.get("title") or "(제목 없음)"
        title_ko = (item.get("titleKo") or "").strip()
        display_title = title_ko or original_title
        title_date, title_text = split_leading_date(display_title)
        original_date, original_text = split_leading_date(original_title)
        item["_title"] = display_title
        item["_title_date"] = title_date
        item["_title_text"] = title_text
        item["_original_title"] = original_title if title_ko and title_ko != original_title else ""
        item["_original_date"] = original_date
        item["_original_text"] = original_text
        source_language = (item.get("sourceLanguage") or "").strip().lower()
        item["_lang_tag"] = (
            LANGUAGE_TAGS.get(source_language, source_language.upper())
            if item["_original_title"] and source_language and source_language != "unknown"
            else ""
        )
        item["_is_new_today"] = is_new_today(item)
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
                date_caption(item),
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
        source_options=source_options,
        category_labels=CATEGORY_LABELS,
        status_labels=STATUS_LABELS,
        angle_labels=ANGLE_LABELS,
        tier_labels=TIER_LABELS,
        next_url=next_url,
        has_more=visible_count < len(items),
        more_url=build_url(filters, visible=filters["visible"] + CHUNK_SIZE),
        remaining=min(CHUNK_SIZE, len(items) - visible_count),
        filter_url=lambda **overrides: build_url(filters, visible=CHUNK_SIZE, **overrides),
    )


@app.get("/sources")
def sources_page():
    return render_template(
        "sources.html",
        sources=load_sources(),
        category_labels=CATEGORY_LABELS,
        region_labels=REGION_LABELS,
        tier_labels=TIER_LABELS,
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
    app.run(host="127.0.0.1", port=5001, debug=True)
