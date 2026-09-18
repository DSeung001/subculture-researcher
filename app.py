import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from firebase_admin import firestore
from flask import Flask, flash, redirect, render_template, request, url_for

from ai_drafts import create_trending_draft
from ai_writer import AiWriterError
from firebase_client import get_db
from content_store import add_manual_content
from drafts_store import (
    DraftError,
    create_draft,
    delete_draft,
    list_drafts,
    publish_draft,
    save_body,
)
from sources_config import load_sources

load_dotenv()
from presentation import (
    date_caption,
    format_date_kst,
    is_new_today,
    metric_caption,
    product_caption,
    content_score,
    signal_labels,
    sort_items,
    split_leading_date,
    summary_preview,
)


CATEGORIES = ["ANIME", "CHARACTER", "FIGURE", "GOODS", "COLLECTION", "FESTIVAL", "UNKNOWN"]
STATUSES = ["NEW", "KEEP", "HOLD", "IGNORE"]
ANGLES = ["NEWS", "COMPARE", "SIZE", "PRICE", "QUESTION", "GUIDE", "COLLECTION"]
SOURCE_TIERS = ["OFFICIAL", "MEDIA"]

CATEGORY_LABELS = {
    "ANIME": "애니",
    "CHARACTER": "캐릭터",
    "FIGURE": "피규어",
    "GOODS": "굿즈",
    "COLLECTION": "컬렉션",
    "FESTIVAL": "페스티벌",
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
DRAFT_STATUSES = ["DRAFT", "POSTED"]
DRAFT_STATUS_LABELS = {
    "DRAFT": "초안",
    "POSTED": "발행됨",
}

PAGE_SIZE = 30

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

_db = None


def db():
    global _db
    if _db is None:
        _db = get_db()
    return _db


def update_content(category: str, document_id: str, **fields):
    db().collection("categories").document(category or "UNKNOWN").collection("contents").document(document_id).update(fields)


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
        "sort": request.args.get("sort", "RECOMMENDED"),
        "after": (request.args.get("after") or "").strip(),
    }


def build_url(filters: dict, **overrides) -> str:
    params = {**filters, **overrides}
    if not params.get("unposted"):
        params.pop("unposted", None)
    if not params.get("after"):
        params.pop("after", None)
    return url_for("index", **params)


def contents_query(category: str):
    # A chosen category reads its own collection; "ALL" merges every category via collection_group.
    if category and category != "ALL":
        return db().collection("categories").document(category).collection("contents")
    return db().collection_group("contents")


def cursor_token(snapshot) -> str:
    category = (snapshot.to_dict() or {}).get("category") or "UNKNOWN"
    return f"{category}:{snapshot.id}"


def resolve_cursor(token: str):
    category, _, doc_id = (token or "").partition(":")
    if not category or not doc_id:
        return None
    snapshot = db().collection("categories").document(category).collection("contents").document(doc_id).get()
    return snapshot if snapshot.exists else None


def fetch_contents_page(after_token: str, category: str):
    query = contents_query(category).order_by("collectedAt", direction=firestore.Query.DESCENDING)
    cursor = resolve_cursor(after_token)
    if cursor is not None:
        query = query.start_after(cursor)
    query = query.limit(PAGE_SIZE)
    docs = list(query.stream())
    return docs, len(docs) == PAGE_SIZE, (cursor_token(docs[-1]) if docs else "")


@app.get("/")
def index():
    filters = current_filters()
    unposted_only = filters["unposted"] == "1"

    docs, has_more, cursor_id = fetch_contents_page(filters["after"], filters["category"])

    items = []
    all_sources = set()
    for snapshot in docs:
        item = snapshot.to_dict()
        item["_id"] = snapshot.id
        item["_category"] = item.get("category") or "UNKNOWN"
        item["_ref"] = f"{item['_category']}:{item['_id']}"
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

    items = sort_items(
        items,
        newest_first=(filters["sort"] == "NEWEST"),
        recommended=(filters["sort"] == "RECOMMENDED"),
    )

    # Forms / filter chips reset the cursor; load-more keeps it.
    list_filters = {**filters, "after": ""}
    next_url = build_url(list_filters)

    for item in items:
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
        item["_product_caption"] = product_caption(item)
        item["_signal_score"] = content_score(item)
        item["_signal_labels"] = signal_labels(item)

    counts = {
        "loaded": len(docs),
        "filtered": len(items),
        "new": sum(1 for item in items if item.get("status") == "NEW"),
        "today": sum(1 for item in items if is_new_today(item)),
    }

    more_url = build_url(list_filters, after=cursor_id) if has_more and cursor_id else ""

    return render_template(
        "index.html",
        items=items,
        counts=counts,
        filters=list_filters,
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
        has_more=bool(more_url),
        more_url=more_url,
        remaining=PAGE_SIZE if more_url else 0,
        filter_url=lambda **overrides: build_url(list_filters, **overrides),
    )


def drafts_list_url(status: str | None = None) -> str:
    chosen = status or request.values.get("list_status") or "DRAFT"
    if chosen not in {"ALL", "DRAFT", "POSTED"}:
        chosen = "DRAFT"
    if chosen == "DRAFT":
        return url_for("drafts_page")
    return url_for("drafts_page", status=chosen)


@app.get("/drafts")
def drafts_page():
    status = request.args.get("status", "DRAFT")
    if status not in {"ALL", "DRAFT", "POSTED"}:
        status = "DRAFT"
    drafts = list_drafts(db(), status=status)
    for draft in drafts:
        created_at = draft.get("createdAt")
        posted_at = draft.get("postedAt")
        draft["_created"] = format_date_kst(created_at) if isinstance(created_at, datetime) else ""
        draft["_posted"] = format_date_kst(posted_at) if isinstance(posted_at, datetime) else ""
        angle = draft.get("angle") or "NEWS"
        draft["_angle_label"] = ANGLE_LABELS.get(angle, angle)
        draft["_status_label"] = DRAFT_STATUS_LABELS.get(draft.get("status"), draft.get("status"))
    return render_template(
        "drafts.html",
        drafts=drafts,
        status=status,
        draft_statuses=DRAFT_STATUSES,
        draft_status_labels=DRAFT_STATUS_LABELS,
        list_status=status,
    )


@app.post("/drafts")
def create_draft_item():
    next_url = safe_next(request.form.get("next"))
    try:
        create_draft(db(), request.form.getlist("source_ids"))
    except DraftError as exc:
        flash(str(exc), "error")
        return redirect(next_url)
    flash("글을 만들었습니다.", "success")
    return redirect(url_for("drafts_page"))


@app.post("/drafts/ai")
def create_ai_draft_item():
    try:
        draft_id = create_trending_draft(db())
    except (DraftError, AiWriterError) as exc:
        flash(str(exc), "error")
    else:
        flash("글을 만들었습니다." if draft_id else "AI로 쓸 만한 새 재료가 없습니다.", "success" if draft_id else "info")
    return redirect(url_for("drafts_page"))


@app.post("/drafts/<draft_id>/body")
def save_draft_body(draft_id):
    try:
        save_body(db(), draft_id, request.form.get("body", ""))
    except DraftError as exc:
        flash(str(exc), "error")
    else:
        flash("본문을 저장했습니다.", "success")
    return redirect(drafts_list_url())


@app.post("/drafts/<draft_id>/publish")
def publish_draft_item(draft_id):
    try:
        publish_draft(db(), draft_id)
    except DraftError as exc:
        flash(str(exc), "error")
        return redirect(drafts_list_url())
    flash("발행함으로 표시했습니다.", "success")
    return redirect(url_for("drafts_page", status="POSTED"))


@app.post("/drafts/<draft_id>/delete")
def delete_draft_item(draft_id):
    try:
        delete_draft(db(), draft_id)
    except DraftError as exc:
        flash(str(exc), "error")
    else:
        flash("글을 삭제했습니다.", "success")
    return redirect(drafts_list_url())


def _source_status(source: dict) -> str:
    if not source.get("enabled", True):
        return "DISABLED"
    if source.get("local_only"):
        return "MANUAL"
    return "ENABLED"


@app.get("/sources")
def sources_page():
    status = request.args.get("status", "ALL")
    if status not in {"ALL", "ENABLED", "DISABLED", "MANUAL"}:
        status = "ALL"

    all_sources = load_sources()
    counts = {"ALL": len(all_sources), "ENABLED": 0, "DISABLED": 0, "MANUAL": 0}
    for source in all_sources:
        counts[_source_status(source)] += 1

    sources = all_sources if status == "ALL" else [s for s in all_sources if _source_status(s) == status]

    return render_template(
        "sources.html",
        sources=sources,
        status=status,
        counts=counts,
        category_labels=CATEGORY_LABELS,
        region_labels=REGION_LABELS,
        tier_labels=TIER_LABELS,
    )


@app.post("/items/<category>/<item_id>/status")
def set_status(category, item_id):
    status = request.form.get("status")
    if status in STATUSES:
        update_content(category, item_id, status=status)
    return redirect(safe_next(request.form.get("next")))


@app.post("/items/<category>/<item_id>/publish")
def publish_item(category, item_id):
    update_content(category, item_id, postedAt=datetime.now(timezone.utc))
    return redirect(safe_next(request.form.get("next")))


@app.post("/items/<category>/<item_id>/note")
def save_note(category, item_id):
    update_content(category, item_id, note=request.form.get("note", "").strip())
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
