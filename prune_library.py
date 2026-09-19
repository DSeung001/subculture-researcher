"""Delete local items that no longer exist in Firestore and carry no local work.

Items with work links, tags, product categories, information types or collection
membership are kept and only listed. A backup is made first; without one nothing is deleted.
"""

import argparse

from dotenv import load_dotenv

from content_model import content_id
from firebase_client import get_db
from library_database import backup_library
from local_library import Library

load_dotenv()


def cloud_item_ids(db) -> set[str]:
    # Ids only: no document bodies are read.
    return {content_id(snapshot) for snapshot in db.collection_group("contents").select([]).stream()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="삭제하지 않고 대상 목록만 출력")
    parser.add_argument("--db", help="Override database URL or legacy SQLite path")
    args = parser.parse_args(argv)

    library = Library(args.db)
    cloud_ids = cloud_item_ids(get_db())
    preview = library.delete_orphans(cloud_ids, dry_run=True)
    for label, items in (("삭제 대상", preview["items"]), ("작업이 있어 보존", preview["kept_curated"])):
        print(f"[{label}] {len(items)}건")
        for item in items:
            print(f"  - {item['id']} [{item['source']}] {item['title']}")
    if args.dry_run or not preview["items"]:
        return

    backup = backup_library(library.engine)  # raises on failure: nothing is deleted without a backup
    print(f"[백업] {backup}")
    result = library.delete_orphans(cloud_ids)
    print(f"[삭제] {result['deleted']}건")


if __name__ == "__main__":
    main()
