import argparse
import json

from collectors.html_links import collect_html_links
from collectors.json_api import collect_json_api
from collectors.rss import collect_rss
from content_store import ContentStore
from firebase_client import get_db
from sources_config import load_sources
from translate import enrich_translation, needs_translation


COLLECTORS = {\n    "rss": collect_rss,\n    "html": collect_html_links,\n    "json_api": collect_json_api,\n    "anilist": collect_anilist,\n    "youtube_feed": collect_youtube_feed,\n}
COUNTS = ("processed", "inserted", "existing", "updated", "failed")
TABLE_HEADERS = ("소스", "처리", "신규", "기존", "갱신", "실패", "실패 사유")


def summarize_errors(reason: str, errors: list[str], limit: int = 2) -> str:
    if reason:
        return reason
    if not errors:
        return "-"
    shown = errors[:limit]
    more = len(errors) - len(shown)
    text = "; ".join(shown)
    return f"{text} 외 {more}건" if more else text


def render_table(rows: list[tuple]) -> str:
    widths = [
        max(len(str(row[i])) for row in (TABLE_HEADERS, *rows))
        for i in range(len(TABLE_HEADERS))
    ]
    def format_row(row):
        return " | ".join(str(cell).ljust(width) for cell, width in zip(row, widths))
    separator = "-+-".join("-" * width for width in widths)
    lines = [format_row(TABLE_HEADERS), separator]
    lines.extend(format_row(row) for row in rows)
    return "\n".join(lines)


def backfill_translations(db) -> None:
    processed = updated = skipped = failed = 0
    for snapshot in db.collection("contents").stream():
        processed += 1
        data = snapshot.to_dict() or {}
        if (data.get("titleKo") or "").strip():
            skipped += 1
            continue
        title = data.get("title") or ""
        summary = data.get("summary") or ""
        if not needs_translation(title) and not needs_translation(summary):
            skipped += 1
            continue
        fields = enrich_translation(data)
        if not (fields.get("titleKo") or fields.get("summaryKo")):
            failed += 1
            continue
        snapshot.reference.update(fields)
        updated += 1
        print(f"[번역] {title} -> {fields.get('titleKo') or fields.get('summaryKo')}")
    print(
        f"번역 보완 종료: processed={processed} updated={updated} "
        f"skipped={skipped} failed={failed}"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="뉴스 메타데이터 수집 및 URL 중복 점검")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Firestore에 연결하지 않고 수집 결과 출력")
    mode.add_argument("--check-duplicates", action="store_true", help="기존 Firestore URL 중복을 읽기 전용으로 점검")
    mode.add_argument(
        "--backfill-translations", action="store_true",
        help="titleKo가 없는 외국어 기존 문서만 MyMemory로 번역해 보완",
    )
    parser.add_argument("--source", action="append", help="수집할 소스 이름 (여러 번 지정 가능)")
    args = parser.parse_args(argv)

    if args.check_duplicates:
        store = ContentStore(get_db())
        print(json.dumps({"duplicates": store.duplicates(), "invalidUrlDocumentIds": store.invalid_urls}, ensure_ascii=False, indent=2))
        return

    if args.backfill_translations:
        backfill_translations(get_db())
        return

    sources = load_sources()
    if args.source:
        missing = set(args.source) - {source.get("name") for source in sources}
        if missing:
            parser.error(f"알 수 없는 소스: {', '.join(sorted(missing))}")
        sources = [source for source in sources if source.get("name") in args.source]
    db = None if args.dry_run else get_db()
    store = ContentStore(db)
    duplicates = store.duplicates()
    if duplicates or store.invalid_urls:
        print(f"[점검] 기존 중복 URL={len(duplicates)} 잘못된 URL={len(store.invalid_urls)}. --check-duplicates로 확인하세요. 기존 문서는 삭제하지 않습니다.")
    total = dict.fromkeys(COUNTS, 0)
    table_rows = []
    for source in sources:
        name = source.get("name")
        if not source.get("enabled", True):
            print(f"[건너뜀] 비활성화: {name}")
            table_rows.append((name, 0, 0, 0, 0, 0, "비활성화"))
            continue
        collector = COLLECTORS.get(source.get("type"))
        if not collector:
            total["failed"] += 1
            reason = f"지원하지 않는 수집 방식: {source.get('type')}"
            print(f"[건너뜀] {reason} ({name})")
            table_rows.append((name, 0, 0, 0, 0, 1, reason))
            continue
        try:
            result = collector(db, source, store=store)
            for key in COUNTS:
                total[key] += result.get(key, 0)
            if result.get("skipped"):
                print(f"[건너뜀] {name}: {result.get('reason', '')}")
            print(
                f"[결과] {name}: 확인={result['processed']} 신규={result['inserted']} "
                f"기존={result['existing']} 수치 갱신={result['updated']} 실패={result['failed']}"
            )
            note = summarize_errors(result.get("reason", ""), result.get("errors", []))
            table_rows.append((
                name, result["processed"], result["inserted"], result["existing"],
                result["updated"], result["failed"], note,
            ))
        except Exception as exc:
            total["failed"] += 1
            print(f"[오류] {name}: {exc}")
            table_rows.append((name, 0, 0, 0, 0, 1, str(exc)))
    if args.dry_run:
        print("[저장 없는 검증] 위 신규/기존/갱신은 이번 실행 내 모의 결과이며 실제 DB와 비교하지 않습니다.")
        print(json.dumps(store.preview, ensure_ascii=False, indent=2, default=str))
    print("수집 종료: " + " ".join(f"{key}={value}" for key, value in total.items()))
    print()
    print(render_table(table_rows))


if __name__ == "__main__":
    main()
