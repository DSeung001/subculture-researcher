"""Local-only curation routes; Firebase is contacted only on explicit sync."""

from datetime import date

from sqlalchemy.exc import IntegrityError

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from subculture.drafts.infrastructure.ai_writer import AiWriterError, write_draft_posts
from subculture.drafts.domain.rules import MAX_SOURCES, DraftError
from subculture.drafts.application.drafts import create_draft
from subculture.library.application.export_images import ExportError, export_images, zip_export
from subculture.library.domain.taxonomy import FILTER_KEYS, TAXONOMIES
from subculture.library.infrastructure.local_library import Library
from subculture.library.infrastructure.database import SchemaError
from subculture.shared.presentation import card_view
from subculture.shared.paths import LOCAL_DIR


library = Blueprint("library", __name__, url_prefix="/library")

PAGE_SIZE = 50  # matches Library.items()
# saleStatus -> (label, badge class already used on the sources page)
SALE_STATUS = {
    "PREORDER": ("예약중", "status-manual"),
    "IN_STOCK": ("판매중", "status-enabled"),
    "SOLD_OUT": ("품절", "status-disabled"),
    "UNKNOWN": ("상태 미확인", "status-disabled"),
}
FILTER_LABELS = {"q": "검색", "deadline_from": "마감 시작", "deadline_to": "마감 끝"}


def store():
    return Library(current_app.config.get("LIBRARY_PATH"))


def show(items):
    """Give every row the same card model the inbox uses (payload = the Firestore document)."""
    for item in items:
        item["view"] = card_view(item["data"])


def filters_from(values):
    return {k: values.get(k, "").strip() for k in FILTER_KEYS}


def active_filters(filters, terms, collection_id=None):
    """Chips for the applied filters; each link drops only that one filter."""
    def without(key):
        rest = {k: v for k, v in filters.items() if v and k != key}
        return url_for("library.index", **rest, collection=collection_id)

    chips = []
    for key in FILTER_KEYS:
        value = filters.get(key)
        if not value:
            continue
        if key in TAXONOMIES:
            name = next((t["name"] for t in terms[key] if str(t["id"]) == value), f"#{value}")
            label, shown = TAXONOMIES[key], name
        elif key == "unclassified":
            label, shown = "작품", "미분류만"
        else:
            label, shown = FILTER_LABELS[key], value
        chips.append({"label": label, "value": shown, "remove_url": without(key)})
    return chips


@library.get("")
def index():
    local = store()
    # Backfill FIGURE → 피규어 without waiting for a full cloud sync.
    local.auto_assign_product_categories()
    filters = filters_from(request.args)
    overview = local.overview()
    page = max(1, request.args.get("page", 1, type=int))
    collection_id = request.args.get("collection", type=int)
    collection = next((c for c in overview["collections"] if c["id"] == collection_id), None)
    if collection_id and not collection:
        flash("기획 묶음을 찾을 수 없습니다.", "error")
        return redirect(url_for("library.index"))
    try:
        items, total = local.items(filters, page, collection_id)
    except ValueError:
        flash("예약 마감일을 올바른 날짜로 입력해주세요.", "error")
        return redirect(url_for("library.index"))
    terms = local.terms()
    show(items)
    return render_template(
        "library.html", items=items, total=total, terms=terms, taxonomies=TAXONOMIES,
        filters=filters, page=page, collection=collection, **overview,
        active=active_filters(filters, terms, collection_id), today=date.today().isoformat(),
        draft_max=MAX_SOURCES,
        pages=max(1, -(-total // PAGE_SIZE)), sale_status=SALE_STATUS,
        page_url=lambda p: url_for("library.index", **filters, page=p, collection=collection_id),
    )


@library.post("/sync")
def sync():
    try:
        count = store().sync(current_app.config["LIBRARY_CLOUD_DB"]())
    except Exception:
        current_app.logger.exception("Local library sync failed")
        flash("동기화에 실패했습니다. 연결·인증을 확인해주세요. 기존 로컬 데이터는 유지됩니다.", "error")
    else:
        flash(f"{count}개 항목을 동기화했습니다. 직접 지정한 분류와 기획은 유지됩니다.", "success")
    return redirect(url_for("library.index"))


@library.get("/settings")
def settings():
    return render_template("library_settings.html", terms=store().terms(), taxonomies=TAXONOMIES)


@library.get("/works/<int:work_id>")
def work_edit(work_id):
    local = store()
    work = local.work(work_id)
    try:
        items, total = local.items({"works": work_id}, page=max(1, request.args.get("page", 1, type=int)))
    except ValueError:
        flash("작품을 찾을 수 없습니다.", "error")
        return redirect(url_for("library.settings"))
    show(items)
    return render_template(
        "library_work.html", work=work, items=items, total=total,
        page=max(1, request.args.get("page", 1, type=int)),
        page_url=lambda p: url_for("library.work_edit", work_id=work_id, page=p),
    )


@library.post("/works/<int:work_id>")
def work_save(work_id):
    local = store()
    action = request.form.get("action")
    if action == "delete":
        local.delete_term("works", work_id)
        flash("작품과 해당 연결을 삭제했습니다. 수집 항목은 유지됩니다.", "success")
        return redirect(url_for("library.settings"))
    if action == "auto_assign":
        linked = local.auto_assign_works(work_id=work_id)
        flash(f"키워드로 {linked}개 연결을 추가했습니다.", "success")
        return redirect(url_for("library.work_edit", work_id=work_id))
    if action == "unlink":
        item_id = request.form.get("item_id")
        if item_id:
            local.assign([item_id], "works", work_id, remove=True)
            flash("작품 연결을 해제했습니다.", "success")
        return redirect(url_for("library.work_edit", work_id=work_id))
    local.save_term("works", request.form.get("name", ""), work_id, request.form.get("aliases", ""))
    flash("작품 정보를 저장했습니다.", "success")
    return redirect(url_for("library.work_edit", work_id=work_id))


@library.post("/works/auto-assign")
def works_auto_assign():
    linked = store().auto_assign_works()
    flash(f"전체 작품 키워드로 {linked}개 연결을 추가했습니다.", "success")
    return redirect(url_for("library.settings"))


@library.post("/terms/<table>")
def term(table):
    local = store()
    term_id = request.form.get("id", type=int)
    if request.form.get("action") == "delete":
        local.delete_term(table, term_id)
        flash("분류와 해당 연결을 삭제했습니다. 수집 항목은 유지됩니다.", "success")
    else:
        local.save_term(table, request.form.get("name", ""), term_id, request.form.get("aliases", ""))
        flash("분류 사전을 저장했습니다.", "success")
    return redirect(url_for("library.settings"))


@library.post("/assign")
def assign():
    store().assign(request.form.getlist("item_ids"), request.form.get("table"),
                   request.form.get("term_id", type=int), request.form.get("action") == "remove")
    flash("선택한 항목의 분류를 변경했습니다.", "success")
    return back()


def back():
    # Keep local browsing state without allowing external redirects.
    target = request.form.get("next", "")
    if not (target == "/library" or target.startswith("/library?")) or "\\" in target:
        target = url_for("library.index")
    return redirect(target)


@library.post("/collections")
def collection_save():
    local = store()
    collection_id = request.form.get("id", type=int)
    if request.form.get("action") == "delete":
        local.delete_collection(collection_id)
        return redirect(url_for("library.index"))
    collection_id = local.save_collection(request.form.get("name", ""), request.form.get("note", ""), collection_id)
    return redirect(url_for("library.index", collection=collection_id))


@library.post("/collections/add")
def collection_add():
    collection_id = request.form.get("collection_id", type=int)
    store().add_to_collection(collection_id, request.form.getlist("item_ids"))
    flash("선택한 항목을 기획에 담았습니다.", "success")
    return back()


@library.post("/collections/member")
def collection_member():
    store().remove_member(request.form.get("collection_id", type=int), request.form.get("item_id"))
    return back()


@library.post("/drafts")
def draft_create():
    """Turn the selected items into a draft and open it on the drafts page.

    mode=plain builds a title/link list (no AI); mode=ai has the model write the body.
    Items here are always in the local copy, so Firestore is never read.
    """
    ai = request.form.get("mode") == "ai"
    try:
        draft_id = create_draft(
            store(), request.form.getlist("item_ids"), body_factory=write_draft_posts if ai else None,
        )
    except (DraftError, AiWriterError) as exc:
        flash(str(exc), "error")
        return back()
    flash("글을 만들었습니다. 본문을 다듬어 저장하세요.", "success")
    return redirect(url_for("drafts_page", _anchor=f"draft-{draft_id}"))


@library.post("/export-images")
def export_item_images():
    """Download main + detail images for the selected items as a ZIP (index.json inside)."""
    from datetime import datetime, timezone

    item_ids = request.form.getlist("item_ids")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        root = export_images(
            store(), item_ids,
            directory=LOCAL_DIR / "image_exports" / stamp,
        )
        archive = zip_export(root)
    except ExportError as exc:
        flash(str(exc), "error")
        return back()
    return send_file(
        archive,
        as_attachment=True,
        download_name=f"library-images-{stamp}.zip",
        mimetype="application/zip",
    )


@library.errorhandler(ValueError)
@library.errorhandler(IntegrityError)
def invalid_input(exc):
    message = "같은 이름이 이미 있거나 선택한 항목이 없습니다." if isinstance(exc, IntegrityError) else str(exc)
    flash(message, "error")
    if request.endpoint in {"library.term", "library.works_auto_assign"}:
        return redirect(url_for("library.settings"))
    if request.endpoint in {"library.work_edit", "library.work_save"}:
        work_id = request.view_args.get("work_id") if request.view_args else None
        if work_id:
            return redirect(url_for("library.work_edit", work_id=work_id))
        return redirect(url_for("library.settings"))
    return back()


@library.errorhandler(SchemaError)
def schema_upgrade_required(exc):
    return render_template("library_upgrade.html", message=str(exc)), 503
