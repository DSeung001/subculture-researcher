"""Firestore → local library sync, as reported after (and before) a collection run."""

from datetime import datetime


def _short(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return (lines[0] if lines else type(exc).__name__)[:160]


def report_local_sync(store, db_path=None) -> None:
    """Print how far the local library is behind, using ids the collection run already read.

    Best effort: a stopped local database or any other failure never stops collection.
    """
    try:
        from subculture.library.infrastructure.local_library import Library
        status = Library(db_path, connect_timeout=5).sync_status(store.item_ids())
    except Exception as exc:
        print(f"[로컬 동기화] 확인 건너뜀: {_short(exc)}")
        return
    last = status["last_sync"]
    when = datetime.fromisoformat(last).astimezone().strftime("%m-%d %H:%M") if last else "기록 없음"
    print(
        f"[로컬 동기화] 마지막 {when} · 로컬 {status['local_count']} · 클라우드 {status['cloud_count']} · "
        f"미동기화 {status['unsynced']} · 로컬에만 {status['orphans']}"
    )
    if status["unsynced"]:
        print("  → 수집이 끝나면 기본으로 동기화합니다. 끄려면 --no-sync, 또는 python sync_library.py")
    if status["orphans"] > status["curated_orphans"]:
        print("  → 원격에서 사라진 로컬 항목 정리: python prune_library.py --dry-run")


def sync_local(db, db_path=None) -> bool:
    """Firestore → local sync after collection. A failure is reported, never raised."""
    try:
        from subculture.library.infrastructure.local_library import Library
        count = Library(db_path).sync(db)
    except Exception as exc:
        print(f"[로컬 동기화] 실패(수집 결과에는 영향 없음): {_short(exc)}")
        return False
    print(f"[로컬 동기화] {count}개 항목 동기화 완료")
    return True
