"""Upsert works from work_catalog.yaml and auto-link items by keyword."""

import argparse
from pathlib import Path

import yaml

from subculture.library.infrastructure.local_library import Library

CATALOG = Path(__file__).resolve().parents[1] / "work_catalog.yaml"


def load_catalog(path=CATALOG):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    works = data.get("works") or []
    if not isinstance(works, list):
        raise ValueError("work_catalog.yaml의 works는 목록이어야 합니다.")
    return works


def seed(library: Library, catalog_path=CATALOG, assign=True):
    created = 0
    for entry in load_catalog(catalog_path):
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        aliases = entry.get("aliases") or []
        if isinstance(aliases, str):
            alias_text = aliases
        else:
            alias_text = "\n".join(str(a).strip() for a in aliases if str(a).strip())
        library.upsert_work(name, alias_text)
        created += 1
    linked = library.auto_assign_works() if assign else 0
    return created, linked


def print_unmatched(library: Library):
    report = library.unclassified_report()
    print(f"작품 링크가 없는 항목: {report['total']}건")
    for source, count in report["by_source"]:
        print(f"\n[{source}] {count}건")
        for title in report["samples"].get(source, []):
            print(f"  - {title}")
    print("\n자주 나오는 괄호 표기 (작품명·시리즈 후보):")
    for token, count in report["bracket_tokens"]:
        print(f"  {count:>4}  {token}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Override database URL or legacy SQLite path")
    parser.add_argument("--catalog", default=str(CATALOG), help="YAML catalog path")
    parser.add_argument("--no-assign", action="store_true", help="Skip keyword auto-link")
    parser.add_argument(
        "--unmatched", action="store_true",
        help="작품 링크가 없는 항목을 소스별로 요약해 출력만 함 (카탈로그 보강용, 변경 없음)",
    )
    args = parser.parse_args()
    if args.unmatched:
        print_unmatched(Library(args.db))
        return
    count, linked = seed(Library(args.db), args.catalog, assign=not args.no_assign)
    print(f"작품 {count}개 반영, 새로 연결한 링크 {linked}개")


if __name__ == "__main__":
    main()
