"""The inbox and the local library must render one and the same item card."""

import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

import app as review
from content_model import content_ref
from local_library import Library, json_default
from presentation import card_view

NOW = datetime.now(timezone.utc)
DOC = {
    "title": "붕괴 스타레일 스파키 1/7 피규어", "titleKo": "", "url": "https://shop.example.com/p/1",
    "imageUrl": "https://cdn.example.com/p/1.jpg", "source": "따빼몰 호요버스 굿즈", "category": "FIGURE",
    "contentAngle": "PRICE", "sourceTier": "MEDIA", "status": "NEW", "region": "KR",
    "entityType": "PRODUCT", "shop": "따빼몰", "saleStatus": "PREORDER", "price": 269000, "currency": "KRW",
    "preorderEndAt": "2999-10-12", "summary": "예약 접수 중", "collectedAt": NOW, "postedAt": None,
}
CLIENT = Client(project="offline-tests", credentials=AnonymousCredentials())


def snapshot(source_id="FIGURE:abc", **fields):
    ref = content_ref(CLIENT, source_id)
    return SimpleNamespace(id=ref.id, reference=ref, exists=True, to_dict=lambda: {**DOC, **fields})


def classes(html):
    """Class names of the card's building blocks, in document order, as a structure fingerprint."""
    return re.findall(r'class="(card item-card|card-row|card-thumb(?: card-thumb-empty)?|card-main|card-title|'
                      r'card-meta-row|card-meta|card-summary)"', html)


def first_card(html):
    return re.search(r'<article class="card item-card">.*?</article>', html, re.S).group(0)


class CardViewTests(unittest.TestCase):
    def test_firestore_document_and_its_json_payload_give_the_same_card(self):
        payload = json.loads(json.dumps(DOC, default=json_default))
        self.assertEqual(card_view(DOC), card_view(payload))
        self.assertTrue(card_view(payload)["is_new_today"])
        self.assertIn("게시", card_view({**payload, "publishedAt": "2026-09-01"})["meta"])

    def test_unsafe_links_never_reach_the_card(self):
        view = card_view({**DOC, "url": "javascript:alert(1)", "imageUrl": "data:image/png;base64,AAAA"})
        self.assertEqual((view["url"], view["image_url"]), ("", ""))

    def test_translated_title_keeps_the_original_toggle(self):
        view = card_view({**DOC, "title": "原題", "titleKo": "번역 제목", "sourceLanguage": "ja"})
        self.assertEqual((view["title_text"], view["original_text"], view["lang_tag"]), ("번역 제목", "原題", "JA"))


class SharedCardRenderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.old = {k: review.app.config.get(k) for k in ("LIBRARY_PATH", "LIBRARY_CLOUD_DB", "TESTING")}
        self.addCleanup(lambda: review.app.config.update(self.old))
        review.app.config.update(TESTING=True, LIBRARY_PATH=self.path, LIBRARY_CLOUD_DB=Mock())
        self.client = review.app.test_client()

    def inbox(self, *snapshots):
        with patch.object(review, "fetch_contents_page", return_value=(list(snapshots), False, "")):
            return self.client.get("/").get_data(as_text=True)

    def library(self, *snapshots, url="/library"):
        db = Mock()
        db.collection_group.return_value.stream.return_value = iter(snapshots)
        Library(self.path).sync(db)
        return self.client.get(url).get_data(as_text=True)

    def test_inbox_and_library_render_the_same_card_markup(self):
        inbox = first_card(self.inbox(snapshot()))
        library = first_card(self.library(snapshot()))
        self.assertEqual(classes(inbox), classes(library))
        for html in (inbox, library):
            self.assertIn('<img class="card-thumb-img" src="https://cdn.example.com/p/1.jpg"', html)
            self.assertIn('referrerpolicy="no-referrer"', html)
            self.assertIn("붕괴 스타레일 스파키 1/7 피규어", html)
            self.assertIn("자세히보기", html)
            self.assertIn("따빼몰 · 예약중 · 269,000원", html)
            self.assertIn("예약 접수 중", html)
            self.assertNotIn("(마감 지남)", html)

    def test_only_the_page_specific_controls_differ(self):
        inbox = first_card(self.inbox(snapshot()))
        library = first_card(self.library(snapshot()))
        self.assertIn('name="source_ids"', inbox)        # draft selection + status buttons: inbox
        self.assertIn("/items/FIGURE/abc/status", inbox)
        self.assertNotIn("library-item-select", inbox)
        self.assertIn("library-item-select", library)    # bulk selection: library
        self.assertNotIn("/items/FIGURE/abc/status", library)
        self.assertNotIn('name="source_ids"', library)

    def test_item_without_a_photo_shows_the_category_placeholder_in_both(self):
        for html in (first_card(self.inbox(snapshot(imageUrl=None))),
                     first_card(self.library(snapshot(imageUrl=None), url="/library?q=%EC%8A%A4"))):
            self.assertIn("card-thumb card-thumb-empty", html)
            self.assertNotIn("<img", html)
            self.assertIn("피규어", html)

    def test_unsafe_image_and_link_are_not_rendered_in_either_list(self):
        bad = snapshot(imageUrl="javascript:alert(1)", url="javascript:alert(1)")
        for html in (self.inbox(bad), self.library(bad)):
            self.assertNotIn('src="javascript:', html)
            self.assertNotIn('href="javascript:', html)

    def test_elapsed_preorder_deadline_is_flagged_in_both(self):
        old = snapshot(preorderEndAt=(NOW - timedelta(days=30)).date().isoformat())
        for html in (first_card(self.inbox(old)), first_card(self.library(old))):
            self.assertIn("(마감 지남)", html)

    def test_work_edit_page_uses_the_same_card_with_an_unlink_action(self):
        lib = Library(self.path)
        db = Mock()
        db.collection_group.return_value.stream.return_value = iter([snapshot()])
        lib.sync(db)
        work = lib.save_term("works", "붕괴 스타레일", aliases="붕괴 스타레일")
        lib.auto_assign_works()
        html = self.client.get(f"/library/works/{work}").get_data(as_text=True)
        card = first_card(html)
        self.assertEqual(classes(card), classes(first_card(self.inbox(snapshot()))))
        self.assertIn('name="action" value="unlink"', card)
        self.assertIn("card-thumb-img", card)


if __name__ == "__main__":
    unittest.main()
