"""Offline shared-original storage and v4 export contract regression tests."""
import base64
import hashlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from subculture.library.application.export_images import ExportOptions, export_images, zip_export
from subculture.library.infrastructure.download_ledger import DownloadLedger
from subculture.library.infrastructure.image_store import ImageStore


class ImageStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {"FIGURE_PROJECT_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.fixture = json.loads((Path(__file__).parent / "fixtures/image-export-v4.json").read_text())
        self.body = base64.b64decode(self.fixture["image_base64"])
        self.entry = self.fixture["entry"]
        self.record = self.entry["files"][0]
        self.store = ImageStore(self.root / "images")
        self.library = Mock()
        self.library.items_by_id.return_value = {self.entry["id"]: {**self.entry, "_id": self.entry["id"]}}

    def export(self, name, fetch=None, **kwargs):
        return export_images(self.library, [self.entry["id"]], directory=self.root / name,
                             fetch=fetch or (lambda url, **kw: (self.body, "image/png")),
                             options=ExportOptions(pause_seconds=0, **kwargs))

    def test_writer_matches_contract_and_custom_out_uses_shared_root(self):
        root = self.export("custom/location")
        self.assertEqual(json.loads((root / "index.json").read_text()), [self.entry])
        self.assertEqual((self.root / "images" / self.record["path"]).read_bytes(), self.body)
        self.assertFalse(any(p.is_dir() for p in root.iterdir()))

    def test_reused_export_survives_removal_of_first_export_and_zip_is_independent(self):
        first = self.export("exports/first")
        no_fetch = Mock(side_effect=AssertionError("must reuse"))
        second = self.export("exports/second", no_fetch)
        shutil.rmtree(first)
        original = (second / "index.json").read_bytes()
        archive = zip_export(second)
        self.assertEqual((second / "index.json").read_bytes(), original)
        shutil.rmtree(self.root / "images")
        with zipfile.ZipFile(archive) as zf:
            record = json.loads(zf.read("index.json"))[0]["files"][0]
            self.assertEqual(record["storage"], "export")
            self.assertEqual(record["status"], "skipped")
            self.assertEqual(zf.read(record["path"]), self.body)
        no_fetch.assert_not_called()

    def test_content_dedup_and_concurrent_writers(self):
        def save(i):
            return ImageStore(self.store.root).save(f"https://cdn.example/{i}", self.body, "png")
        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(save, range(24)))
        self.assertEqual(len({r["path"] for r in records}), 1)
        self.assertEqual(len(list(self.store.root.rglob("*.png"))), 1)
        ledger = DownloadLedger(self.store.root)
        self.assertTrue(all(ledger.lookup(f"https://cdn.example/{i}") for i in range(24)))
        self.assertEqual(list(self.store.root.rglob(".image-*")), [])

    def test_no_skip_fetches_again_without_duplicate_original(self):
        self.export("exports/first")
        fetch = Mock(return_value=(self.body, "image/png"))
        self.export("exports/second", fetch, skip_downloaded=False)
        fetch.assert_called_once()
        self.assertEqual(len(list(self.store.root.rglob("*.png"))), 1)

    def test_old_export_ledger_is_ignored(self):
        old_ledger = DownloadLedger(self.root / "exports")
        old = old_ledger.root / "old/items/original.png"
        old.parent.mkdir(parents=True)
        old.write_bytes(self.body)
        old_ledger.record(self.record["url"], "old/items/original.png", sha256=self.record["sha256"],
                          size=len(self.body), image_format="png")
        fetch = Mock(return_value=(self.body, "image/png"))
        root = self.export("exports/new", fetch)
        fetch.assert_called_once()
        self.assertEqual(json.loads((root / "index.json").read_text())[0]["files"][0]["status"], "ok")
        self.assertTrue(old.is_file())

    def test_zip_rejects_non_v4_without_replacing_archive(self):
        root = self.export("exports/run")
        archive = zip_export(root)
        before = archive.read_bytes()
        for version in (1, 2, 3, 99, None):
            with self.subTest(version=version):
                (root / "export.json").write_text(json.dumps({"formatVersion": version}))
                with self.assertRaisesRegex(ValueError, "formatVersion 4"):
                    zip_export(root)
                self.assertEqual(archive.read_bytes(), before)

    def test_write_failure_cleans_temporary_and_does_not_record_url(self):
        with patch("subculture.library.infrastructure.image_store.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.store.save(self.record["url"], self.body, "png")
        self.assertIsNone(self.store.lookup(self.record["url"]))
        self.assertEqual(list(self.store.root.rglob(".image-*")), [])
        self.assertFalse(any(p.is_dir() for p in self.store.root.iterdir()))

    def test_failed_export_and_cancel_do_not_create_image_directories(self):
        root = self.export("exports/failure", Mock(side_effect=OSError("network")))
        self.assertFalse(self.store.root.exists())
        self.assertFalse(any(p.is_dir() for p in root.iterdir()))
        self.assertEqual(json.loads((root / "export.json").read_text())["errorCount"], 1)
        cancelled = export_images(self.library, [self.entry["id"]], directory=self.root / "cancelled",
                                  should_stop=lambda: True)
        self.assertFalse(self.store.root.exists())
        self.assertEqual(json.loads((cancelled / "index.json").read_text()), [])

    def test_failed_zip_preserves_existing_archive(self):
        root = self.export("exports/run")
        archive = zip_export(root)
        before = archive.read_bytes()
        (self.store.root / self.record["path"]).unlink()
        with self.assertRaises(FileNotFoundError):
            zip_export(root)
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(list(archive.parent.glob(".export-*")), [])

    def test_ledger_failure_does_not_cache_success(self):
        with patch.object(self.store.ledger, "_append", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.store.save(self.record["url"], self.body, "png")
        self.assertIsNone(self.store.lookup(self.record["url"]))

    def test_shared_ledger_cannot_escape_root(self):
        ledger = DownloadLedger(self.root / "images")
        outside = self.root / "outside.png"
        outside.write_bytes(self.body)
        ledger.record("url", "../outside.png", sha256=hashlib.sha256(self.body).hexdigest(),
                      size=len(self.body), image_format="png")
        self.assertIsNone(ledger.lookup("url"))
