from pathlib import Path

import yaml

from collectors.html_links import collect_html_links
from collectors.rss import collect_rss
from firebase_client import get_db


CONFIG_PATH = Path("sources.yaml")
COLLECTORS = {
    "rss": collect_rss,
    "html": collect_html_links,
}


def main():
    if not CONFIG_PATH.exists():
        raise SystemExit("sources.yaml 파일이 없습니다.")

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    sources = config.get("sources", [])
    db = get_db()

    total_processed = 0
    total_inserted = 0

    for source in sources:
        if not source.get("enabled", True):
            print(f"[건너뜀] 비활성화: {source.get('name')}")
            continue

        source_type = source.get("type")
        collector = COLLECTORS.get(source_type)

        if not collector:
            print(f"[건너뜀] 지원하지 않는 수집 방식: {source_type} ({source.get('name')})")
            continue

        try:
            result = collector(db, source)
            total_processed += result.get("processed", 0)
            total_inserted += result.get("inserted", 0)

            if result.get("skipped"):
                print(f"[건너뜀] {source['name']}: {result.get('reason', '')}")
                continue

            print(
                f"[완료] {source['name']}: "
                f"확인={result.get('processed', 0)} 신규={result.get('inserted', 0)}"
            )
        except Exception as exc:
            print(f"[오류] {source.get('name')}: {exc}")

    print(f"수집 종료: 확인={total_processed} 신규={total_inserted}")


if __name__ == "__main__":
    main()
