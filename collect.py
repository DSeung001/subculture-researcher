import argparse
import json

from collectors.html_links import collect_html_links
from collectors.rss import collect_rss
from content_store import ContentStore
from firebase_client import get_db
from sources_config import community_source_names, load_sources


COLLECTORS = {"rss": collect_rss, "html": collect_html_links}
COUNTS = ("processed", "inserted", "existing", "updated", "failed")


def main(argv=None):
    parser = argparse.ArgumentParser(description="뉴스 메타데이터 수집 및 URL 중복 점검")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Firestore에 연결하지 않고 수집 결과 출력")
    mode.add_argument("--check-duplicates", action="store_true", help="기존 Firestore URL 중복을 읽기 전용으로 점검")
    mode.add_argument(
        "--purge-community", action="store_true",
        help="sourceTier가 COMMUNITY인 기존 Firestore 문서를 조회(기본) 또는 삭제(--yes)",
    )
    parser.add_argument("--source", action="append", help="수집할 소스 이름 (여러 번 지정 가능)")
    parser.add_argument(
        "--yes", action="store_true",
        help="--purge-community와 함께 사용 시 실제로 삭제를 실행 (기본은 드라이런)",
    )
    args = parser.parse_args(argv)

    if args.check_duplicates:
        store = ContentStore(get_db())
        print(json.dumps({"duplicates": store.duplicates(), "invalidUrlDocumentIds": store.invalid_urls}, ensure_ascii=False, indent=2))
        return

    if args.purge_community:
        db = get_db()
        names = sorted(community_source_names())
        by_id = {}
        # sourceTier catches items written after that field existed; source
        # name also catches legacy docs collected before it did (sourceTier
        # missing entirely on those).
        for snapshot in db.collection("contents").where("sourceTier", "==", "COMMUNITY").stream():
            by_id[snapshot.id] = snapshot
        if names:
            for snapshot in db.collection("contents").where("source", "in", names).stream():
                by_id[snapshot.id] = snapshot
        docs = list(by_id.values())
        print(f"[커뮤니티 문서] {len(docs)}건 발견 (대상 소스: {', '.join(names) or '없음'})")
        for snapshot in docs:
            data = snapshot.to_dict() or {}
            print(f"  - {snapshot.id}: {data.get('source')} | {data.get('title')} | {data.get('url')}")
        if not docs:
            return
        if not args.yes:
            print("[드라이런] 실제 삭제하려면 --yes를 함께 지정하세요. 아직 아무것도 삭제하지 않았습니다.")
            return
        batch_size = 400
        for start in range(0, len(docs), batch_size):
            batch = db.batch()
            for snapshot in docs[start:start + batch_size]:
                batch.delete(snapshot.reference)
            batch.commit()
        print(f"[삭제 완료] {len(docs)}건 삭제했습니다.")
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
    for source in sources:
        if not source.get("enabled", True):
            print(f"[건너뜀] 비활성화: {source.get('name')}")
            continue
        collector = COLLECTORS.get(source.get("type"))
        if not collector:
            total["failed"] += 1
            print(f"[건너뜀] 지원하지 않는 수집 방식: {source.get('type')} ({source.get('name')})")
            continue
        try:
            result = collector(db, source, store=store)
            for key in COUNTS:
                total[key] += result.get(key, 0)
            if result.get("skipped"):
                print(f"[건너뜀] {source['name']}: {result.get('reason', '')}")
            print(
                f"[결과] {source['name']}: 확인={result['processed']} 신규={result['inserted']} "
                f"기존={result['existing']} 수치 갱신={result['updated']} 실패={result['failed']}"
            )
        except Exception as exc:
            total["failed"] += 1
            print(f"[오류] {source.get('name')}: {exc}")
    if args.dry_run:
        print("[저장 없는 검증] 위 신규/기존/갱신은 이번 실행 내 모의 결과이며 실제 DB와 비교하지 않습니다.")
        print(json.dumps(store.preview, ensure_ascii=False, indent=2, default=str))
    print("수집 종료: " + " ".join(f"{key}={value}" for key, value in total.items()))


if __name__ == "__main__":
    main()
