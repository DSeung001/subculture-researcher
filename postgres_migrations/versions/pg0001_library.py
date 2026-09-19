"""PostgreSQL baseline for the IP-centric curation library."""

from alembic import op
from sqlalchemy import MetaData

from migrations.schema_v2 import Base


revision = "pg0001_library"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Frozen historical definitions; never import changing application models.
    metadata = MetaData()
    for original in Base.metadata.sorted_tables:
        table = original.to_metadata(metadata)
        for column in table.primary_key:
            column.nullable = False
    metadata.create_all(op.get_bind(), checkfirst=False)
    for table, names in {
        "product_categories": ("피규어", "아크릴 굿즈", "봉제인형", "기타 굿즈"),
        "information_types": ("예약상품", "신상품", "재입고", "이벤트"),
    }.items():
        op.bulk_insert(metadata.tables[table], [{"name": name, "normalized": name} for name in names])


def downgrade():
    raise RuntimeError("기획 DB 삭제는 지원하지 않습니다. 백업으로 복원해주세요.")
