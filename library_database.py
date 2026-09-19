"""Engine setup and explicit, backed-up local schema upgrades."""

import sqlite3
import os
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine, event, inspect
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv


DEFAULT_PATH = Path(__file__).parent / ".local" / "library.sqlite3"


class SchemaError(RuntimeError):
    pass


def database_target(target=None):
    if target is not None:
        return target
    load_dotenv()
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise SchemaError(".env에 POSTGRES_PASSWORD를 설정하고 Docker DB를 시작해주세요.")
    return URL.create("postgresql+psycopg", username=os.environ.get("POSTGRES_USER", "subculture"),
                      password=password, host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
                      port=int(os.environ.get("POSTGRES_PORT", "55432")),
                      database=os.environ.get("POSTGRES_DB", "subculture"))


def config(dialect="sqlite"):
    cfg = Config(str(Path(__file__).parent / "alembic.ini"))
    if dialect == "postgresql":
        cfg.set_main_option("script_location", str(Path(__file__).parent / "postgres_migrations"))
    return cfg


def make_engine(path=None, *, foreign_keys=True):
    path = database_target(path)
    if isinstance(path, URL) or (isinstance(path, str) and "://" in path):
        engine = create_engine(path, poolclass=NullPool)
        if engine.dialect.name != "postgresql":
            engine.dispose()
            raise ValueError("PostgreSQL URL 또는 레거시 SQLite 파일 경로를 사용해주세요.")
        return engine
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite", database=str(path)),
                           poolclass=NullPool, connect_args={"timeout": 30})

    @event.listens_for(engine, "connect")
    def configure(dbapi, _):
        dbapi.isolation_level = None
        dbapi.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")

    @event.listens_for(engine, "begin")
    def begin(connection):
        # Explicit BEGIN includes DDL in the same transaction on all supported Python versions.
        connection.exec_driver_sql("BEGIN")

    return engine


def head(dialect="sqlite"):
    return ScriptDirectory.from_config(config(dialect)).get_current_head()


def ensure_schema(engine):
    with engine.connect() as connection:
        dialect = engine.dialect.name
        tables = inspect(connection).get_table_names()
        version = connection.exec_driver_sql("PRAGMA user_version").scalar() if dialect == "sqlite" else None
        new_database = dialect == "sqlite" and not tables and version == 0
        current = MigrationContext.configure(connection).get_current_heads()
        if not new_database and current != (head(dialect),):
            raise SchemaError("DB 업그레이드가 필요합니다. 앱을 종료하고 docker compose run --rm tools python migrate_library.py upgrade를 실행해주세요.")
    if new_database:
        upgrade_database(engine.url.database)


def upgrade_database(path=None):
    """Caller stops the app; back up before any mutation, including legacy adoption."""
    path = database_target(path)
    if isinstance(path, URL) or (isinstance(path, str) and "://" in path):
        return upgrade_postgres(path)
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # SQLite batch migrations rebuild tables; disable FK actions while rebuilding
    # and check all constraints before commit. Runtime sessions always enable FKs.
    engine = make_engine(path, foreign_keys=False)
    backup = None
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
            if MigrationContext.configure(connection).get_current_heads() == (head(),):
                return None
        if tables:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(f"{path.name}.{stamp}.bak")
            with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target)
        with engine.begin() as connection:
            cfg = config()
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
            if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
                raise SchemaError("외래 키 검증에 실패했습니다. 변경을 취소합니다.")
        return backup
    finally:
        engine.dispose()


def upgrade_postgres(target):
    engine = make_engine(target)
    backup = None
    try:
        with engine.begin() as connection:
            # Prevent two upgrade commands from running together.
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(73291024)")
            if MigrationContext.configure(connection).get_current_heads() == (head("postgresql"),):
                return None
            tables = inspect(connection).get_table_names()
            if tables:
                backup_dir = Path(__file__).parent / ".local" / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup = backup_dir / f"library-{stamp}.dump"
                url = engine.url
                env = {**os.environ, "PGHOST": url.host or "127.0.0.1", "PGPORT": str(url.port or 5432),
                       "PGUSER": url.username or "", "PGPASSWORD": url.password or "", "PGDATABASE": url.database or ""}
                subprocess.run(["pg_dump", "--format=custom", "--file", str(backup)], env=env, check=True)
            cfg = config("postgresql")
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
        return backup
    finally:
        engine.dispose()
