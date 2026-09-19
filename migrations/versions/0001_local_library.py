"""Baseline local curation schema; validate and adopt the original v1 database.

The SQL snapshot is intentionally independent of current ORM models.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from alembic import op


revision = "0001_local_library"
down_revision = None
branch_labels = None
depends_on = None


def signature(connection):
    names = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name")]
    result = {}
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        columns = list(connection.execute(f"PRAGMA table_info({quoted})"))
        foreign_keys = sorted(connection.execute(f"PRAGMA foreign_key_list({quoted})"))
        indexes = sorted((row[2], tuple(c[2] for c in connection.execute(
            'PRAGMA index_info("' + row[1].replace('"', '""') + '")')))
            for row in connection.execute(f"PRAGMA index_list({quoted})"))
        result[name] = (columns, foreign_keys, indexes)
    return result


def upgrade():
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    sql = Path(__file__).with_name("0001_schema.sql").read_text(encoding="utf-8")
    current = signature(raw)
    version = bind.exec_driver_sql("PRAGMA user_version").scalar()
    if current:
        with closing(sqlite3.connect(":memory:")) as expected:
            expected.executescript(sql)
            if version != 1 or current != signature(expected):
                raise RuntimeError("기존 SQLite 구조가 v1과 다릅니다. 자동 전환하지 않습니다.")
        if bind.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise RuntimeError("기존 SQLite 외래 키가 손상되어 전환할 수 없습니다.")
    else:
        if version != 0:
            raise RuntimeError("알 수 없는 SQLite 버전입니다.")
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement and statement not in ("BEGIN TRANSACTION", "COMMIT") and not statement.startswith("PRAGMA"):
                bind.exec_driver_sql(statement)
        for table, names in {
            "product_categories": ("피규어", "아크릴 굿즈", "봉제인형", "기타 굿즈"),
            "information_types": ("예약상품", "신상품", "재입고", "이벤트"),
        }.items():
            for name in names:
                bind.exec_driver_sql(f"INSERT INTO {table}(name, normalized) VALUES (?, ?)", (name, name))
    bind.exec_driver_sql("PRAGMA user_version=1")


def downgrade():
    raise RuntimeError("초기 스키마 삭제는 지원하지 않습니다. 앱 종료 후 업그레이드 전 백업을 복원해주세요.")
