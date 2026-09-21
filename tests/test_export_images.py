"""Offline checks for bulk image export (files + index.json, no real HTTP)."""

import json
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
            "https://cdn.example.com/a/main.jpg": (b"MAIN", "image/jpeg"),
            "https://cdn.example.com/a/d1.jpg": (b"D1", "image/jpeg"),
            "https://cdn.example.com/a/d2.png": (b"D2", "image/png"),
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
        self.assertEqual((root / entry["files"][0]["path"]).read_bytes(), b"MAIN")
        self.assertTrue(entry["files"][2]["path"].endswith(".png"))
        self.assertEqual(index[1]["files"], [])

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
            return b"IMG", "image/jpeg"

        from unittest.mock import patch
        with patch(
            "subculture.library.application.export_images._download", side_effect=fetch,
        ), patch(
            "subculture.library.interface.routes.LOCAL_DIR", Path(self.temp.name),
        ):
            response = self.client.post(
                "/library/export-images",
                data={"item_ids": ["FIGURE:a"], "next": "/library"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        self.assertTrue(response.data[:2] == b"PK")


if __name__ == "__main__":
    unittest.main()
