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
    ExportError, export_images, resolve_item_ids, zip_export,
)
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
            directory=self.out, pause_seconds=0, fetch=fetch,
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
        self.assertEqual(meta["formatVersion"], 2)
        self.assertEqual((meta["itemCount"], meta["fileCount"], meta["okCount"]), (2, 3, 3))

    def test_extension_follows_content_not_headers(self):
        bodies = {
            "https://cdn.example.com/a/main.jpg": (PNG, "image/jpeg"),
            "https://cdn.example.com/a/d1.jpg": (HTML, "text/html"),
            "https://cdn.example.com/a/d2.png": (HTML, "image/png"),
        }
        root = export_images(
            self.lib, ["FIGURE:a"], directory=self.out, pause_seconds=0,
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
                self.lib, ["FIGURE:b"], pause_seconds=0,
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
            self.lib, ["FIGURE:b"], directory=self.out, pause_seconds=0,
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

    def test_bulk_bar_has_download_button_and_route_returns_zip(self):
        html = self.client.get("/library").get_data(as_text=True)
        self.assertIn("이미지 다운로드", html)
        self.assertIn("/library/export-images", html)

        def fetch(url, *, timeout):
            return JPEG, "image/jpeg"

        from unittest.mock import patch
        with patch(
            "subculture.library.application.export_images._download", side_effect=fetch,
        ), patch.dict(os.environ, {"FIGURE_PROJECT_DIR": self.temp.name}):
            response = self.client.post(
                "/library/export-images",
                data={"item_ids": ["FIGURE:a"], "next": "/library"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        self.assertTrue(response.data[:2] == b"PK")
        exports = Path(self.temp.name) / "exports"
        self.assertEqual(len(list(exports.glob("*/index.json"))), 1)
        self.assertEqual(len(list(exports.glob("*.zip"))), 1)


if __name__ == "__main__":
    unittest.main()
