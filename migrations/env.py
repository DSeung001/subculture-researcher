from alembic import context

from library_models import Base
from library_database import DEFAULT_PATH, make_engine


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata,
                      render_as_batch=True, compare_type=True, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()
        if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise RuntimeError("마이그레이션 후 외래 키 검증에 실패했습니다.")


if context.is_offline_mode():
    raise RuntimeError("SQLite 마이그레이션은 DB에 연결하여 실행해주세요.")
connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    path = context.get_x_argument(as_dictionary=True).get("db", DEFAULT_PATH)
    engine = make_engine(path, foreign_keys=False)
    try:
        with engine.begin() as connection:
            run(connection)
    finally:
        engine.dispose()
