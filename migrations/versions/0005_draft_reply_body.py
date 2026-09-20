"""Drafts get a second post: the reply that carries the purchase links."""

import sqlalchemy as sa
from alembic import op

revision = "0005_draft_reply_body"
down_revision = "0004_drafts"
branch_labels = None
depends_on = None


def upgrade():
    # Existing drafts keep their body untouched and get an empty reply.
    with op.batch_alter_table("drafts") as batch:
        batch.add_column(sa.Column("reply_body", sa.Text(), server_default=sa.text("''"), nullable=False))


def downgrade():
    raise RuntimeError("댓글 본문 삭제는 지원하지 않습니다. 백업으로 복원해주세요.")
