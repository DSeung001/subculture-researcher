"""Delete the temporary posts still stored in Firestore (`drafts` collection).

Drafts now live in the local library. Every document is exported to
`.local/backups/firestore-drafts-<time>.json` first; if that export fails nothing is deleted.
Published (POSTED) drafts are only removed with --include-posted.
"""

import argparse
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from firebase_client import get_db

load_dotenv()

BACKUP_DIR = Path(__file__).parent / ".local" / "backups"
BATCH = 400


def _json(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def firestore_drafts(db) -> list:
    return list(db.collection("drafts").stream())


def export_drafts(snapshots, directory: Path = BACKUP_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"firestore-drafts-{stamp}.json"
    payload = [{"id": snapshot.id, **(snapshot.to_dict() or {})} for snapshot in snapshots]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json), encoding="utf-8")
    return path


def delete_drafts(db, *, dry_run: bool = False, include_posted: bool = False, backup_dir: Path = BACKUP_DIR) -> dict:
    snapshots = firestore_drafts(db)
    statuses = Counter((snapshot.to_dict() or {}).get("status") for snapshot in snapshots)
    if statuses.get("POSTED") and not include_posted:
        raise ValueError(
            f"발행된 임시글 {statuses['POSTED']}건이 있습니다. 함께 지우려면 --include-posted를 지정하세요."
        )
    result = {"matched": len(snapshots), "deleted": 0, "statuses": dict(statuses), "backup": None, "dry_run": dry_run}
    if dry_run or not snapshots:
        return result
    result["backup"] = export_drafts(snapshots, backup_dir)  # raises on failure: nothing is deleted
    for start in range(0, len(snapshots), BATCH):
        batch = db.batch()
        for snapshot in snapshots[start:start + BATCH]:
            batch.delete(snapshot.reference)
        batch.commit()
    result["deleted"] = len(snapshots)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="삭제하지 않고 대상과 상태만 출력")
    parser.add_argument("--include-posted", action="store_true", help="발행된 임시글도 삭제")
    args = parser.parse_args(argv)
    try:
        result = delete_drafts(get_db(), dry_run=args.dry_run, include_posted=args.include_posted)
    except ValueError as exc:
        parser.error(str(exc))
    label = "대상" if result["dry_run"] else "삭제"
    count = result["matched"] if result["dry_run"] else result["deleted"]
    print(f"[Firestore drafts] {label} {count}건 {result['statuses']}")
    if result["backup"]:
        print(f"[백업] {result['backup']}")


if __name__ == "__main__":
    main()
