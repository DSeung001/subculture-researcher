"""Automatic collection entry point (CI / scheduled). Manual sources are skipped."""

import argparse
import json

from dotenv import load_dotenv

from subculture.collection.application.collection_runner import MANUAL_ENTRY, run_collection
from subculture.collection.infrastructure.content_store import ContentStore
from subculture.shared.firebase_client import get_db
from subculture.collection.application.image_backfill import backfill_images
from subculture.collection.infrastructure.sources_config import automatic_sources, is_manual_source, load_sources
from subculture.collection.application.translation_backfill import backfill_translations

load_dotenv()

# Space sources out so a full automatic run is not one burst of hosts.
INTER_SOURCE_DELAY = (5.0, 12.0)


def main(argv=None):
    parser = argparse.ArgumentParser(description="자동 수집 (수동 소스 제외)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Firestore에 연결하지 않고 수집 결과 출력")
    mode.add_argument("--check-duplicates", action="store_true", help="기존 Firestore URL 중복을 읽기 전용으로 점검")
    mode.add_argument(
        "--backfill-translations", action="store_true",
        help="titleKo가 없는 외국어 기존 문서만 MyMemory로 번역해 보완",
    )
    mode.add_argument(
        "--backfill-images", action="store_true",
        help="imageUrl이 없는 기존 문서만 상세 대표 이미지로 보완 (기존 이미지는 덮어쓰지 않음)",
    )
    parser.add_argument("--source", action="append", help="수집할 자동 소스 이름 (여러 번 지정 가능)")
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="결과를 캐시하는 수집기의 캐시를 무시하고 다시 수집 (현재 캐시하는 수집기 없음)",
    )
    args = parser.parse_args(argv)

    if args.check_duplicates:
        store = ContentStore(get_db())
        print(json.dumps(
            {"duplicates": store.duplicates(), "invalidUrlDocumentIds": store.invalid_urls},
            ensure_ascii=False,
            indent=2,
        ))
        return

    if args.backfill_translations:
        backfill_translations(get_db())
        return

    if args.backfill_images:
        backfill_images(get_db(), load_sources())
        return

    all_sources = load_sources()
    by_name = {source.get("name"): source for source in all_sources}
    if args.source:
        missing = set(args.source) - set(by_name)
        if missing:
            parser.error(f"알 수 없는 소스: {', '.join(sorted(missing))}")
        manual = [name for name in args.source if is_manual_source(by_name[name])]
        if manual:
            parser.error(
                f"수동 소스입니다. {MANUAL_ENTRY}를 사용하세요: {', '.join(manual)}"
            )
        sources = [by_name[name] for name in args.source]
    else:
        sources = automatic_sources(all_sources)

    db = None if args.dry_run else get_db()
    run_collection(
        sources,
        db=db,
        dry_run=args.dry_run,
        allow_manual=False,
        inter_source_delay=None if args.dry_run else INTER_SOURCE_DELAY,
        show_progress=True,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    main()
