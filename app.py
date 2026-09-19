import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from flask import Flask, flash, redirect, render_template, request, url_for

from ai_drafts import create_trending_draft, create_work_drafts
from ai_writer import AiWriterError
from firebase_client import get_db
from content_store import add_manual_content
from erd import build_erd
from content_model import (
    ANGLES, CATEGORIES, SOURCE_TIERS, STATUSES,
    category_collection, content_id, content_ref,
)
from drafts_store import (
    DraftError,
    create_draft,
    delete_draft,
    list_drafts,
    publish_draft,
    save_body,
)
from library_database import SchemaError
from local_library import Library
from sources_config import load_sources

load_dotenv()
from presentation import (
    ANGLE_LABELS,
    CATEGORY_LABELS,
    REGION_LABELS,
    STATUS_LABELS,
    TIER_LABELS,
    card_view,
    format_date_kst,
    sort_items,
)


DRAFT_STATUSES = ["DRAFT", "POSTED"]
DRAFT_STATUS_LABELS = {
    "DRAFT": "초안",
    "POSTED": "발행됨",
}

PAGE_SIZE = 30
# Inbox default: unreviewed items collected recently; older ones stay reachable via 「전체 기간」.
DAY_CHOICES = ("7", "14", "30", "ALL")
DEFAULT_DAYS = "14"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

from library_routes import library
app.register_blueprint(library)

_db = None


def db():
    global _db
    if _db is None:
        _db = get_db()
    return _db


app.config["LIBRARY_CLOUD_DB"] = db


def local_library() -> Library:
    """Drafts live in the local library; Firestore is only read/written for sources and publish marks."""
    return Library(app.config.get("LIBRARY_PATH"))


@app.errorhandler(SchemaError)
def schema_upgrade_required(exc):
    return render_template("library_upgrade.html", message=str(exc)), 503


def update_content(category: str, document_id: str, **fields):
    category_collection(db(), category).document(document_id).update(fields)


def safe_next(raw: str | None) -> str:
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return url_for("index")


def current_filters():
    days = request.args.get("days", DEFAULT_DAYS)
    return {
        "category": request.args.get("category", "ALL"),
        "status": request.args.get("status", "NEW"),
        "days": days if days in DAY_CHOICES else DEFAULT_DAYS,
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
        return category_collection(db(), category)
    return db().collection_group("contents")


def cursor_token(snapshot) -> str:
    return content_id(snapshot)


def resolve_cursor(token: str):
    if not token:
        return None
    try:
        ref = content_ref(db(), token)
    except ValueError:
        return None
    snapshot = ref.get()
    return snapshot if snapshot.exists else None


def fetch_contents_page(after_token: str, category: str, days: str = "ALL"):
    query = contents_query(category)
    if days != "ALL":
        # Same field as the order_by below, so no composite index is needed.
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        query = query.where(filter=FieldFilter("collectedAt", ">=", cutoff))
    query = query.order_by("collectedAt", direction=firestore.Query.DESCENDING)
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

    docs, has_more, cursor_id = fetch_contents_page(
        filters["after"], filters["category"], filters["days"],
    )

    items = []
    all_sources = set()
    for snapshot in docs:
        item = snapshot.to_dict()
        item["_id"] = snapshot.id
        item["_ref"] = content_id(snapshot)
        item["_category"] = item["_ref"].partition(":")[0]
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
        # Same card model as the local library list (presentation.card_view).
        item["_view"] = card_view(item)

    more_url = build_url(list_filters, after=cursor_id) if has_more and cursor_id else ""

    return render_template(
        "index.html",
        items=items,
        filters=list_filters,
        categories=CATEGORIES,
        statuses=STATUSES,
        angles=ANGLES,
        source_tiers=SOURCE_TIERS,
        day_choices=DAY_CHOICES,
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
    drafts = list_drafts(local_library(), status=status)
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
        create_draft(local_library(), request.form.getlist("source_ids"), cloud=db())
    except DraftError as exc:
        flash(str(exc), "error")
        return redirect(next_url)
    flash("글을 만들었습니다.", "success")
    return redirect(url_for("drafts_page"))


@app.post("/drafts/ai")
def create_ai_draft_item():
    try:
        draft_id = create_trending_draft(local_library())
    except (DraftError, AiWriterError) as exc:
        flash(str(exc), "error")
    else:
        flash("글을 만들었습니다." if draft_id else "AI로 쓸 만한 새 재료가 없습니다.", "success" if draft_id else "info")
    return redirect(url_for("drafts_page"))


@app.post("/drafts/ai/by-work")
def create_work_ai_draft_item():
    try:
        results = create_work_drafts(local_library())
    except SchemaError as exc:
        flash(str(exc), "error")
        return redirect(url_for("drafts_page"))
    except AiWriterError as exc:
        flash(str(exc), "error")
        return redirect(url_for("drafts_page"))

    created = sum(1 for _, draft_id, error in results if draft_id and not error)
    errors = [error for _, _, error in results if error]
    if created:
        flash(f"작품별 글 {created}개를 만들었습니다.", "success")
    elif errors:
        flash(errors[0], "error")
    else:
        flash("작품이 연결된 새 재료가 없습니다. 작품·기획에서 연결한 뒤 다시 시도해주세요.", "info")
    return redirect(url_for("drafts_page"))


@app.post("/drafts/<int:draft_id>/body")
def save_draft_body(draft_id):
    try:
        save_body(local_library(), draft_id, request.form.get("body", ""))
    except DraftError as exc:
        flash(str(exc), "error")
    else:
        flash("본문을 저장했습니다.", "success")
    return redirect(drafts_list_url())


@app.post("/drafts/<int:draft_id>/publish")
def publish_draft_item(draft_id):
    try:
        warnings = publish_draft(local_library(), draft_id, cloud=db())
    except DraftError as exc:
        flash(str(exc), "error")
        return redirect(drafts_list_url())
    flash("발행함으로 표시했습니다.", "success")
    for warning in warnings:
        flash(warning, "error")
    return redirect(url_for("drafts_page", status="POSTED"))


@app.post("/drafts/<int:draft_id>/delete")
def delete_draft_item(draft_id):
    try:
        delete_draft(local_library(), draft_id)
    except DraftError as exc:
        flash(str(exc), "error")
    else:
        flash("글을 삭제했습니다.", "success")
    return redirect(drafts_list_url())


def _source_status(source: dict) -> str:
    if not source.get("enabled", True):
        return "DISABLED"
    if source.get("local_only") or source.get("manual_only"):
        return "MANUAL"
    return "ENABLED"


@app.get("/sources")
def sources_page():
    status = request.args.get("status", "ALL")
    if status not in {"ALL", "ENABLED", "DISABLED", "MANUAL"}:
        status = "ALL"

    all_sources = load_sources()
    sources = all_sources if status == "ALL" else [s for s in all_sources if _source_status(s) == status]

    return render_template(
        "sources.html",
        sources=sources,
        status=status,
        category_labels=CATEGORY_LABELS,
        region_labels=REGION_LABELS,
        tier_labels=TIER_LABELS,
    )


@app.get("/erd")
def erd_page():
    # Static schema view: no DB connection, so it works even before Docker is up.
    return render_template("erd.html", erd=build_erd())


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
    image_url = request.form.get("image_url", "")

    try:
        created = add_manual_content(db(), url, title, category, angle, source_tier, image_url)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("저장했습니다." if created else "이미 저장된 URL입니다.", "success" if created else "info")
    return redirect(next_url)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
