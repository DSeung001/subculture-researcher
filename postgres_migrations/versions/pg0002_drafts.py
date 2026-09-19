"""Local drafts: temporary posts move from Firestore into the local library."""

import sqlalchemy as sa
from alembic import op

revision = "pg0002_drafts"
down_revision = "pg0001_library"
branch_labels = None
depends_on = None


def upgrade():
    # Frozen definitions; existing tables and rows are not touched.
    op.create_table(
        "drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("posted_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("drafts_by_status", "drafts", ["status", "created_at"])
    op.create_table(
        "draft_items",
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("draft_id", "item_id"),
    )
    op.create_index("draft_items_by_item", "draft_items", ["item_id"])


def downgrade():
    raise RuntimeError("임시글 삭제는 지원하지 않습니다. 백업으로 복원해주세요.")
