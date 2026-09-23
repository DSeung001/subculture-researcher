"""Offline checks for bulk image export (files + index.json, no real HTTP)."""

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from subculture.library.application.export_images import (
    ExportError, ExportOptions, export_images, resolve_item_ids, zip_export,
)
from subculture.library.application.export_jobs import ExportJobs
from subculture.library.infrastructure.download_ledger import DownloadLedger
from subculture.library.infrastructure.local_library import Library

JPEG = b"\xff\xd8\xff\xe0JPEG"
PNG = b"\x89PNG\r\n\x1a\nPNG"
HTML = b"<!doctype html><title>404</title>"


def snapshot(doc_id, title="상품", category="FIGURE", **fields):
    return SimpleNamespace(
        id=doc_id,
        reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id=category))),
        to_dict=lambda: {
            "title": title,
            "url": f"https://shop.example.com/{doc_id}",
            "source": "Shop",
            **fields,
        },
    )


def cloud(*snapshots):
    db = Mock()
    db.collection_group.return_value.stream.return_value = iter(snapshots)
    return db


class ExportImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.lib = Library(self.path)
        self.lib.sync(cloud(
            snapshot(
                "a",
                title="상품 A",
                shop="따빼몰",
                imageUrl="https://cdn.example.com/a/main.jpg",
                detailImageUrls=[
                    "https://cdn.example.com/a/d1.jpg",
                    "javascript:alert(1)",
                    "https://cdn.example.com/a/d2.png",
                ],
            ),
            snapshot("b", title="사진 없음"),
        ))
        self.out = Path(self.temp.name) / "export"

    def test_writes_files_and_index(self):
        bodies = {
            "https://cdn.example.com/a/main.jpg": (JPEG, "image/jpeg"),
            "https://cdn.example.com/a/d1.jpg": (JPEG + b"1", "image/jpeg"),
            "https://cdn.example.com/a/d2.png": (PNG, "image/png"),
        }

        def fetch(url, *, timeout):
            return bodies[url]

        root = export_images(
            self.lib, ["FIGURE:a", "FIGURE:b"],
            directory=self.out, options=ExportOptions(pause_seconds=0), fetch=fetch,
        )
        index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index), 2)
        entry = index[0]
        self.assertEqual(entry["id"], "FIGURE:a")
        self.assertEqual(entry["shop"], "따빼몰")
        self.assertEqual(
            entry["detailImageUrls"],
            ["https://cdn.example.com/a/d1.jpg", "https://cdn.example.com/a/d2.png"],
        )
        self.assertEqual([f["status"] for f in entry["files"]], ["ok", "ok", "ok"])
        first = entry["files"][0]
        self.assertEqual((root / first["path"]).read_bytes(), JPEG)
        self.assertEqual(first["path"], "items/FIGURE_a/00_main.jpg")
        self.assertEqual(first["key"], "FIGURE_a-00")
        self.assertEqual(first["format"], "jpeg")
        self.assertEqual(first["bytes"], len(JPEG))
        self.assertEqual(len(first["sha256"]), 64)
        self.assertTrue(entry["files"][2]["path"].endswith(".png"))
        self.assertEqual(index[1]["files"], [])
        meta = json.loads((root / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["formatVersion"], 3)
        self.assertEqual((meta["itemCount"], meta["fileCount"], meta["okCount"]), (2, 3, 3))
        self.assertEqual((meta["skippedCount"], meta["errorCount"], meta["stopReason"]), (0, 0, None))
        self.assertEqual(meta["bytes"], len(JPEG) * 2 + 1 + len(PNG))

    def test_extension_follows_content_not_headers(self):
        bodies = {
            "https://cdn.example.com/a/main.jpg": (PNG, "image/jpeg"),
            "https://cdn.example.com/a/d1.jpg": (HTML, "text/html"),
            "https://cdn.example.com/a/d2.png": (HTML, "image/png"),
        }
        root = export_images(
            self.lib, ["FIGURE:a"], directory=self.out, options=ExportOptions(pause_seconds=0),
            fetch=lambda url, *, timeout: bodies[url],
        )
        files = json.loads((root / "index.json").read_text(encoding="utf-8"))[0]["files"]
        self.assertEqual(files[0]["path"], "items/FIGURE_a/00_main.png")
        self.assertEqual(files[0]["format"], "png")
        for record in files[1:]:
            self.assertEqual(record["status"], "error")
            self.assertIsNone(record["path"])
            self.assertIsNone(record["sha256"])
            self.assertTrue(record["error"].startswith("not_image"))
        self.assertEqual(sorted(p.name for p in (root / "items" / "FIGURE_a").iterdir()), ["00_main.png"])
        self.assertEqual(json.loads((root / "export.json").read_text(encoding="utf-8"))["okCount"], 1)

    def test_default_directory_follows_figure_project_dir(self):
        from unittest.mock import patch
        from subculture.shared.paths import figure_project_dir

        with patch.dict(os.environ, {"FIGURE_PROJECT_DIR": self.temp.name}):
            root = export_images(
                self.lib, ["FIGURE:b"], options=ExportOptions(pause_seconds=0),
                fetch=lambda url, *, timeout: (_ for _ in ()).throw(AssertionError("no fetch")),
            )
        self.assertEqual(root.parent, Path(self.temp.name) / "exports")
        self.assertTrue((root / "index.json").is_file())
        with patch.dict(os.environ, {"FIGURE_PROJECT_DIR": ""}):
            self.assertEqual(figure_project_dir(), Path.home() / "figure_project")

    def test_folder_names_unique_after_sanitizing(self):
        from subculture.library.application.export_images import _folder_name

        used = set()
        self.assertEqual(_folder_name("FIGURE:x", used), "FIGURE_x")
        self.assertEqual(_folder_name("FIGURE_x", used), "FIGURE_x-2")
        self.assertEqual(_folder_name("", used), "item")

    def test_zip_contains_index(self):
        export_images(
            self.lib, ["FIGURE:b"], directory=self.out, options=ExportOptions(pause_seconds=0),
            fetch=lambda url, *, timeout: (_ for _ in ()).throw(AssertionError("no fetch")),
        )
        archive = zip_export(self.out)
        with zipfile.ZipFile(archive) as zf:
            self.assertIn("index.json", zf.namelist())

    def test_resolve_by_work(self):
        work_id = self.lib.save_term("works", "테스트작")
        self.lib.assign(["FIGURE:a"], "works", work_id)
        self.assertEqual(resolve_item_ids(self.lib, work_id=work_id), ["FIGURE:a"])
        with self.assertRaises(ExportError):
            resolve_item_ids(self.lib)


def all_images(url, *, timeout):
    return (PNG if url.endswith(".png") else JPEG), "image/jpeg"


class ExportOptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.lib = Library(Path(self.temp.name) / "library.sqlite3")
        self.lib.sync(cloud(*[
            snapshot(
                name, imageUrl=f"https://cdn.example.com/{name}/main.jpg",
                detailImageUrls=[f"https://cdn.example.com/{name}/d{i}.jpg" for i in range(3)],
            )
            for name in ("a", "b", "c")
        ]))
        self.ids = ["FIGURE:a", "FIGURE:b", "FIGURE:c"]
        self.exports = Path(self.temp.name) / "exports"

    def run_export(self, name="run", fetch=all_images, **kwargs):
        return export_images(
            self.lib, kwargs.pop("ids", self.ids), directory=self.exports / name, fetch=fetch, **kwargs,
        )

    @staticmethod
    def index(root):
        return json.loads((root / "index.json").read_text(encoding="utf-8"))

    @staticmethod
    def meta(root):
        return json.loads((root / "export.json").read_text(encoding="utf-8"))

    def test_item_and_image_limits_and_role_filters(self):
        root = self.run_export(options=ExportOptions(max_items=2, max_images_per_item=2, pause_seconds=0))
        index = self.index(root)
        self.assertEqual([entry["id"] for entry in index], ["FIGURE:a", "FIGURE:b"])
        self.assertEqual([f["role"] for f in index[0]["files"]], ["main", "detail"])

        details = self.run_export("details", options=ExportOptions(
            include_main=False, pause_seconds=0, skip_downloaded=False))
        self.assertEqual({f["role"] for e in self.index(details) for f in e["files"]}, {"detail"})
        self.assertEqual(self.index(details)[0]["files"][0]["path"], "items/FIGURE_a/00_detail.jpg")

        main = self.run_export("main", options=ExportOptions(
            include_detail=False, pause_seconds=0, skip_downloaded=False))
        self.assertEqual([len(e["files"]) for e in self.index(main)], [1, 1, 1])
        self.assertEqual(self.meta(main)["options"]["include_detail"], False)

    def test_invalid_options_are_refused(self):
        for kwargs in ({"include_main": False, "include_detail": False}, {"max_items": 0},
                       {"max_total_bytes": -1}, {"pause_seconds": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ExportError):
                ExportOptions(**kwargs)

    def test_total_size_cap_stops_without_saving_the_overflow_file(self):
        cap = len(JPEG) * 4 + 1  # a's four images fit, b's first one would overflow
        root = self.run_export(options=ExportOptions(max_total_bytes=cap, pause_seconds=0))
        index = self.index(root)
        self.assertEqual([entry["id"] for entry in index], ["FIGURE:a", "FIGURE:b"])
        self.assertEqual([f["status"] for f in index[0]["files"]], ["ok"] * 4)
        overflow = index[1]["files"]
        self.assertEqual((len(overflow), overflow[0]["status"], overflow[0]["error"]), (1, "error", "size_limit"))
        self.assertFalse(any((root / "items" / "FIGURE_b").iterdir()))
        meta = self.meta(root)
        self.assertEqual((meta["stopReason"], meta["bytes"]), ("size_limit", len(JPEG) * 4))

    def test_should_stop_cancels_at_the_next_item_and_progress_is_reported(self):
        seen = []
        root = self.run_export(
            options=ExportOptions(pause_seconds=0),
            progress=lambda p: seen.append((p.items_done, p.files_ok, p.finished)),
            should_stop=lambda: len(seen) >= 1,
        )
        self.assertEqual([entry["id"] for entry in self.index(root)], ["FIGURE:a"])
        self.assertEqual(self.meta(root)["stopReason"], "cancelled")
        self.assertEqual(seen, [(1, 4, False), (1, 4, True)])

    def test_second_export_skips_urls_already_saved(self):
        first = self.run_export("first", options=ExportOptions(pause_seconds=0))
        calls = []

        def counting(url, *, timeout):
            calls.append(url)
            return all_images(url, timeout=timeout)

        second = self.run_export("second", fetch=counting, options=ExportOptions(pause_seconds=0))
        self.assertEqual(calls, [])
        record = self.index(second)[0]["files"][0]
        self.assertEqual(record["status"], "skipped")
        self.assertIsNone(record["path"])
        self.assertEqual(record["previousPath"], "first/items/FIGURE_a/00_main.jpg")
        self.assertEqual(record["sha256"], self.index(first)[0]["files"][0]["sha256"])
        self.assertEqual((self.meta(second)["skippedCount"], self.meta(second)["okCount"]), (12, 0))

        (first / "items" / "FIGURE_a" / "00_main.jpg").unlink()  # deleted file -> download again
        third = self.run_export("third", fetch=counting, options=ExportOptions(pause_seconds=0))
        self.assertEqual(calls, ["https://cdn.example.com/a/main.jpg"])
        self.assertEqual(self.index(third)[0]["files"][0]["status"], "ok")

        no_skip = self.run_export("no-skip", fetch=counting,
                                  options=ExportOptions(pause_seconds=0, skip_downloaded=False))
        self.assertEqual(self.meta(no_skip)["okCount"], 12)

    def test_old_exports_without_a_ledger_are_not_read(self):
        old = self.exports / "old"
        (old / "items" / "FIGURE_a").mkdir(parents=True)
        (old / "items" / "FIGURE_a" / "00_main.jpg").write_bytes(JPEG)
        (old / "index.json").write_text(json.dumps([{"id": "FIGURE:a", "files": [{
            "url": "https://cdn.example.com/a/main.jpg", "path": "items/FIGURE_a/00_main.jpg", "status": "ok",
        }]}]), encoding="utf-8")
        ledger = DownloadLedger(self.exports)
        self.assertIsNone(ledger.lookup("https://cdn.example.com/a/main.jpg"))
        self.assertFalse((self.exports / "ledger.jsonl").exists())


class ExportJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        Library(self.path).sync(cloud(snapshot("a", imageUrl="https://cdn.example.com/a.jpg")))

    def test_runs_to_completion_and_reports_the_folder(self):
        jobs = ExportJobs(runner=lambda target: target())
        job_id = jobs.start(lambda: Library(self.path), ["FIGURE:a"], ExportOptions(pause_seconds=0),
                            directory=Path(self.temp.name) / "exports" / "x", fetch=all_images)
        status = jobs.status(job_id)
        self.assertEqual(status["state"], "done")
        self.assertEqual((status["progress"]["items_done"], status["progress"]["files_ok"]), (1, 1))
        self.assertTrue(status["directory"].endswith("x"))
        self.assertNotIn("stop", status)

    def test_only_one_running_job_and_cancel(self):
        pending = []
        jobs = ExportJobs(runner=pending.append)
        job_id = jobs.start(lambda: Library(self.path), ["FIGURE:a"], ExportOptions(pause_seconds=0),
                            directory=Path(self.temp.name) / "exports" / "y", fetch=all_images)
        with self.assertRaisesRegex(ExportError, "진행 중"):
            jobs.start(lambda: Library(self.path), ["FIGURE:a"], ExportOptions())
        self.assertTrue(jobs.cancel(job_id))
        pending[0]()
        self.assertEqual(jobs.status(job_id)["state"], "cancelled")
        self.assertFalse(jobs.cancel(job_id))
        self.assertIsNone(jobs.status("missing"))

    def test_a_failing_export_is_reported(self):
        jobs = ExportJobs(runner=lambda target: target())
        job_id = jobs.start(lambda: Library(self.path), ["FIGURE:none"], ExportOptions(pause_seconds=0),
                            directory=Path(self.temp.name) / "exports" / "z")
        self.assertEqual(jobs.status(job_id)["state"], "failed")
        self.assertIn("로컬 DB", jobs.status(job_id)["error"])


class LibraryExportRouteTests(unittest.TestCase):
    def setUp(self):
        from subculture.web.app import app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.old = {k: app.config.get(k) for k in ("LIBRARY_PATH", "LIBRARY_CLOUD_DB", "TESTING")}
        self.addCleanup(lambda: app.config.update(self.old))
        app.config.update(
            TESTING=True, LIBRARY_PATH=self.path,
            LIBRARY_CLOUD_DB=Mock(side_effect=AssertionError("offline")),
        )
        self.client = app.test_client()
        self.lib = Library(self.path)
        self.lib.sync(cloud(snapshot("a", imageUrl="https://cdn.example.com/x.jpg")))

    def export_client(self):
        from unittest.mock import patch
        from subculture.library.interface import routes
        jobs = ExportJobs(runner=lambda target: target())
        patches = [
            patch.object(routes, "export_jobs", jobs),
            patch("subculture.library.application.export_images._download",
                  side_effect=lambda url, *, timeout: (JPEG, "image/jpeg")),
            patch.dict(os.environ, {"FIGURE_PROJECT_DIR": self.temp.name}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return jobs

    def test_popup_is_separate_from_the_bulk_bar(self):
        html = self.client.get("/library").get_data(as_text=True)
        self.assertIn('id="image-export-dialog"', html)
        self.assertIn('data-dialog-target="image-export-dialog"', html)
        bulk = html.split('id="library-bulk"', 1)[1].split("</form>", 1)[0]
        self.assertNotIn("이미지", bulk)
        self.assertIn("/library/export-images/jobs", html)

    def test_filter_scope_exports_everything_without_zip(self):
        self.lib.sync(cloud(*[
            snapshot(f"n{i}", imageUrl=f"https://cdn.example.com/n{i}.jpg") for i in range(60)
        ]))  # more than one 50-item page
        self.export_client()
        response = self.client.post("/library/export-images/jobs", data={
            "scope": "filter", "pause": "0", "include_main": "1", "include_detail": "1", "skip_downloaded": "1",
        })
        self.assertEqual(response.status_code, 200)
        job = response.get_json()
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["progress"]["items_total"], 61)
        status = self.client.get(f"/library/export-images/jobs/{job['id']}").get_json()
        self.assertEqual(status["progress"]["files_ok"], 61)
        exports = Path(self.temp.name) / "exports"
        self.assertEqual(len(list(exports.glob("*/index.json"))), 1)
        self.assertEqual(list(exports.glob("*.zip")), [])

    def test_selected_scope_and_limits(self):
        self.export_client()
        job = self.client.post("/library/export-images/jobs", data={
            "scope": "selected", "item_ids": ["FIGURE:a"], "pause": "0", "include_main": "1",
            "max_items": "1", "max_images": "1", "max_total_mb": "5",
        }).get_json()
        self.assertEqual((job["progress"]["items_total"], job["progress"]["files_ok"]), (1, 1))
        meta = json.loads((Path(job["directory"]) / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["options"]["max_total_bytes"], 5 * 1024 * 1024)
        self.assertFalse(meta["options"]["skip_downloaded"])

    def test_bad_values_and_unknown_jobs(self):
        self.export_client()
        for data in ({"max_items": "0", "include_main": "1"}, {"max_items": "abc", "include_main": "1"},
                     {"pause": "11", "include_main": "1"}, {}):
            with self.subTest(data=data):
                response = self.client.post("/library/export-images/jobs", data={"scope": "filter", **data})
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.get_json()["error"])
        empty = self.client.post("/library/export-images/jobs", data={"scope": "selected", "include_main": "1"})
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(self.client.get("/library/export-images/jobs/nope").status_code, 404)
        self.assertEqual(self.client.post("/library/export-images/jobs/nope/cancel").status_code, 404)

if __name__ == "__main__":
    unittest.main()
