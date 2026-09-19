"""Download Firestore metadata to the local curation database, without AI calls."""

import argparse

from subculture.shared.firebase_client import get_db
from subculture.library.infrastructure.local_library import Library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Override database URL or legacy SQLite path")
    args = parser.parse_args()
    count = Library(args.db).sync(get_db())
    print(f"{count}개 항목 동기화 완료")


if __name__ == "__main__":
    main()
