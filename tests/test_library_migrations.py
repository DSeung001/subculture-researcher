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
        self.assertEqual(len(lib.terms()["information_types"]), 4)

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
        self.assertEqual(rows[0]["terms"]["tags"][0]["id"], 8)
        self.assertEqual(lib.terms()["works"][0]["aliases"], "Frieren")
        self.assertEqual(lib.overview()["saved_filters"][0]["id"], 10)
        # Do not reinsert defaults the user had deleted in the legacy database.
        self.assertEqual(lib.terms()["information_types"], [])
        self.assertIsNone(upgrade_database(self.path))
        self.assertEqual(len(list(self.path.parent.glob("*.bak"))), 1)

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
