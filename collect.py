from pathlib import Path

import yaml

from collectors.rss import collect_rss
from firebase_client import get_db


CONFIG_PATH = Path("sources.yaml")


def main():
    if not CONFIG_PATH.exists():
        raise SystemExit("sources.yaml not found")

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    sources = config.get("sources", [])

    db = get_db()

    total_processed = 0
    total_inserted = 0

    for source in sources:
        if not source.get("enabled", True):
            continue

        if source.get("type") != "rss":
            print(f"[skip] unsupported source type: {source.get('type')} ({source.get('name')})")
            continue

        try:
            result = collect_rss(db, source)
            total_processed += result["processed"]
            total_inserted += result["inserted"]
            print(
                f"[ok] {source['name']}: "
                f"processed={result['processed']} inserted={result['inserted']}"
            )
        except Exception as exc:
            print(f"[error] {source.get('name')}: {exc}")

    print(f"done: processed={total_processed} inserted={total_inserted}")


if __name__ == "__main__":
    main()
