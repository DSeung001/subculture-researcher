"""Create one AI-written draft from unposted inbox items (no collection)."""

import argparse

from dotenv import load_dotenv

from ai_drafts import run_trending_draft
from firebase_client import get_db

load_dotenv()

CATEGORIES = ("ANIME", "CHARACTER", "FIGURE", "GOODS", "COLLECTION", "FESTIVAL", "UNKNOWN")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="미게시 인박스 항목으로 AI 임시글 초안 하나 만들기 (수집 없음)",
    )
    parser.add_argument(
        "--category",
        choices=CATEGORIES,
        help="이 카테고리의 미게시 항목만 후보로 사용",
    )
    args = parser.parse_args(argv)
    print(run_trending_draft(get_db(), category=args.category))


if __name__ == "__main__":
    main()
