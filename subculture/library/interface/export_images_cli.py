"""Download product main + detail images from the local library into $FIGURE_PROJECT_DIR/exports."""

import argparse

from dotenv import load_dotenv

from subculture.library.application.export_images import (
    ExportError, ExportOptions, export_images, resolve_item_ids, zip_export,
)
from subculture.library.infrastructure.local_library import Library


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Override database URL or legacy SQLite path")
    parser.add_argument("--ids", nargs="+", help="Item ids (CATEGORY:document_id)")
    parser.add_argument("--work-id", type=int, help="All items linked to this work")
    parser.add_argument("--collection-id", type=int, help="All items in this collection")
    parser.add_argument("--out", help="Output directory (default: $FIGURE_PROJECT_DIR/exports/<stamp>, ~/figure_project if unset)")
    parser.add_argument("--zip", action="store_true", help="Also write a .zip next to the folder")
    parser.add_argument("--pause", type=float, default=0.35, help="Seconds between items (default 0.35)")
    parser.add_argument(
        "--no-skip", action="store_true",
        help="Download again even when ledger.jsonl says an image URL was already saved",
    )
    args = parser.parse_args()
    library = Library(args.db)
    try:
        item_ids = resolve_item_ids(
            library, item_ids=args.ids, work_id=args.work_id, collection_id=args.collection_id,
        )
        root = export_images(
            library, item_ids,
            directory=args.out,
            options=ExportOptions(pause_seconds=args.pause, skip_downloaded=not args.no_skip),
        )
    except ExportError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"내보냄: {root}")
    if args.zip:
        archive = zip_export(root)
        print(f"ZIP: {archive}")


if __name__ == "__main__":
    main()
