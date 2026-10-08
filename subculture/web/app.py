import argparse
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from flask import Flask, jsonify, flash, redirect, render_template, request, url_for

from subculture.shared.firebase_client import get_db
from subculture.collection.application.manual_entry import add_manual_content
from subculture.shared.compare_post import BODY_TARGET, MAX_SOURCES, build_compare_posts
from subculture.shared.content_model import ANGLES, CATEGORIES, SOURCE_TIERS, STATUSES, category_collection, content_id, content_ref
from subculture.collection.infrastructure.sources_config import load_sources
from subculture.collection.domain.image_collection import image_collection_flags

load_dotenv()
from subculture.shared.presentation import ANGLE_LABELS, CATEGORY_LABELS, REGION_LABELS, STATUS_LABELS, TIER_LABELS, card_view, sort_items


PAGE_SIZE = 30
# Inbox default: unreviewed items collected recently; older ones stay reachable via 「전체 기간」.
DAY_CHOICES = ("7", "14", "30", "ALL")
DEFAULT_DAYS = "14"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

_db = None


def db():
    global _db
    if _db is None:
        _db = get_db()
    return _db


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


RECOMMENDATION_POOL_DAYS = 14
RECOMMENDATION_POOL_LIMIT = 200
RECOMMENDATION_COUNT = 10


def fetch_recommended_items(days: int = RECOMMENDATION_POOL_DAYS, limit: int = RECOMMENDATION_POOL_LIMIT):
    """Top-scoring, not-yet-posted items across every category, independent of the page's
    own filter chips - a fixed "what to post next" pool, not a view of the filtered list."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        db().collection_group("contents")
        .where(filter=FieldFilter("collectedAt", ">=", cutoff))
        .order_by("collectedAt", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    candidates = []
    for snapshot in query.stream():
        item = snapshot.to_dict()
        if item.get("status") == "IGNORE" or item.get("postedAt"):
            continue
        item["_id"] = snapshot.id
        item["_ref"] = content_id(snapshot)
        item["_category"] = item["_ref"].partition(":")[0]
        item["_view"] = card_view(item)
        candidates.append(item)
    candidates.sort(key=lambda item: item["_view"]["signal_score"], reverse=True)
    return candidates[:RECOMMENDATION_COUNT]


@app.get("/")
def home():
    """The app opens on the inbox, which lives at /inbox."""
    return redirect(url_for("index"))


@app.get("/inbox")
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
        # Same card model as the static site list (presentation.card_view).
        item["_view"] = card_view(item)

    more_url = build_url(list_filters, after=cursor_id) if has_more and cursor_id else ""

    return render_template(
        "index.html",
        items=items,
        recommended_items=fetch_recommended_items(),
        recommended_days=RECOMMENDATION_POOL_DAYS,
        max_sources=MAX_SOURCES,
        body_target=BODY_TARGET,
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
    for source in sources:
        source["_image"] = image_collection_flags(source)

    return render_template(
        "sources.html",
        sources=sources,
        status=status,
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


@app.post("/compare")
def compare_page():
    """Comparison post from the items ticked in the list. Shown once; nothing is stored."""
    wants_json = request.accept_mimetypes.best == "application/json"
    def failure(message):
        if wants_json:
            return jsonify(error=message), 400
        flash(message, "error")
        return redirect(next_url)

    next_url = safe_next(request.form.get("next"))
    ids = list(dict.fromkeys(value.strip() for value in request.form.getlist("source_ids") if value.strip()))
    if not ids:
        return failure("항목을 선택해주세요.")
    if len(ids) > MAX_SOURCES:
        return failure(f"비교글 재료는 {MAX_SOURCES}개까지입니다.")
    try:
        refs = [content_ref(db(), source_id) for source_id in ids]
    except ValueError as exc:
        return failure(str(exc))
    # get_all may return snapshots in any order; match them by their own path.
    found = {content_id(snapshot): snapshot.to_dict() for snapshot in db().get_all(refs) if snapshot.exists}
    items = [found[source_id] for source_id in ids if source_id in found]
    if not items:
        return failure("선택한 항목을 찾을 수 없습니다.")
    if wants_json:
        posts = build_compare_posts(items)
        return jsonify(body=posts.body, reply=posts.reply, count=len(items), bodyTarget=BODY_TARGET,
                       missingCount=len(ids) - len(items))
    for item in items:
        item["_view"] = card_view(item)
    return render_template(
        "compare.html",
        items=items,
        posts=build_compare_posts(items),
        body_target=BODY_TARGET,
        next_url=next_url,
    )


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


def main(argv=None):
    # Parse first so `--help` prints usage instead of starting (or failing to bind) the server.
    argparse.ArgumentParser(
        description="로컬 검토 UI (http://127.0.0.1:5001)",
    ).parse_args(argv)
    app.run(host="127.0.0.1", port=5001, debug=True)


if __name__ == "__main__":
    main()
