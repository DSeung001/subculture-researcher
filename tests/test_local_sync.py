"""Offline checks for orphan cleanup, the sync status check and the --sync collection option."""

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import collect
import collect_manual
import collection_runner
import library_database
import prune_library
from content_store import ContentStore, doc_id
from local_library import Library


def cloud_doc(doc_id_, category="FIGURE", title="제목", source="Shop"):
    return SimpleNamespace(
        id=doc_id_,
        reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id=category))),
        to_dict=lambda: {"title": title, "url": f"https://example.com/{doc_id_}", "source": source, "category": "GOODS"},
    )


def cloud(*snapshots):
    db = Mock()
    db.collection_group.return_value.stream.return_value = iter(snapshots)
    return db


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.lib = Library(self.path)
        self.lib.sync(cloud(*(cloud_doc(name) for name in ("a", "b", "c", "d", "e"))))
        # a: tagged, d: in a collection, b/e: no local work, c: still in the cloud
        tag = self.lib.save_term("tags", "관심")
        self.lib.assign(["FIGURE:a"], "tags", tag)
        group = self.lib.save_collection("기획")
        self.lib.add_to_collection(group, ["FIGURE:d"])

    def ids(self):
        rows, _ = self.lib.items({})
        return sorted(row["id"] for row in rows)


class OrphanTests(LibraryCase):
    CLOUD = {"FIGURE:c"}

    def test_orphans_flag_which_ones_carry_local_work(self):
        by_id = {item["id"]: item["curated"] for item in self.lib.orphan_items(self.CLOUD)}
        self.assertEqual(by_id, {"FIGURE:a": True, "FIGURE:b": False, "FIGURE:d": True, "FIGURE:e": False})

    def test_only_items_without_local_work_are_deleted(self):
        result = self.lib.delete_orphans(self.CLOUD)
        self.assertEqual((result["matched"], result["deleted"]), (2, 2))
        self.assertEqual(sorted(item["id"] for item in result["kept_curated"]), ["FIGURE:a", "FIGURE:d"])
        self.assertEqual(self.ids(), ["FIGURE:a", "FIGURE:c", "FIGURE:d"])
        # The curated item keeps its tag and collection membership.
        rows, _ = self.lib.items({})
        tagged = next(row for row in rows if row["id"] == "FIGURE:a")
        self.assertEqual([t["name"] for t in tagged["terms"]["tags"]], ["관심"])

    def test_dry_run_changes_nothing(self):
        result = self.lib.delete_orphans(self.CLOUD, dry_run=True)
        self.assertEqual((result["matched"], result["deleted"]), (2, 0))
        self.assertEqual(len(self.ids()), 5)

    def test_empty_cloud_listing_is_refused(self):
        with self.assertRaises(ValueError):
            self.lib.delete_orphans(set())
        self.assertEqual(len(self.ids()), 5)


class SyncStatusTests(LibraryCase):
    def test_counts_unsynced_and_orphans(self):
        status = self.lib.sync_status({"FIGURE:a", "FIGURE:b", "FIGURE:x", "FIGURE:y"})
        self.assertEqual(status["local_count"], 5)
        self.assertEqual(status["cloud_count"], 4)
        self.assertEqual(status["unsynced"], 2)  # x, y exist only in the cloud
        self.assertEqual(status["orphans"], 3)  # c, d, e exist only locally
        self.assertEqual(status["curated_orphans"], 1)  # d
        self.assertTrue(status["last_sync"])

    def test_fresh_library_has_no_sync_record(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Library(Path(directory) / "new.sqlite3").sync_status({"FIGURE:a"})
        self.assertIsNone(status["last_sync"])
        self.assertEqual((status["local_count"], status["unsynced"]), (0, 1))


class ItemIdsTests(unittest.TestCase):
    def test_ids_come_from_the_index_already_read(self):
        def snap(name, category):
            url = f"https://example.com/{name}"
            ref = SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id=category)))
            return SimpleNamespace(id=doc_id(url), reference=ref, to_dict=lambda: {"url": url, "status": "NEW"})
        db = Mock()
        db.collection_group.return_value.select.return_value.stream.return_value = iter(
            [snap("a", "FIGURE"), snap("b", "GOODS")])
        store = ContentStore(db)
        self.assertEqual(store.item_ids(), {
            f"FIGURE:{doc_id('https://example.com/a')}", f"GOODS:{doc_id('https://example.com/b')}"})
        self.assertEqual(ContentStore(None).item_ids(), set())


def run_quiet(function, *args, **kwargs):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = function(*args, **kwargs)
    return result, buffer.getvalue()


class ReportLocalSyncTests(unittest.TestCase):
    STATUS = {"last_sync": "2026-09-19T08:52:46+00:00", "local_count": 632, "cloud_count": 805,
              "unsynced": 220, "orphans": 47, "curated_orphans": 1}

    def test_prints_the_gap_and_the_next_steps(self):
        store = Mock()
        store.item_ids.return_value = {"FIGURE:a"}
        with patch("local_library.Library") as library:
            library.return_value.sync_status.return_value = self.STATUS
            _, output = run_quiet(collection_runner.report_local_sync, store)
        library.return_value.sync_status.assert_called_once_with({"FIGURE:a"})
        for text in ("로컬 632", "클라우드 805", "미동기화 220", "로컬에만 47", "--sync", "prune_library.py"):
            self.assertIn(text, output)

    def test_up_to_date_prints_no_hints(self):
        status = {**self.STATUS, "unsynced": 0, "orphans": 1, "curated_orphans": 1}
        with patch("local_library.Library") as library:
            library.return_value.sync_status.return_value = status
            _, output = run_quiet(collection_runner.report_local_sync, Mock(item_ids=lambda: set()))
        self.assertIn("미동기화 0", output)
        self.assertNotIn("→", output)

    def test_a_stopped_local_database_only_skips_the_check(self):
        with patch("local_library.Library", side_effect=RuntimeError("connection refused\nsecond line")):
            _, output = run_quiet(collection_runner.report_local_sync, Mock())
        self.assertIn("확인 건너뜀: connection refused", output)
        self.assertNotIn("second line", output)


class RunCollectionCheckTests(unittest.TestCase):
    def run_it(self, **kwargs):
        with patch.object(collection_runner, "ContentStore") as store, \
                patch.object(collection_runner, "report_local_sync") as report:
            store.return_value.duplicates.return_value = []
            store.return_value.invalid_urls = []
            run_quiet(collection_runner.run_collection, [], **kwargs)
        return report

    def test_check_runs_once_from_the_existing_index_only_when_asked(self):
        self.assertEqual(self.run_it(db=Mock(), local_check=True).call_count, 1)
        self.assertEqual(self.run_it(db=Mock()).call_count, 0)
        self.assertEqual(self.run_it(db=None, local_check=True).call_count, 0)  # dry run has no cloud ids


class SyncAfterCollectionTests(unittest.TestCase):
    def run_main(self, module, argv, env=None):
        environ = {key: value for key, value in os.environ.items() if key != "CI"}
        environ.update(env or {})
        with patch.object(module, "get_db", return_value=Mock()),                 patch.object(module, "load_sources", return_value=[]),                 patch.object(module, "run_collection") as run,                 patch.object(module, "sync_local") as sync,                 patch.object(module, "run_trending_draft", return_value="ok"),                 patch.dict("os.environ", environ, clear=True):
            run_quiet(module.main, argv)
        return run, sync

    def test_sync_runs_after_collection_only_with_the_flag(self):
        for module in (collect, collect_manual):
            with self.subTest(module=module.__name__):
                _, sync = self.run_main(module, ["--no-ai-draft"] if module is collect else [])
                sync.assert_not_called()
                _, sync = self.run_main(module, ["--sync", "--no-ai-draft"] if module is collect else ["--sync"])
                sync.assert_called_once()

    def test_dry_run_never_syncs_or_checks(self):
        run, sync = self.run_main(collect, ["--dry-run", "--sync"])
        sync.assert_not_called()
        self.assertFalse(run.call_args.kwargs["local_check"])

    def test_check_is_on_locally_and_off_in_ci_or_with_the_flag(self):
        run, _ = self.run_main(collect, ["--no-ai-draft"])
        self.assertTrue(run.call_args.kwargs["local_check"])
        run, _ = self.run_main(collect, ["--no-ai-draft", "--no-local-check"])
        self.assertFalse(run.call_args.kwargs["local_check"])
        run, _ = self.run_main(collect, ["--no-ai-draft"], env={"CI": "true"})
        self.assertFalse(run.call_args.kwargs["local_check"])

    def test_sync_local_failure_is_reported_not_raised(self):
        with patch("local_library.Library", side_effect=RuntimeError("db down")):
            ok, output = run_quiet(collection_runner.sync_local, Mock())
        self.assertFalse(ok)
        self.assertIn("수집 결과에는 영향 없음", output)
        with patch("local_library.Library") as library:
            library.return_value.sync.return_value = 12
            ok, output = run_quiet(collection_runner.sync_local, Mock())
        self.assertTrue(ok)
        self.assertIn("12개", output)


class BackupTests(unittest.TestCase):
    def test_sqlite_backup_copies_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(Path(directory) / "library.sqlite3")
            backup = library_database.backup_library(library.engine)
            self.assertTrue(backup.exists())
            self.assertTrue(backup.name.endswith(".bak"))

    def test_postgres_backup_failure_raises(self):
        engine = Mock()
        engine.dialect.name = "postgresql"
        engine.url = SimpleNamespace(host="127.0.0.1", port=55432, username="u", password="p", database="d")
        with patch.object(library_database.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "pg_dump")):
            with self.assertRaises(subprocess.CalledProcessError):
                library_database.backup_library(engine)


class PostgresBackupFallbackTests(unittest.TestCase):
    def engine(self, host):
        engine = Mock()
        engine.dialect.name = "postgresql"
        engine.url = SimpleNamespace(host=host, port=55432, username="u", password="p", database="d")
        return engine

    def test_local_server_version_mismatch_falls_back_to_the_container_pg_dump(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[0] == "pg_dump":
                raise subprocess.CalledProcessError(1, "pg_dump")  # host client older than the server
            kwargs["stdout"].write(b"PGDMP")
        with patch.object(library_database.subprocess, "run", side_effect=fake_run),                 patch.object(library_database, "__file__", str(Path(tempfile.gettempdir()) / "x.py")):
            backup = library_database.backup_library(self.engine("127.0.0.1"))
            try:
                self.assertEqual(backup.read_bytes(), b"PGDMP")
                self.assertEqual(calls[1][:5], ["docker", "compose", "exec", "-T", "db"])
            finally:
                backup.unlink(missing_ok=True)

    def test_remote_server_has_no_container_fallback(self):
        with patch.object(library_database.subprocess, "run",
                          side_effect=subprocess.CalledProcessError(1, "pg_dump")) as run,                 patch.object(library_database, "__file__", str(Path(tempfile.gettempdir()) / "x.py")):
            with self.assertRaises(subprocess.CalledProcessError):
                library_database.backup_library(self.engine("db.example.com"))
        self.assertEqual(run.call_count, 1)

    def test_an_empty_container_dump_is_a_failure_and_leaves_no_file(self):
        def fake_run(command, **kwargs):
            if command[0] == "pg_dump":
                raise FileNotFoundError("pg_dump")
        with patch.object(library_database.subprocess, "run", side_effect=fake_run),                 patch.object(library_database, "__file__", str(Path(tempfile.gettempdir()) / "x.py")):
            with self.assertRaises(RuntimeError):
                library_database.backup_library(self.engine("localhost"))
        leftovers = list((Path(tempfile.gettempdir()) / ".local" / "backups").glob("library-*.dump"))
        self.assertEqual([p for p in leftovers if p.stat().st_size == 0], [])


class PruneCliTests(LibraryCase):
    def cloud_db(self, *names):
        db = Mock()
        db.collection_group.return_value.select.return_value.stream.return_value = iter(
            [cloud_doc(name) for name in names])
        return db

    def main(self, argv, backup=None):
        with patch.object(prune_library, "get_db", return_value=self.cloud_db("c")), \
                patch.object(prune_library, "backup_library", backup or Mock(return_value=Path("x.dump"))) as made:
            _, output = run_quiet(prune_library.main, ["--db", str(self.path), *argv])
        return made, output

    def test_dry_run_lists_and_neither_backs_up_nor_deletes(self):
        made, output = self.main(["--dry-run"])
        made.assert_not_called()
        self.assertIn("[삭제 대상] 2건", output)
        self.assertIn("[작업이 있어 보존] 2건", output)
        self.assertEqual(len(self.ids()), 5)

    def test_real_run_backs_up_first_then_deletes(self):
        made, output = self.main([])
        made.assert_called_once()
        self.assertIn("[삭제] 2건", output)
        self.assertEqual(self.ids(), ["FIGURE:a", "FIGURE:c", "FIGURE:d"])

    def test_failed_backup_deletes_nothing(self):
        failing = Mock(side_effect=subprocess.CalledProcessError(1, "pg_dump"))
        with self.assertRaises(subprocess.CalledProcessError):
            self.main([], backup=failing)
        self.assertEqual(len(self.ids()), 5)


if __name__ == "__main__":
    unittest.main()
