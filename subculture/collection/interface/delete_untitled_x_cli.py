"""Delete leftover '(제목 없음)' documents (X status posts, the laftel.net home) from Firestore."""

import argparse

from dotenv import load_dotenv

from subculture.collection.application.untitled_cleanup import delete_untitled_x_contents
from subculture.shared.firebase_client import get_db

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
    args = parser.parse_args(argv)
    _print_result("Firestore", delete_untitled_x_contents(get_db(), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
