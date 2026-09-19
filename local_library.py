"""Local curation database. Imported source records never own editorial relations."""

import json
import re
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session

from library_database import DEFAULT_PATH, ensure_schema, make_engine
from library_models import (Collection, CollectionItem, Item, ItemWork, LINK_MODELS,
                            SavedFilter, SyncState, TERM_MODELS, Work, WorkAlias)

from content_model import content_id
from content_store import UNTITLED_TITLE, is_untitled_leftover


TAXONOMIES = {
    "works": "작품·IP",
    "product_categories": "제품 카테고리",
    "information_types": "정보 유형",
    "tags": "태그",
}
FILTER_KEYS = (*TAXONOMIES, "q", "unclassified", "deadline_from", "deadline_to")


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def clean_name(value):
    value = value.strip()
    if not value or len(value) > 200:
        raise ValueError("이름은 1~200자로 입력해주세요.")
    return value


def json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported source value: {type(value).__name__}")


def item_title_text(data):
    """Normalized title string used for work keyword matching."""
    return normalized(" ".join(str(data.get(k) or "") for k in ("title", "titleKo")))


BRACKET_TOKEN = re.compile(r"[【\[『「]([^】\]』」]{1,30})[】\]』」]")


def work_keywords(work):
    """Display keywords: canonical name plus aliases (comma- or newline-separated)."""
    aliases = work.get("aliases") or ""
    if isinstance(aliases, list):
        parts = aliases
    else:
        parts = re.split(r"[,\n]", aliases)
    names = []
    seen = set()
    for raw in [work.get("name") or "", *parts]:
        name = (raw or "").strip()
        if not name:
            continue
        key = normalized(name)
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def match_keyword(text, keyword):
    """Return the matched keyword if it appears in normalized title text, else None."""
    alias = normalized(keyword)
    # Short aliases are noisy; ASCII aliases must not sit inside another Latin word or number.
    # Hangul/kana next to them is fine: shop titles often glue the name to a product noun.
    if len(alias) < 2:
        return None
    pattern = re.escape(alias)
    if alias.isascii():
        pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
    if re.search(pattern, text):
        return keyword.strip()
    return None


class Library:
    def __init__(self, path=None):
        self.engine = make_engine(path)
        self.insert = postgres_insert if self.engine.dialect.name == "postgresql" else insert
        ensure_schema(self.engine)

    @contextmanager
    def connect(self):
        with Session(self.engine) as session, session.begin():
            yield session

    @staticmethod
    def table(table):
        if table not in TAXONOMIES:
            raise ValueError("잘못된 분류입니다.")
        return table

    def terms(self):
        with self.connect() as session:
            result = {table: [row_dict(row) for row in session.scalars(select(model).order_by(model.name))]
                      for table, model in TERM_MODELS.items()}
            aliases = {}
            for row in session.scalars(select(WorkAlias).order_by(WorkAlias.name)):
                aliases.setdefault(row.work_id, []).append(row.name)
            for work in result["works"]:
                work["aliases"] = ", ".join(aliases.get(work["id"], []))
            return result

    def save_term(self, table, name, term_id=None, aliases=""):
        model = TERM_MODELS[self.table(table)]
        name = clean_name(name)
        with self.connect() as session:
            term = session.get(model, term_id) if term_id else model()
            if term is None:
                raise ValueError("분류를 찾을 수 없습니다.")
            term.name, term.normalized = name, normalized(name)
            session.add(term)
            session.flush()
            if table == "works":
                names = [clean_name(s) for s in re.split(r"[,\n]", aliases) if s.strip()]
                session.execute(delete(WorkAlias).where(WorkAlias.work_id == term.id))
                for alias in names:
                    session.execute(self.insert(WorkAlias).values(work_id=term.id, name=alias,
                                    normalized=normalized(alias)).on_conflict_do_nothing())
            return term.id

    def delete_term(self, table, term_id):
        model = TERM_MODELS[self.table(table)]
        with self.connect() as session:
            session.execute(delete(model).where(model.id == term_id))

    def delete_items(self, item_ids):
        """Remove local items by id. Link/collection rows cascade."""
        ids = [item_id for item_id in item_ids if item_id]
        if not ids:
            return 0
        with self.connect() as session:
            result = session.execute(delete(Item).where(Item.id.in_(ids)))
            return result.rowcount or 0

    def untitled_x_items(self):
        """Local rows stored as untitled leftovers: X status posts and the laftel.net home."""
        with self.connect() as session:
            rows = session.scalars(select(Item)).all()
            matched = []
            for row in rows:
                title = row.title or ""
                if title != UNTITLED_TITLE:
                    try:
                        payload = json.loads(row.payload or "{}")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        payload = {}
                    title = payload.get("title") or title
                if is_untitled_leftover(row.url or "", title):
                    matched.append({"id": row.id, "url": row.url or "", "title": title})
            return matched

    def delete_untitled_x(self, *, dry_run: bool = False) -> dict:
        matched = self.untitled_x_items()
        if not dry_run:
            self.delete_items([item["id"] for item in matched])
        return {
            "deleted": 0 if dry_run else len(matched),
            "matched": len(matched),
            "dry_run": dry_run,
            "items": matched,
        }

    def sync(self, cloud):
        # Read outside the local transaction. A failed remote stream leaves the
        # previous snapshot and every local relation intact. No cloud writes.
        records = []
        now = datetime.now(timezone.utc).isoformat()
        for snapshot in cloud.collection_group("contents").stream():
            data = snapshot.to_dict() or {}
            deadline = data.get("preorderEndAt")
            if isinstance(deadline, (date, datetime)):
                deadline = deadline.isoformat()[:10]
            try:
                deadline = date.fromisoformat(deadline).isoformat() if deadline else None
            except (ValueError, TypeError):
                deadline = None
            records.append(dict(id=content_id(snapshot),
                                title=data.get("titleKo") or data.get("title") or "(제목 없음)",
                                url=data.get("url") or "", source=data.get("source") or "",
                                payload=json.dumps(data, ensure_ascii=False, default=json_default),
                                deadline=deadline, synced_at=now))
        with self.connect() as session:
            statement = self.insert(Item)
            statement = statement.on_conflict_do_update(
                index_elements=[Item.id],
                set_={key: getattr(statement.excluded, key) for key in
                      ("title", "url", "source", "payload", "deadline", "synced_at")})
            if records:
                session.execute(statement, records)
            session.merge(SyncState(id=1, completed_at=now, item_count=len(records)))
        # New source rows only: additive keyword links for still-unlinked items.
        self.auto_assign_works(unclassified_only=True)
        return len(records)

    def upsert_work(self, name, aliases=""):
        """Create a work or merge extra aliases into the existing normalized name."""
        name = clean_name(name)
        names = [clean_name(s) for s in re.split(r"[,\n]", aliases) if s.strip()]
        with self.connect() as session:
            term = session.scalar(select(Work).where(Work.normalized == normalized(name)))
            if term is None:
                term = Work(name=name, normalized=normalized(name))
                session.add(term)
                session.flush()
            existing = set(session.scalars(
                select(WorkAlias.normalized).where(WorkAlias.work_id == term.id)))
            existing.add(term.normalized)
            for alias in names:
                key = normalized(alias)
                if key in existing:
                    continue
                session.execute(self.insert(WorkAlias).values(
                    work_id=term.id, name=alias, normalized=key).on_conflict_do_nothing())
                existing.add(key)
            return term.id

    def work(self, work_id):
        with self.connect() as session:
            term = session.get(Work, work_id)
            if term is None:
                raise ValueError("작품을 찾을 수 없습니다.")
            aliases = [row.name for row in session.scalars(
                select(WorkAlias).where(WorkAlias.work_id == work_id).order_by(WorkAlias.name))]
            linked = session.scalar(select(func.count()).select_from(ItemWork).where(
                ItemWork.term_id == work_id)) or 0
            return {"id": term.id, "name": term.name, "aliases": aliases, "linked_count": linked}

    def auto_assign_works(self, work_id=None, unclassified_only=False):
        """Add item_works links when title keywords match. Never removes links.

        Returns the number of new (item, work) pairs inserted.
        """
        works = self.terms()["works"]
        if work_id is not None:
            works = [w for w in works if w["id"] == work_id]
            if not works:
                raise ValueError("작품을 찾을 수 없습니다.")
        compiled = []
        for work in works:
            keywords = work_keywords(work)
            if keywords:
                compiled.append((work["id"], keywords))
        if not compiled:
            return 0
        with self.connect() as session:
            query = select(Item.id, Item.payload)
            if unclassified_only:
                query = query.where(~exists().where(ItemWork.item_id == Item.id))
            if work_id is not None:
                # Still scan all items; on_conflict skips already-linked pairs.
                pass
            rows = session.execute(query).all()
            pairs = []
            for item_id, payload in rows:
                text = item_title_text(json.loads(payload))
                for wid, keywords in compiled:
                    for keyword in keywords:
                        if match_keyword(text, keyword):
                            pairs.append({"item_id": item_id, "term_id": wid})
                            break
            if not pairs:
                return 0
            before = session.scalar(select(func.count()).select_from(ItemWork)) or 0
            session.execute(self.insert(ItemWork).on_conflict_do_nothing(), pairs)
            after = session.scalar(select(func.count()).select_from(ItemWork)) or 0
            return after - before

    def assign(self, item_ids, table, term_id, remove=False):
        table = self.table(table)
        model, link = TERM_MODELS[table], LINK_MODELS[table]
        if not item_ids:
            raise ValueError("항목을 먼저 선택해주세요.")
        with self.connect() as session:
            if session.get(model, term_id) is None:
                raise ValueError("분류를 선택해주세요.")
            ids = set(item_ids)
            found = set(session.scalars(select(Item.id).where(Item.id.in_(ids))))
            if found != ids:
                raise ValueError("항목을 찾을 수 없습니다.")
            if remove:
                session.execute(delete(link).where(link.item_id.in_(ids), link.term_id == term_id))
            else:
                session.execute(self.insert(link).on_conflict_do_nothing(),
                                [{"item_id": item_id, "term_id": term_id} for item_id in ids])

    def linked_work_items(self) -> list[dict]:
        """Confirmed work→item groups for IP draft selection (aliases excluded).

        Storage category comes from the item id prefix (`FIGURE:…`), not the
        editable payload category. Collab items appear under every linked work.
        """
        with self.connect() as session:
            rows = session.execute(
                select(Work.id, Work.name, Item.id, Item.payload, Item.deadline)
                .join(ItemWork, ItemWork.term_id == Work.id)
                .join(Item, Item.id == ItemWork.item_id)
                .order_by(Work.id, Item.id)
            ).all()
        groups: dict[int, dict] = {}
        for work_id, work_name, item_id, payload, deadline in rows:
            group = groups.setdefault(
                work_id, {"work_id": work_id, "work_name": work_name, "items": []}
            )
            category, _, _ = item_id.partition(":")
            group["items"].append({
                "id": item_id,
                "storage_category": category or "UNKNOWN",
                "deadline": deadline,
                "data": json.loads(payload),
            })
        return list(groups.values())

    def items(self, filters, page=1, collection_id=None):
        query = select(Item)
        for table, link in LINK_MODELS.items():
            if filters.get(table):
                try:
                    term_id = int(filters[table])
                except (TypeError, ValueError):
                    raise ValueError("잘못된 분류입니다.") from None
                query = query.where(exists().where(link.item_id == Item.id, link.term_id == term_id))
        if filters.get("unclassified"):
            link = LINK_MODELS["works"]
            query = query.where(~exists().where(link.item_id == Item.id))
        if filters.get("q"):
            query = query.where(or_(func.lower(Item.title).contains(filters["q"].lower(), autoescape=True),
                                    func.lower(Item.source).contains(filters["q"].lower(), autoescape=True)))
        for key in ("deadline_from", "deadline_to"):
            if filters.get(key):
                value = date.fromisoformat(filters[key]).isoformat()
                query = query.where(Item.deadline >= value if key == "deadline_from" else Item.deadline <= value)
        order = (Item.synced_at.desc(), Item.id)
        if collection_id:
            query = query.join(CollectionItem, CollectionItem.item_id == Item.id).where(
                CollectionItem.collection_id == collection_id)
            query = query.add_columns(CollectionItem.note, CollectionItem.position)
            order = (CollectionItem.position, Item.id)
        with self.connect() as session:
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            records = session.execute(query.order_by(*order).limit(50).offset((max(1, page) - 1) * 50))
            rows = []
            for record in records:
                row = row_dict(record[0])
                row["data"] = json.loads(row.pop("payload"))
                row["terms"] = {table: [] for table in TAXONOMIES}
                if collection_id:
                    row.update(collection_note=record[1], position=record[2])
                rows.append(row)
            by_id = {r["id"]: r for r in rows}
            if by_id:
                for table, model in TERM_MODELS.items():
                    link = LINK_MODELS[table]
                    links = session.execute(select(link.item_id, model.id, model.name).join(
                        model, link.term_id == model.id).where(link.item_id.in_(by_id)).order_by(model.name))
                    for item_id, term_id, name in links:
                        by_id[item_id]["terms"][table].append({"item_id": item_id, "id": term_id, "name": name})
            return rows, total

    def unclassified_report(self, samples=5, top=25):
        """Read-only view of items with no work link, to decide which works to add to the catalog."""
        with self.connect() as session:
            rows = session.execute(
                select(Item.source, Item.title).where(~exists().where(ItemWork.item_id == Item.id))
            ).all()
        by_source, tokens, examples = Counter(), Counter(), {}
        for source, title in rows:
            source = source or "(출처 없음)"
            by_source[source] += 1
            tokens.update(BRACKET_TOKEN.findall(title or ""))
            if len(examples.setdefault(source, [])) < samples:
                examples[source].append(title or "")
        return {
            "total": len(rows),
            "by_source": by_source.most_common(),
            "bracket_tokens": tokens.most_common(top),
            "samples": examples,
        }

    def suggestions(self, items, works):
        result = {}
        for item in items:
            if item["terms"]["works"]:
                continue
            text = item_title_text(item["data"])
            found = []
            for work in works:
                for keyword in work_keywords(work):
                    matched = match_keyword(text, keyword)
                    if matched:
                        found.append({"id": work["id"], "name": work["name"],
                                      "matched": normalized(matched)})
                        break
            result[item["id"]] = found
        return result

    def overview(self):
        with self.connect() as session:
            sync = session.get(SyncState, 1)
            return {
                "collections": [row_dict(r) for r in session.scalars(select(Collection).order_by(Collection.id.desc()))],
                "saved_filters": [row_dict(r) for r in session.scalars(select(SavedFilter).order_by(SavedFilter.id.desc()))],
                "sync": row_dict(sync) if sync else None,
            }

    def save_collection(self, name, note="", collection_id=None):
        name = clean_name(name)
        with self.connect() as session:
            group = session.get(Collection, collection_id) if collection_id else Collection()
            if group is None:
                raise ValueError("기획 묶음을 찾을 수 없습니다.")
            group.name, group.note = name, note
            session.add(group)
            session.flush()
            return group.id

    def add_to_collection(self, collection_id, item_ids):
        if not item_ids:
            raise ValueError("항목을 먼저 선택해주세요.")
        with self.connect() as session:
            position = session.scalar(select(func.coalesce(func.max(CollectionItem.position), 0)).where(
                CollectionItem.collection_id == collection_id))
            for item_id in dict.fromkeys(item_ids):
                position += 1
                session.execute(self.insert(CollectionItem).values(collection_id=collection_id, item_id=item_id,
                                position=position).on_conflict_do_nothing())

    def edit_member(self, collection_id, item_id, note, position, remove=False):
        with self.connect() as session:
            member = session.get(CollectionItem, (collection_id, item_id))
            if member:
                if remove:
                    session.delete(member)
                else:
                    member.note, member.position = note, int(position)

    def save_filter(self, name, filters):
        with self.connect() as session:
            session.add(SavedFilter(name=clean_name(name), filters=json.dumps(
                {k: filters[k] for k in FILTER_KEYS if filters.get(k)})))

    def delete_group(self, table, group_id):
        model = {"collections": Collection, "saved_filters": SavedFilter}.get(table)
        if model is None:
            raise ValueError("잘못된 목록입니다.")
        with self.connect() as session:
            session.execute(delete(model).where(model.id == group_id))


def row_dict(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}
