"""Download main + detail image URLs from local library items into a folder with index.json."""

from __future__ import annotations

import hashlib
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import requests
from sqlalchemy import exists, select

from subculture.library.infrastructure.local_library import Library
from subculture.library.infrastructure.models import CollectionItem, Item, ItemWork
from subculture.shared.image_urls import http_url
from subculture.shared.paths import image_export_dir

USER_AGENT = "SubcultureResearcher/0.1 (+https://github.com/DSeung001/subculture-researcher)"
DEFAULT_TIMEOUT = 30
DEFAULT_PAUSE = 0.35
FORMAT_VERSION = 2
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
_EXT_FROM_FORMAT = {"jpeg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp", "bmp": ".bmp"}


class ExportError(ValueError):
    """User-facing export failure (no items, bad args)."""


def resolve_item_ids(
    library: Library,
    *,
    item_ids: list[str] | None = None,
    work_id: int | None = None,
    collection_id: int | None = None,
) -> list[str]:
    """Ordered unique item ids from an explicit list and/or work/collection filters."""
    if item_ids:
        return list(dict.fromkeys(item_ids))
    if work_id is None and collection_id is None:
        raise ExportError("내보낼 항목 id, 작품 id, 또는 기획 id가 필요합니다.")
    query = select(Item.id)
    if work_id is not None:
        query = query.where(exists().where(ItemWork.item_id == Item.id, ItemWork.term_id == work_id))
    if collection_id is not None:
        query = query.where(
            exists().where(
                CollectionItem.item_id == Item.id,
                CollectionItem.collection_id == collection_id,
            )
        )
    with library.connect() as session:
        return [row[0] for row in session.execute(query.order_by(Item.id)).all()]


def export_images(
    library: Library,
    item_ids: list[str],
    *,
    directory: Path | None = None,
    pause_seconds: float = DEFAULT_PAUSE,
    timeout: float = DEFAULT_TIMEOUT,
    fetch=None,
) -> Path:
    """Write image files + index.json under `directory` (default stamped folder). Returns that path."""
    ids = list(dict.fromkeys(item_ids))
    if not ids:
        raise ExportError("내보낼 항목이 없습니다.")
    by_id = library.items_by_id(ids)
    missing = [item_id for item_id in ids if item_id not in by_id]
    if missing and not by_id:
        raise ExportError("선택한 항목을 로컬 DB에서 찾지 못했습니다. 먼저 동기화하세요.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = Path(directory) if directory is not None else image_export_dir() / stamp
    root.mkdir(parents=True, exist_ok=True)
    items_dir = root / "items"
    items_dir.mkdir(exist_ok=True)
    getter = fetch or _download
    index = []
    used_folders: set[str] = set()
    for position, item_id in enumerate(ids):
        data = by_id.get(item_id)
        if data is None:
            index.append({"id": item_id, "error": "not_in_library", "files": []})
            continue
        entry, files = _export_one(
            data, items_dir, used_folders, getter=getter, timeout=timeout,
        )
        index.append(entry)
        if pause_seconds > 0 and position + 1 < len(ids) and files:
            time.sleep(pause_seconds)
    records = [record for entry in index for record in entry["files"]]
    # export.json goes first: index.json stays the last file written (completion marker).
    (root / "export.json").write_text(
        json.dumps(
            {
                "formatVersion": FORMAT_VERSION,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "itemCount": len(index),
                "fileCount": len(records),
                "okCount": sum(1 for record in records if record["status"] == "ok"),
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    (root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return root


def zip_export(directory: Path, zip_path: Path | None = None) -> Path:
    """Zip an export folder; default sibling `.zip` next to the folder."""
    directory = Path(directory)
    archive = Path(zip_path) if zip_path is not None else directory.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(directory).as_posix())
    return archive


def _export_one(
    data: dict, items_dir: Path, used_folders: set[str], *, getter, timeout: float,
) -> tuple[dict, list[dict]]:
    item_id = data.get("_id") or ""
    folder_name = _folder_name(item_id, used_folders)
    dest = items_dir / folder_name
    dest.mkdir(parents=True, exist_ok=True)
    main = http_url(data.get("imageUrl"))
    details = []
    raw_details = data.get("detailImageUrls")
    if isinstance(raw_details, list):
        seen = {main} if main else set()
        for value in raw_details:
            url = http_url(value)
            if url and url not in seen:
                seen.add(url)
                details.append(url)
    jobs = []
    if main:
        jobs.append(("main", main))
    for url in details:
        jobs.append(("detail", url))
    files = []
    for index, (role, url) in enumerate(jobs):
        stem = f"{index:02d}_{role}"
        record = {
            "key": f"{folder_name}-{index:02d}",
            "role": role,
            "url": url,
            "path": None,
            "status": "error",
            "error": None,
            "format": None,
            "sha256": None,
            "bytes": None,
        }
        try:
            body, content_type = getter(url, timeout=timeout)
            image_format = _sniff_format(body)
            if image_format is None:
                # CDNs may answer 200 with an HTML error page; never save it as an image.
                raise ValueError(f"not_image: {content_type or 'unknown content type'}")
            ext = _EXT_FROM_FORMAT[image_format]
            (dest / f"{stem}{ext}").write_bytes(body)
            record.update(
                path=f"items/{folder_name}/{stem}{ext}",
                status="ok",
                format=image_format,
                sha256=hashlib.sha256(body).hexdigest(),
                bytes=len(body),
            )
        except Exception as exc:
            record["error"] = str(exc)
        files.append(record)
    entry = {
        "id": item_id,
        "title": data.get("title") or "",
        "titleKo": data.get("titleKo") or "",
        "url": http_url(data.get("url")) or data.get("url") or "",
        "shop": data.get("shop") or "",
        "category": data.get("category") or "",
        "source": data.get("source") or "",
        "imageUrl": main or "",
        "detailImageUrls": details,
        "files": files,
    }
    return entry, files


def _download(url: str, *, timeout: float) -> tuple[bytes, str | None]:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content, response.headers.get("Content-Type")


def _folder_name(item_id: str, used: set[str]) -> str:
    """Filesystem-safe folder name (no `:`), unique within one export."""
    base = _SAFE_ID.sub("_", item_id) or "item"
    name, suffix = base, 2
    while name in used:
        name, suffix = f"{base}-{suffix}", suffix + 1
    used.add(name)
    return name


def _sniff_format(body: bytes) -> str | None:
    """Image format from magic bytes; None when the body is not a supported image."""
    if body.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp"
    if body.startswith(b"BM"):
        return "bmp"
    return None
