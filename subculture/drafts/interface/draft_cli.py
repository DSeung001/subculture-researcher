"""Create AI-written drafts from unposted inbox items (no collection)."""

import argparse

from dotenv import load_dotenv

from subculture.drafts.application.ai_drafts import run_local_trending_draft, run_work_drafts
from subculture.shared.content_model import CATEGORIES
from subculture.library.infrastructure.database import SchemaError
from subculture.library.infrastructure.local_library import Library

load_dotenv()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="미게시 인박스 항목으로 AI 임시글 초안 만들기 (수집 없음)",
    )
    parser.add_argument(
        "--category",
        choices=CATEGORIES,
        help="이 카테고리의 미게시 항목만 후보로 사용 (혼합 경로)",
    )
    parser.add_argument(
        "--by-work",
        action="store_true",
        help="로컬 DB의 확인된 작품 연결로 피규어·애니·혼합 초안 만들기",
    )
    parser.add_argument("--db", help="로컬 DB URL 또는 레거시 SQLite 경로")
    args = parser.parse_args(argv)
    if args.by_work and args.category:
        parser.error("--by-work와 --category는 함께 쓸 수 없습니다")

    if args.by_work:
        try:
            library = Library(args.db)
        except SchemaError as exc:
            print(f"[작품 초안] 실패: {exc}")
            return
        print(run_work_drafts(library))
        return

    print(run_local_trending_draft(args.db, category=args.category))


if __name__ == "__main__":
    main()
