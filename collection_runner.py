"""Shared collection loop used by automatic and manual entry points."""

from __future__ import annotations

import json
import random
import time

from collectors.anilist import collect_anilist
from collectors.figurefarm import collect_figurefarm
from collectors.html_links import collect_html_links
from collectors.json_api import collect_json_api
from collectors.local_browser import collect_local_browser
from collectors.rss import collect_rss
from collectors.youtube_feed import collect_youtube_feed
from content_store import ContentStore
from sources_config import is_manual_source


COLLECTORS = {
    "rss": collect_rss,
    "html": collect_html_links,
    "json_api": collect_json_api,
    "local_browser": collect_local_browser,
    "anilist": collect_anilist,
    "figurefarm": collect_figurefarm,
    "youtube_feed": collect_youtube_feed,
}
COUNTS = ("processed", "inserted", "existing", "updated", "failed")
TABLE_HEADERS = ("소스", "처리", "신규", "기존", "갱신", "실패", "실패 사유")
MANUAL_ENTRY = "collect_manual.py"


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


def run_collection(
    sources: list[dict],
    *,
    db,
    dry_run: bool = False,
    allow_manual: bool = False,
    inter_source_delay: tuple[float, float] | None = None,
    show_progress: bool = False,
    force_refresh: bool = False,
) -> dict:
    store = ContentStore(db)
    duplicates = store.duplicates()
    if duplicates or store.invalid_urls:
        print(
            f"[점검] 기존 중복 URL={len(duplicates)} 잘못된 URL={len(store.invalid_urls)}. "
            "--check-duplicates로 확인하세요. 기존 문서는 삭제하지 않습니다."
        )

    total = dict.fromkeys(COUNTS, 0)
    table_rows = []
    ran_any = False

    for position, source in enumerate(sources, start=1):
        name = source.get("name")
        if show_progress:
            print(f"[{position}/{len(sources)}] {name}")

        if not source.get("enabled", True):
            print(f"[건너뜀] 비활성화: {name}")
            table_rows.append((name, 0, 0, 0, 0, 0, "비활성화"))
            continue

        if is_manual_source(source) and not allow_manual:
            reason = f"수동 전용 ({MANUAL_ENTRY})"
            print(f"[건너뜀] {name}: {reason}")
            table_rows.append((name, 0, 0, 0, 0, 0, reason))
            continue

        collector = COLLECTORS.get(source.get("type"))
        if not collector:
            total["failed"] += 1
            reason = f"지원하지 않는 수집 방식: {source.get('type')}"
            print(f"[건너뜀] {reason} ({name})")
            table_rows.append((name, 0, 0, 0, 0, 1, reason))
            continue

        if ran_any and inter_source_delay and not dry_run:
            lo, hi = inter_source_delay
            wait = random.uniform(lo, hi)
            print(f"[대기] 다음 소스까지 {wait:.1f}초")
            time.sleep(wait)

        try:
            if force_refresh:
                source = {**source, "force_refresh": True}  # collectors that cache results skip the cache
            result = collector(db, source, store=store)
            ran_any = True
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
            ran_any = True
            total["failed"] += 1
            print(f"[오류] {name}: {exc}")
            table_rows.append((name, 0, 0, 0, 0, 1, str(exc)))

    if dry_run:
        print("[저장 없는 검증] 위 신규/기존/갱신은 이번 실행 내 모의 결과이며 실제 DB와 비교하지 않습니다.")
        print(json.dumps(store.preview, ensure_ascii=False, indent=2, default=str))

    print("수집 종료: " + " ".join(f"{key}={value}" for key, value in total.items()))
    print()
    print(render_table(table_rows))
    return {"total": total, "rows": table_rows, "store": store}
