import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from dotenv import load_dotenv
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from flask import Flask, Response, jsonify, flash, redirect, render_template, request, url_for

from subculture.shared.firebase_client import get_db
from subculture.collection.application.manual_entry import add_manual_content
from subculture.shared.compare_post import BODY_TARGET, MAX_SOURCES, build_compare_posts
from subculture.shared.content_model import ANGLES, CATEGORIES, SOURCE_TIERS, STATUSES, category_collection, content_id, content_ref
from subculture.collection.infrastructure.sources_config import load_sources
from subculture.collection.domain.image_collection import image_collection_flags
from subculture.collection.domain.extract_profile import ExtractProfileError, normalize_extract
from subculture.collection.infrastructure.extractors_config import (
    extractor_path_for,
    save_extractor,
    supports_visual_extract,
)
from subculture.collection.infrastructure.mapped_extract import extract_list_items
from subculture.collection.infrastructure.preview_fetch import preview_document
from subculture.collection.infrastructure.collectors.common import RobotsDenied

load_dotenv()
from subculture.shared.presentation import ANGLE_LABELS, CATEGORY_LABELS, REGION_LABELS, STATUS_LABELS, TIER_LABELS, card_view, sort_items

REGIONS = ("KR", "JP", "US", "CN")


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


def find_source(name: str) -> dict | None:
    decoded = unquote(name)
    for source in load_sources():
        if source.get("name") == decoded:
            return source
    return None


@app.get("/sources")
def sources_page():
    status = request.args.get("status", "ALL")
    if status not in {"ALL", "ENABLED", "DISABLED", "MANUAL"}:
        status = "ALL"

    all_sources = load_sources()
    sources = all_sources if status == "ALL" else [s for s in all_sources if _source_status(s) == status]
    for source in sources:
        source["_image"] = image_collection_flags(source)
        source["_visual_extract"] = supports_visual_extract(source)
        source["_has_extract"] = bool(source.get("extract"))

    return render_template(
        "sources.html",
        sources=sources,
        status=status,
        category_labels=CATEGORY_LABELS,
        region_labels=REGION_LABELS,
        tier_labels=TIER_LABELS,
    )


@app.get("/sources/new")
def source_new_page():
    return render_template(
        "source_new.html",
        categories=CATEGORIES,
        regions=REGIONS,
        angles=ANGLES,
        source_tiers=SOURCE_TIERS,
        category_labels=CATEGORY_LABELS,
        region_labels=REGION_LABELS,
        angle_labels=ANGLE_LABELS,
        tier_labels=TIER_LABELS,
    )


@app.post("/sources/new")
def source_new_save():
    name = (request.form.get("name") or "").strip()
    url = (request.form.get("url") or "").strip()
    if not name or not url:
        flash("이름과 목록 URL이 필요합니다.", "error")
        return redirect(url_for("source_new_page"))
    if find_source(name) is not None:
        flash("같은 이름의 소스가 이미 있습니다.", "error")
        return redirect(url_for("source_new_page"))
    category = request.form.get("category", "GOODS")
    if category not in CATEGORIES:
        category = "GOODS"
    region = request.form.get("region", "KR")
    if region not in REGIONS:
        region = "KR"
    angle = request.form.get("content_angle", "PRICE")
    if angle not in ANGLES:
        angle = "PRICE"
    tier = request.form.get("source_tier", "MEDIA")
    if tier not in SOURCE_TIERS:
        tier = "MEDIA"
    payload = {
        "name": name,
        "url": url,
        "type": "html",
        "region": region,
        "category": category,
        "content_angle": angle,
        "source_tier": tier,
        "enabled": False,
        "respect_robots": True,
        "max_items": int(request.form.get("max_items") or 40),
        "render_js": request.form.get("render_js") == "1",
    }
    try:
        save_extractor(payload)
    except ExtractProfileError as exc:
        flash(str(exc), "error")
        return redirect(url_for("source_new_page"))
    flash("소스를 추가했습니다. 추출 설정을 이어서 만드세요.", "success")
    return redirect(url_for("source_extract_page", name=name))


@app.get("/sources/<path:name>/extract")
def source_extract_page(name):
    source = find_source(name)
    if source is None:
        flash("소스를 찾을 수 없습니다.", "error")
        return redirect(url_for("sources_page"))
    if not supports_visual_extract(source):
        flash("이 소스 유형은 클릭 추출을 지원하지 않습니다.", "error")
        return redirect(url_for("sources_page"))
    extract = source.get("extract") or {"list": {"item": "", "fields": {}}}
    return render_template(
        "source_extract.html",
        source=source,
        extract=extract,
        field_labels={
            "link": "링크",
            "title": "제목",
            "price": "가격",
            "image": "대표 사진",
            "status": "판매 상태",
            "deadline": "예약 마감",
            "published": "게시일",
            "gallery": "상세 갤러리",
        },
    )


@app.get("/sources/<path:name>/extract/preview")
def source_extract_preview(name):
    source = find_source(name)
    if source is None or not supports_visual_extract(source):
        return Response("소스를 찾을 수 없습니다.", status=404, mimetype="text/plain; charset=utf-8")
    detail_url = (request.args.get("url") or "").strip() or None
    try:
        html, _final = preview_document(source, detail_url)
    except RobotsDenied as exc:
        return Response(f"robots.txt로 미리보기를 열 수 없습니다.\n{exc}", status=403, mimetype="text/plain; charset=utf-8")
    except Exception as exc:
        return Response(f"미리보기 실패: {exc}", status=502, mimetype="text/plain; charset=utf-8")
    response = Response(html, mimetype="text/html; charset=utf-8")
    # Opaque origin even when the preview URL is opened directly, outside the iframe.
    response.headers["Content-Security-Policy"] = "sandbox allow-scripts"
    return response


@app.post("/sources/<path:name>/extract/sample")
def source_extract_sample(name):
    source = find_source(name)
    if source is None or not supports_visual_extract(source):
        return jsonify(error="소스를 찾을 수 없습니다."), 404
    body = request.get_json(silent=True) or {}
    try:
        extract = normalize_extract(body.get("extract"))
    except ExtractProfileError as exc:
        return jsonify(error=str(exc)), 400
    html = body.get("html")
    base_url = (body.get("base_url") or source.get("url") or "").strip()
    if not html:
        try:
            from subculture.collection.infrastructure.preview_fetch import fetch_page_html
            html, base_url = fetch_page_html(source, body.get("url") or None)
        except Exception as exc:
            return jsonify(error=f"목록을 가져오지 못했습니다: {exc}"), 502
    probe = {**source, "extract": extract}
    items = extract_list_items(html, base_url, probe)[:20]
    rows = [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "price": item.get("price"),
            "saleStatus": item.get("saleStatus"),
            "imageUrl": item.get("imageUrl"),
            "publishedAt": item.get("publishedAt"),
        }
        for item in items
    ]
    return jsonify(count=len(rows), items=rows, base_url=base_url)


@app.post("/sources/<path:name>/extract")
def source_extract_save(name):
    source = find_source(name)
    if source is None or not supports_visual_extract(source):
        flash("소스를 찾을 수 없습니다.", "error")
        return redirect(url_for("sources_page"))
    body = request.get_json(silent=True)
    if body is None:
        # Form posts may send extract as a JSON string field.
        raw = request.form.get("extract_json")
        if raw:
            try:
                body = {"extract": json.loads(raw)}
            except json.JSONDecodeError:
                flash("추출 설정 JSON이 잘못되었습니다.", "error")
                return redirect(url_for("source_extract_page", name=source["name"]))
        else:
            flash("추출 설정이 비어 있습니다.", "error")
            return redirect(url_for("source_extract_page", name=source["name"]))
    try:
        extract = normalize_extract(body.get("extract"))
    except ExtractProfileError as exc:
        if request.is_json or request.accept_mimetypes.best == "application/json":
            return jsonify(error=str(exc)), 400
        flash(str(exc), "error")
        return redirect(url_for("source_extract_page", name=source["name"]))

    payload = {"name": source["name"], "extract": extract}
    if source.get("_from_extractor"):
        # Keep the standalone source definition fields when rewriting the file.
        for key in (
            "url", "type", "region", "category", "content_angle", "source_tier",
            "enabled", "respect_robots", "max_items", "render_js", "shop",
            "page_param", "max_pages", "allow_patterns", "deny_patterns",
        ):
            if key in source:
                payload[key] = source[key]
    path = source.get("_extractor_path")
    try:
        saved = save_extractor(
            payload,
            path=path if path else extractor_path_for(source["name"]),
        )
    except ExtractProfileError as exc:
        if request.is_json:
            return jsonify(error=str(exc)), 400
        flash(str(exc), "error")
        return redirect(url_for("source_extract_page", name=source["name"]))
    if request.is_json or request.accept_mimetypes.best == "application/json":
        return jsonify(ok=True, path=str(saved))
    flash("추출 설정을 저장했습니다.", "success")
    return redirect(url_for("source_extract_page", name=source["name"]))


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
