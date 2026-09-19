import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from library_database import SchemaError, head, make_engine, upgrade_database
from library_models import Base
from local_library import Library


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"

    def legacy(self):
        sql = Path(__file__).with_name("fixtures").joinpath("library_v1.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(self.path)) as con:
            con.executescript(sql)
            con.execute("INSERT INTO items VALUES ('FIGURE:legacy', '예약 굿즈', 'https://example.com/1', 'shop', '{}', NULL, '2026-09-19')")
            con.execute("INSERT INTO works VALUES (7, '프리렌', '프리렌')")
            con.execute("INSERT INTO work_aliases VALUES (7, 'Frieren', 'frieren')")
            con.execute("INSERT INTO item_works VALUES ('FIGURE:legacy', 7)")
            con.execute("INSERT INTO tags VALUES (8, '관심', '관심')")
            con.execute("INSERT INTO item_tags VALUES ('FIGURE:legacy', 8)")
            con.execute("INSERT INTO collections VALUES (9, '기획', '메모')")
            con.execute("INSERT INTO collection_items VALUES (9, 'FIGURE:legacy', 3, '소개 메모')")
            con.execute("INSERT INTO saved_filters VALUES (10, '관심 작품', '{\"works\": \"7\"}')")
            con.commit()

    def test_new_database_schema_matches_models(self):
        lib = Library(self.path)
        with lib.engine.connect() as con:
            self.assertEqual(MigrationContext.configure(con).get_current_heads(), (head(),))
            differences = compare_metadata(MigrationContext.configure(con, opts={"compare_server_default": True}), Base.metadata)
            self.assertEqual(differences, [])
        self.assertEqual(len(lib.terms()["product_categories"]), 4)
        with lib.engine.connect() as con:  # hidden from the screens, still seeded in the database
            self.assertEqual(con.exec_driver_sql("SELECT COUNT(*) FROM information_types").scalar(), 4)

    def test_legacy_requires_explicit_upgrade_and_preserves_all_data(self):
        self.legacy()
        before = self.path.read_bytes()
        with self.assertRaises(SchemaError):
            Library(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        backup = upgrade_database(self.path)
        self.assertTrue(backup.is_file())
        with closing(sqlite3.connect(backup)) as con:
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone())
        lib = Library(self.path)
        rows, total = lib.items({"works": 7}, collection_id=9)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["collection_note"], "소개 메모")
        self.assertEqual(lib.terms()["works"][0]["aliases"], "Frieren")
        # Tags and saved filters are no longer shown, but their rows survive the upgrade.
        with lib.engine.connect() as con:
            self.assertEqual(con.exec_driver_sql("SELECT term_id FROM item_tags").fetchall(), [(8,)])
            self.assertEqual(con.exec_driver_sql("SELECT id FROM saved_filters").fetchall(), [(10,)])
            # Do not reinsert defaults the user had deleted in the legacy database.
            self.assertEqual(con.exec_driver_sql("SELECT COUNT(*) FROM information_types").scalar(), 0)
        self.assertIsNone(upgrade_database(self.path))
        self.assertEqual(len(list(self.path.parent.glob("*.bak"))), 1)

    def test_draft_tables_are_added_without_touching_existing_rows(self):
        from alembic import command
        from library_database import config

        engine = make_engine(self.path, foreign_keys=False)
        with engine.begin() as connection:  # a database still at the previous head
            cfg = config()
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "0003_required_primary_keys")
        engine.dispose()
        with closing(sqlite3.connect(self.path)) as con:
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='drafts'").fetchone())
            con.execute("INSERT INTO items VALUES ('FIGURE:x', '굿즈', 'https://example.com/x', 'shop', '{}', NULL, '2026-09-19')")
            con.execute("INSERT INTO works VALUES (5, '작품', '작품')")
            con.execute("INSERT INTO item_works VALUES ('FIGURE:x', 5)")
            con.commit()
        with self.assertRaises(SchemaError):
            Library(self.path)  # not upgraded implicitly
        self.assertTrue(upgrade_database(self.path).is_file())  # backup first
        with closing(sqlite3.connect(self.path)) as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"drafts", "draft_items"} <= tables)
            self.assertEqual(con.execute("SELECT title FROM items").fetchall(), [("굿즈",)])
            self.assertEqual(con.execute("SELECT * FROM item_works").fetchall(), [("FIGURE:x", 5)])
            self.assertEqual(con.execute("SELECT COUNT(*) FROM drafts").fetchone(), (0,))
        lib = Library(self.path)
        with lib.connect() as session:
            from library_models import Draft, DraftItem
            draft = Draft(angle="NEWS", body="본문", created_at="t", updated_at="t")
            session.add(draft)
            session.flush()
            session.add(DraftItem(draft_id=draft.id, item_id="FIGURE:gone"))  # no foreign key on item_id
            self.assertEqual(draft.status, "DRAFT")

    def test_postgres_chain_ends_at_the_drafts_revision(self):
        self.assertEqual(head("postgresql"), "pg0002_drafts")
        self.assertEqual(head(), "0004_drafts")

    def test_unknown_or_incomplete_schema_is_rejected_without_stamp(self):
        self.legacy()
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("ALTER TABLE works ADD COLUMN unexpected TEXT")
        with self.assertRaisesRegex(RuntimeError, "v1"):
            upgrade_database(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone())
            self.assertEqual(con.execute("SELECT name FROM works WHERE id=7").fetchone()[0], "프리렌")

    def test_failed_migration_rolls_back_schema_and_data(self):
        self.legacy()
        def fail(cfg, target):
            con = cfg.attributes["connection"]
            con.exec_driver_sql("ALTER TABLE works ADD COLUMN temporary TEXT")
            con.exec_driver_sql("UPDATE works SET name='lost'")
            raise RuntimeError("migration failed")
        with patch("library_database.command.upgrade", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                upgrade_database(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertNotIn("temporary", [r[1] for r in con.execute("PRAGMA table_info(works)")])
            self.assertEqual(con.execute("SELECT name FROM works WHERE id=7").fetchone()[0], "프리렌")

    def test_foreign_keys_enabled_in_every_runtime_session(self):
        lib = Library(self.path)
        for _ in range(2):
            with self.assertRaises(IntegrityError):
                lib.add_to_collection(999, ["missing"])

    def test_future_revision_is_not_silently_changed(self):
        Library(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("UPDATE alembic_version SET version_num='future'")
            con.commit()
        with self.assertRaises(SchemaError):
            Library(self.path)


if __name__ == "__main__":
    unittest.main()
