"""Read-only static site for GitHub Pages: one data file of item cards plus a shell page.

The page never talks to Firestore. This build reads it once (with the service account the
collection run already uses) and writes plain files, so no key reaches the browser.
"""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from subculture.library.application.catalog import load_catalog
from subculture.library.domain.keywords import compile_works, match_works
from subculture.shared.content_model import content_id
from subculture.shared.firebase_client import get_db
from subculture.shared.paths import PROJECT_ROOT
from subculture.shared.presentation import CATEGORY_LABELS, card_view, effective_date

WEB_DIR = Path(__file__).resolve().parent
SITE_ASSETS = WEB_DIR / "site"
# Shared with the local review UI so both render the same cards.
SHARED_STATIC = ("style.css", "app.js")
DEFAULT_OUT = PROJECT_ROOT / "site"


def _iso(value) -> str:
    if not isinstance(value, datetime):
        return ""
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def site_item(source_id: str, data: dict, compiled_works) -> dict:
    """One card of the static list: the shared card view plus what the page filters and sorts on."""
    view = card_view(data)
    view["score_breakdown"] = [list(pair) for pair in view["score_breakdown"]]
    return {
        "id": source_id,
        "view": view,
        "category": data.get("category") or "UNKNOWN",
        "source": data.get("source") or "",
        "works": match_works(data, compiled_works),
        "date": _iso(effective_date(data)),
        "collected": _iso(data.get("collectedAt")),
        "posted": bool(data.get("postedAt")),
    }


def build(docs, works, out_dir, *, now: datetime | None = None) -> int:
    """Write the site into out_dir from (item id, document) pairs. Returns the number of items."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    compiled = compile_works(works)
    items = [
        site_item(source_id, data, compiled)
        for source_id, data in docs
        if data.get("status") != "IGNORE"
    ]
    payload = {
        "builtAt": _iso(now or datetime.now(timezone.utc)),
        "categoryLabels": CATEGORY_LABELS,
        "items": items,
    }
    (out_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8",
    )
    for asset in SITE_ASSETS.iterdir():
        shutil.copyfile(asset, out_dir / asset.name)
    for name in SHARED_STATIC:
        shutil.copyfile(WEB_DIR / "static" / name, out_dir / name)
    # Pages runs Jekyll on plain uploads unless told not to.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return len(items)


def cloud_docs(db):
    for snapshot in db.collection_group("contents").stream():
        yield content_id(snapshot), snapshot.to_dict()


def main(argv=None):
    parser = argparse.ArgumentParser(description="보기 전용 정적 사이트 생성 (GitHub Pages 배포용)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="출력 폴더 (기본: site/)")
    args = parser.parse_args(argv)
    count = build(cloud_docs(get_db()), load_catalog(), args.out)
    print(f"{count}개 항목으로 {args.out} 생성 완료")


if __name__ == "__main__":
    main()
