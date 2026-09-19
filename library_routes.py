"""Local-only curation routes; Firebase is contacted only on explicit sync."""

import json
from sqlalchemy.exc import IntegrityError

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from local_library import FILTER_KEYS, TAXONOMIES, Library
from library_database import SchemaError


library = Blueprint("library", __name__, url_prefix="/library")


def store():
    return Library(current_app.config.get("LIBRARY_PATH"))


def filters_from(values):
    return {k: values.get(k, "").strip() for k in FILTER_KEYS}


@library.get("")
def index():
    local = store()
    filters = filters_from(request.args)
    overview = local.overview()
    saved_id = request.args.get("saved", type=int)
    if saved_id:
        saved = next((f for f in overview["saved_filters"] if f["id"] == saved_id), None)
        if saved:
            return redirect(url_for("library.index", **json.loads(saved["filters"])))
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
    return render_template(
        "library.html", items=items, total=total, terms=terms, taxonomies=TAXONOMIES,
        filters=filters, page=page, collection=collection, **overview,
        suggestions=local.suggestions(items, terms["works"]),
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
        local.delete_group("collections", collection_id)
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
    collection_id = request.form.get("collection_id", type=int)
    store().edit_member(collection_id, request.form.get("item_id"), request.form.get("note", ""),
                        request.form.get("position", "0"), request.form.get("action") == "remove")
    return back()


@library.post("/filters")
def filter_save():
    if request.form.get("action") == "delete":
        store().delete_group("saved_filters", request.form.get("id", type=int))
    else:
        store().save_filter(request.form.get("name", ""), filters_from(request.form))
        flash("현재 필터를 저장했습니다.", "success")
    return back()


@library.errorhandler(ValueError)
@library.errorhandler(IntegrityError)
def invalid_input(exc):
    message = "같은 이름이 이미 있거나 선택한 항목이 없습니다." if isinstance(exc, IntegrityError) else str(exc)
    flash(message, "error")
    if request.endpoint == "library.term":
        return redirect(url_for("library.settings"))
    return back()


@library.errorhandler(SchemaError)
def schema_upgrade_required(exc):
    return render_template("library_upgrade.html", message=str(exc)), 503
