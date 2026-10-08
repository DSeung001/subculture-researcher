"""Offline tests for deleting leftover untitled X status posts."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from subculture.shared.untitled_content import UNTITLED_TITLE, is_untitled_x_post
from subculture.collection.application.untitled_cleanup import delete_untitled_x_contents


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


if __name__ == "__main__":
    unittest.main()
