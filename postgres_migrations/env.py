from alembic import context

from library_database import make_engine
from library_models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata,
                      compare_type=True, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("DB에 연결하여 마이그레이션을 실행해주세요.")
connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    engine = make_engine()
    try:
        with engine.begin() as connection:
            run(connection)
    finally:
        engine.dispose()
