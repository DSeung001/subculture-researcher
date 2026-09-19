"""Manual collection entry point (YouTube RSS + local browser sources)."""

import argparse

from dotenv import load_dotenv

from ai_drafts import run_trending_draft
from collection_runner import run_collection
from firebase_client import get_db
from sources_config import is_manual_source, load_sources, manual_sources

load_dotenv()

INTER_SOURCE_DELAY = (3.0, 8.0)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="수동 수집 (YouTube·로컬 브라우저). 준비는 랜덤 대기 후 자동 진행"
    )
    parser.add_argument("--dry-run", action="store_true", help="Firestore에 연결하지 않고 수집 결과 출력")
    parser.add_argument("--source", action="append", help="수집할 수동 소스 이름 (여러 번 지정 가능)")
    parser.add_argument(
        "--ai-draft",
        action="store_true",
        help="수집 후 AI 초안 생성(Gemini 호출). 기본은 끔",
    )
    args = parser.parse_args(argv)

    all_sources = load_sources()
    by_name = {source.get("name"): source for source in all_sources}
    if args.source:
        missing = set(args.source) - set(by_name)
        if missing:
            parser.error(f"알 수 없는 소스: {', '.join(sorted(missing))}")
        automatic = [name for name in args.source if not is_manual_source(by_name[name])]
        if automatic:
            parser.error(
                f"자동 소스입니다. collect.py를 사용하세요: {', '.join(automatic)}"
            )
        sources = [by_name[name] for name in args.source]
    else:
        sources = manual_sources(all_sources)

    db = None if args.dry_run else get_db()
    run_collection(
        sources,
        db=db,
        dry_run=args.dry_run,
        allow_manual=True,
        inter_source_delay=None if args.dry_run else INTER_SOURCE_DELAY,
        show_progress=True,
    )

    if db is not None and args.ai_draft:
        print(run_trending_draft(db))


if __name__ == "__main__":
    main()
