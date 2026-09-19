"""Normalize legacy inline constraints for reliable future autogeneration.

Rebuild using frozen definitions, keeping every column, primary key and row.
"""

from alembic import op

from migrations.schema_v2 import Base


revision = "0002_normalize_definitions"
down_revision = "0001_local_library"
branch_labels = None
depends_on = None


def upgrade():
    for table in Base.metadata.sorted_tables:
        with op.batch_alter_table(table.name, copy_from=table, recreate="always"):
            pass


def downgrade():
    # Logical schema is identical to 0001; only DDL formatting was normalized.
    pass
