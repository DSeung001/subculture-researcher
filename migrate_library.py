"""Explicit local schema upgrade with a SQLite backup before changes."""

import argparse
from pathlib import Path

from alembic.runtime.migration import MigrationContext

from library_database import DEFAULT_PATH, head, make_engine, upgrade_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upgrade", "current"))
    parser.add_argument("--db", help="Override database URL or legacy SQLite path")
    args = parser.parse_args()
    if args.action == "current" and args.db and "://" not in args.db and not Path(args.db).is_file():
        print(f"DB 없음: {args.db} / 최신: {head()}")
        return
    if args.action == "upgrade":
        backup = upgrade_database(args.db)
        if backup:
            print(f"백업: {backup}")
    engine = make_engine(args.db)
    try:
        with engine.connect() as connection:
            revisions = MigrationContext.configure(connection).get_current_heads()
            print(f"현재: {', '.join(revisions) or '미등록'} / 최신: {head(engine.dialect.name)}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
