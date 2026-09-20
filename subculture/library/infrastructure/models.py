"""SQLAlchemy models for the local curation database only."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    payload: Mapped[str] = mapped_column(Text)
    deadline: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("items_deadline", "deadline"),)


class Term:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(Text, unique=True)


class Work(Term, Base):
    __tablename__ = "works"


class ProductCategory(Term, Base):
    __tablename__ = "product_categories"


class InformationType(Term, Base):
    __tablename__ = "information_types"


class Tag(Term, Base):
    __tablename__ = "tags"


class WorkAlias(Base):
    __tablename__ = "work_aliases"
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(Text, primary_key=True)


class ItemWork(Base):
    __tablename__ = "item_works"
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), primary_key=True)
    __table_args__ = (Index("by_works", "term_id", "item_id"),)


class ItemProductCategory(Base):
    __tablename__ = "item_product_categories"
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("product_categories.id", ondelete="CASCADE"), primary_key=True)
    __table_args__ = (Index("by_product_categories", "term_id", "item_id"),)


class ItemInformationType(Base):
    __tablename__ = "item_information_types"
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("information_types.id", ondelete="CASCADE"), primary_key=True)
    __table_args__ = (Index("by_information_types", "term_id", "item_id"),)


class ItemTag(Base):
    __tablename__ = "item_tags"
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    __table_args__ = (Index("by_tags", "term_id", "item_id"),)


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, server_default=text("''"))


class CollectionItem(Base):
    __tablename__ = "collection_items"
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    note: Mapped[str] = mapped_column(Text, server_default=text("''"))


class SavedFilter(Base):
    __tablename__ = "saved_filters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    filters: Mapped[str] = mapped_column(Text)


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    angle: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    reply_body: Mapped[str] = mapped_column(Text, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'DRAFT'"))
    posted_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("drafts_by_status", "status", "created_at"),)


class DraftItem(Base):
    """A draft's source. item_id has no foreign key so removing an item never breaks a draft."""
    __tablename__ = "draft_items"
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    __table_args__ = (Index("draft_items_by_item", "item_id"),)


class SyncState(Base):
    __tablename__ = "sync_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    completed_at: Mapped[str] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("id=1"),)


TERM_MODELS = {"works": Work, "product_categories": ProductCategory,
               "information_types": InformationType, "tags": Tag}
LINK_MODELS = {"works": ItemWork, "product_categories": ItemProductCategory,
               "information_types": ItemInformationType, "tags": ItemTag}
