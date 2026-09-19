"""Align legacy SQLite primary-key nullability with the PostgreSQL models."""
from alembic import op
import sqlalchemy as sa

revision = "0003_required_primary_keys"
down_revision = "0002_normalize_definitions"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("items", "works", "product_categories", "information_types", "tags", "collections", "saved_filters", "sync_state"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("id", nullable=False, existing_type=sa.Text() if table == "items" else sa.Integer())


def downgrade():
    for table in ("items", "works", "product_categories", "information_types", "tags", "collections", "saved_filters", "sync_state"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("id", nullable=True, existing_type=sa.Text() if table == "items" else sa.Integer())
