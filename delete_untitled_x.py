"""Delete leftover '(제목 없음)' documents (X status posts, the laftel.net home) from Firestore and local DB."""

import argparse

from dotenv import load_dotenv

from content_store import delete_untitled_x_contents
from firebase_client import get_db
from local_library import Library

load_dotenv()


def _print_result(label: str, result: dict) -> None:
    action = "대상" if result["dry_run"] else "삭제"
    print(f"[{label}] {action} {result['matched']}건")
    for item in result["items"]:
        print(f"  - {item['id']}: {item['url']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="삭제하지 않고 대상 목록만 출력",
    )
    parser.add_argument("--db", help="Override database URL or legacy SQLite path")
    parser.add_argument(
        "--firestore-only",
        action="store_true",
        help="Firestore만 정리 (로컬 DB는 건너뜀)",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="로컬 DB만 정리 (Firestore는 건너뜀)",
    )
    args = parser.parse_args(argv)
    if args.firestore_only and args.local_only:
        parser.error("--firestore-only와 --local-only는 함께 쓸 수 없습니다.")

    if not args.local_only:
        cloud = delete_untitled_x_contents(get_db(), dry_run=args.dry_run)
        _print_result("Firestore", cloud)

    if not args.firestore_only:
        local = Library(args.db).delete_untitled_x(dry_run=args.dry_run)
        _print_result("로컬", local)


if __name__ == "__main__":
    main()
