"""Local curation database. Imported source records never own editorial relations."""

import json
import re
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, cast, delete, exists, func, or_, select, type_coerce
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session

from subculture.library.domain.keywords import (
    BRACKET_TOKEN, clean_name, item_title_text, match_keyword, normalized, work_keywords,
)
from subculture.library.domain.taxonomy import TAXONOMIES
from subculture.library.infrastructure.database import DEFAULT_PATH, ensure_schema, make_engine
from subculture.library.infrastructure.models import (Collection, CollectionItem, Draft, DraftItem, Item, ItemWork, LINK_MODELS,
                            SyncState, TERM_MODELS, Work, WorkAlias)

from subculture.shared.content_model import content_id
from subculture.shared.untitled_content import UNTITLED_TITLE, is_untitled_leftover


def json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported source value: {type(value).__name__}")


class Library:
    def __init__(self, path=None, *, connect_timeout=None):
        self.engine = make_engine(path, connect_timeout=connect_timeout)
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
                      for table, model in TERM_MODELS.items() if table in TAXONOMIES}
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

    def orphan_items(self, cloud_ids):
        """Local items whose id is not in `cloud_ids` (removed remotely); `curated` marks local work on them."""
        cloud_ids = set(cloud_ids)
        with self.connect() as session:
            rows = session.execute(select(Item.id, Item.source, Item.title)).all()
            curated = set(session.scalars(select(CollectionItem.item_id)))
            curated.update(session.scalars(select(DraftItem.item_id)))  # sources of a draft
            for table, model in LINK_MODELS.items():
                if table == "product_categories":
                    continue  # sync links every FIGURE item to 피규어 by itself, so it says nothing about local work
                curated.update(session.scalars(select(model.item_id)))
        return [{"id": item_id, "source": source or "", "title": title or "", "curated": item_id in curated}
                for item_id, source, title in rows if item_id not in cloud_ids]

    def delete_orphans(self, cloud_ids, *, dry_run: bool = False) -> dict:
        """Delete remote-missing items that carry no local work. Curated ones are kept and reported."""
        cloud_ids = set(cloud_ids)
        if not cloud_ids:
            # An empty listing means the remote read failed or is empty; never treat everything as removed.
            raise ValueError("클라우드 항목 목록이 비어 있어 정리하지 않습니다.")
        orphans = self.orphan_items(cloud_ids)
        removable = [item for item in orphans if not item["curated"]]
        if not dry_run:
            self.delete_items([item["id"] for item in removable])
        return {
            "matched": len(removable),
            "deleted": 0 if dry_run else len(removable),
            "dry_run": dry_run,
            "items": removable,
            "kept_curated": [item for item in orphans if item["curated"]],
        }

    def sync_status(self, cloud_ids) -> dict:
        """How far the local copy is from the cloud, judged by item ids only."""
        cloud_ids = set(cloud_ids)
        with self.connect() as session:
            local_ids = set(session.scalars(select(Item.id)))
            state = session.get(SyncState, 1)
            last_sync = state.completed_at if state else None
        orphans = self.orphan_items(cloud_ids)
        return {
            "last_sync": last_sync,
            "local_count": len(local_ids),
            "cloud_count": len(cloud_ids),
            "unsynced": len(cloud_ids - local_ids),
            "orphans": len(orphans),
            "curated_orphans": sum(1 for item in orphans if item["curated"]),
        }

    @staticmethod
    def _record(snapshot, now):
        """One Firestore contents document as a local `items` row."""
        data = snapshot.to_dict() or {}
        deadline = data.get("preorderEndAt")
        if isinstance(deadline, (date, datetime)):
            deadline = deadline.isoformat()[:10]
        try:
            deadline = date.fromisoformat(deadline).isoformat() if deadline else None
        except (ValueError, TypeError):
            deadline = None
        return dict(id=content_id(snapshot),
                    title=data.get("titleKo") or data.get("title") or "(제목 없음)",
                    url=data.get("url") or "", source=data.get("source") or "",
                    payload=json.dumps(data, ensure_ascii=False, default=json_default),
                    deadline=deadline, synced_at=now)

    def _upsert_items(self, session, records):
        if not records:
            return
        statement = self.insert(Item)
        statement = statement.on_conflict_do_update(
            index_elements=[Item.id],
            set_={key: getattr(statement.excluded, key) for key in
                  ("title", "url", "source", "payload", "deadline", "synced_at")})
        session.execute(statement, records)

    def sync(self, cloud):
        # Read outside the local transaction. A failed remote stream leaves the
        # previous snapshot and every local relation intact. No cloud writes.
        now = datetime.now(timezone.utc).isoformat()
        records = [self._record(snapshot, now) for snapshot in cloud.collection_group("contents").stream()]
        with self.connect() as session:
            self._upsert_items(session, records)
            session.merge(SyncState(id=1, completed_at=now, item_count=len(records)))
        # New source rows only: additive keyword links for still-unlinked items.
        self.auto_assign_works(unclassified_only=True)
        self.auto_assign_product_categories()
        return len(records)

    def upsert_snapshots(self, snapshots):
        """Add or refresh only the given Firestore documents (never deletes); the sync record stays as is."""
        now = datetime.now(timezone.utc).isoformat()
        records = [self._record(snapshot, now) for snapshot in snapshots]
        with self.connect() as session:
            self._upsert_items(session, records)
        if records:
            self.auto_assign_works(unclassified_only=True)
            self.auto_assign_product_categories()
        return len(records)

    def items_by_id(self, item_ids):
        """Stored documents by item id (payload plus `_id`); ids that are not stored are absent."""
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return {}
        with self.connect() as session:
            rows = session.execute(select(Item.id, Item.payload).where(Item.id.in_(ids))).all()
        result = {}
        for item_id, payload in rows:
            data = json.loads(payload)
            data["_id"] = item_id
            result[item_id] = data
        return result

    def posted_item_ids(self, item_ids=None):
        """Item ids that belong to a published draft (optionally limited to `item_ids`)."""
        query = select(DraftItem.item_id).join(Draft, Draft.id == DraftItem.draft_id).where(Draft.status == "POSTED")
        if item_ids is not None:
            ids = list(dict.fromkeys(item_ids))
            if not ids:
                return set()
            query = query.where(DraftItem.item_id.in_(ids))
        with self.connect() as session:
            return set(session.scalars(query))

    def draft_candidates(self, category=None):
        """Every stored document a new draft could use: not ignored, not posted, not in a published draft."""
        used = self.posted_item_ids()
        with self.connect() as session:
            rows = session.execute(select(Item.id, Item.payload)).all()
        items = []
        for item_id, payload in rows:
            data = json.loads(payload)
            if item_id in used or data.get("status") == "IGNORE" or data.get("postedAt"):
                continue
            if category is not None and (data.get("category") or "UNKNOWN") != category:
                continue
            data["_id"] = item_id
            items.append(data)
        return items

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

    def auto_assign_product_categories(self):
        """Link FIGURE: items to the seeded '피규어' product category when they have none.

        Additive only: items that already have any product_categories link are skipped.
        Returns the number of new links inserted.
        """
        model = TERM_MODELS["product_categories"]
        link = LINK_MODELS["product_categories"]
        with self.connect() as session:
            term = session.scalar(select(model).where(model.name == "피규어"))
            if term is None:
                return 0
            rows = session.execute(
                select(Item.id).where(
                    Item.id.like("FIGURE:%"),
                    ~exists().where(link.item_id == Item.id),
                )
            ).all()
            if not rows:
                return 0
            pairs = [{"item_id": item_id, "term_id": term.id} for (item_id,) in rows]
            before = session.scalar(select(func.count()).select_from(link)) or 0
            session.execute(self.insert(link).on_conflict_do_nothing(), pairs)
            after = session.scalar(select(func.count()).select_from(link)) or 0
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

    def _collected_at(self):
        """`collectedAt` from the stored document (ISO text, UTC, so it sorts as text); "" when missing."""
        # Text is not JSON for PostgreSQL, while a CAST to JSON on SQLite would read it as a number.
        if self.engine.dialect.name == "postgresql":
            payload = cast(Item.payload, JSON)
        else:
            payload = type_coerce(Item.payload, JSON)
        return func.coalesce(payload["collectedAt"].as_string(), "")

    def items(self, filters, page=1, collection_id=None):
        query = select(Item)
        for table in TAXONOMIES:
            link = LINK_MODELS[table]
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
        # Newest collected first. `synced_at` is one timestamp per sync run, so it cannot order items.
        order = (self._collected_at().desc(), Item.id)
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
                for table in TAXONOMIES:
                    model, link = TERM_MODELS[table], LINK_MODELS[table]
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

    def overview(self):
        with self.connect() as session:
            sync = session.get(SyncState, 1)
            return {
                "collections": [row_dict(r) for r in session.scalars(select(Collection).order_by(Collection.id.desc()))],
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

    def remove_member(self, collection_id, item_id):
        with self.connect() as session:
            member = session.get(CollectionItem, (collection_id, item_id))
            if member:
                session.delete(member)

    def delete_collection(self, collection_id):
        with self.connect() as session:
            session.execute(delete(Collection).where(Collection.id == collection_id))


def row_dict(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}
