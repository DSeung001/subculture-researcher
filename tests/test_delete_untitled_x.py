"""Offline tests for deleting leftover untitled X status posts."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from content_store import UNTITLED_TITLE, delete_untitled_x_contents, is_untitled_x_post
from local_library import Library


class UntitledXMatchTests(unittest.TestCase):
    def test_matches_only_x_status_with_placeholder_title(self):
        self.assertTrue(is_untitled_x_post(
            "https://x.com/animate_hongdae/status/123", UNTITLED_TITLE))
        self.assertTrue(is_untitled_x_post(
            "https://twitter.com/user/status/456", UNTITLED_TITLE))
        self.assertTrue(is_untitled_x_post(
            "https://www.x.com/user/status/789", UNTITLED_TITLE))

    def test_rejects_non_x_or_titled_posts(self):
        self.assertFalse(is_untitled_x_post(
            "https://laftel.net/item/1", UNTITLED_TITLE))
        self.assertFalse(is_untitled_x_post(
            "https://x.com/animate_hongdae", UNTITLED_TITLE))
        self.assertFalse(is_untitled_x_post(
            "https://x.com/user/status/1", "16시간"))
        self.assertFalse(is_untitled_x_post(
            "https://x.com/user/status/1", ""))
        self.assertFalse(is_untitled_x_post(
            "https://x.com/user/status/1", "본문 제목"))


def _snapshot(doc_id, category, url, title):
    ref = Mock()
    ref.parent.parent.id = category
    return SimpleNamespace(
        id=doc_id,
        reference=ref,
        to_dict=lambda: {"url": url, "title": title},
    )


class DeleteUntitledXFirestoreTests(unittest.TestCase):
    def test_deletes_only_matching_documents(self):
        keep = _snapshot(
            "keep", "GOODS", "https://x.com/user/status/1", "입고 안내")
        drop = _snapshot(
            "drop", "GOODS", "https://x.com/animate_hongdae/status/2", UNTITLED_TITLE)
        other = _snapshot(
            "other", "ANIME", "https://laftel.net/item/3", UNTITLED_TITLE)
        db = Mock()
        db.collection_group.return_value.stream.return_value = iter([keep, drop, other])

        result = delete_untitled_x_contents(db, dry_run=False)

        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["items"], [{
            "id": "GOODS:drop",
            "url": "https://x.com/animate_hongdae/status/2",
        }])
        drop.reference.delete.assert_called_once()
        keep.reference.delete.assert_not_called()
        other.reference.delete.assert_not_called()

    def test_dry_run_lists_without_deleting(self):
        drop = _snapshot(
            "drop", "GOODS", "https://twitter.com/u/status/9", UNTITLED_TITLE)
        db = Mock()
        db.collection_group.return_value.stream.return_value = iter([drop])

        result = delete_untitled_x_contents(db, dry_run=True)

        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["deleted"], 0)
        self.assertTrue(result["dry_run"])
        drop.reference.delete.assert_not_called()


class DeleteUntitledXLocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.lib = Library(self.path)

    def _insert(self, item_id, url, title, payload_title=None):
        from datetime import datetime, timezone
        from library_models import Item
        payload = {"title": payload_title if payload_title is not None else title, "url": url}
        with self.lib.connect() as session:
            session.add(Item(
                id=item_id,
                title=title,
                url=url,
                source="animate 서울홍대점",
                payload=json.dumps(payload, ensure_ascii=False),
                deadline=None,
                synced_at=datetime.now(timezone.utc).isoformat(),
            ))

    def test_deletes_matching_local_rows_and_cascades_links(self):
        self._insert("GOODS:x1", "https://x.com/u/status/1", UNTITLED_TITLE)
        self._insert("GOODS:x2", "https://x.com/u/status/2", "실제 제목")
        self._insert("ANIME:l1", "https://laftel.net/a", UNTITLED_TITLE)
        work = self.lib.save_term("works", "테스트")
        self.lib.assign(["GOODS:x1", "GOODS:x2"], "works", work)

        result = self.lib.delete_untitled_x(dry_run=False)

        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["deleted"], 1)
        ids = {row["id"] for row in self.lib.items({})[0]}
        self.assertEqual(ids, {"GOODS:x2", "ANIME:l1"})
        self.assertEqual(self.lib.items({"works": work})[1], 1)

    def test_dry_run_keeps_rows(self):
        self._insert("GOODS:x1", "https://x.com/u/status/1", UNTITLED_TITLE)
        result = self.lib.delete_untitled_x(dry_run=True)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(self.lib.items({})[1], 1)

    def test_matches_payload_title_when_display_title_differs(self):
        self._insert(
            "GOODS:x1",
            "https://x.com/u/status/1",
            "표시용",
            payload_title=UNTITLED_TITLE,
        )
        result = self.lib.delete_untitled_x(dry_run=True)
        self.assertEqual(result["matched"], 1)


if __name__ == "__main__":
    unittest.main()
