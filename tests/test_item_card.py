"""The item card: one view model for the inbox and the static site, and the inbox markup."""

import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

from subculture.web import app as review
from subculture.shared.content_model import content_ref
from subculture.shared.presentation import card_view
from subculture.web import site_builder

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
    return re.findall(r'class="(card item-card|card-row|card-thumb-col|card-thumb(?: card-thumb-empty)?|'
                      r'card-detail-thumbs|card-main|card-title|'
                      r'card-meta-row|card-meta|card-summary)"', html)


def first_card(html):
    return re.search(r'<article class="card item-card">.*?</article>', html, re.S).group(0)


class CardViewTests(unittest.TestCase):
    def test_static_site_card_is_the_inbox_card_view_as_json(self):
        view = json.loads(json.dumps(site_builder.site_item("FIGURE:abc", DOC, [])["view"]))
        expected = card_view(DOC)
        expected["score_breakdown"] = [list(pair) for pair in expected["score_breakdown"]]
        self.assertEqual(view, expected)
        self.assertTrue(view["is_new_today"])
        self.assertIn("게시", card_view({**DOC, "publishedAt": "2026-09-01"})["meta"])

    def test_unsafe_links_never_reach_the_card(self):
        view = card_view({**DOC, "url": "javascript:alert(1)", "imageUrl": "data:image/png;base64,AAAA"})
        self.assertEqual((view["url"], view["image_url"]), ("", ""))

    def test_translated_title_keeps_the_original_toggle(self):
        view = card_view({**DOC, "title": "原題", "titleKo": "번역 제목", "sourceLanguage": "ja"})
        self.assertEqual((view["title_text"], view["original_text"], view["lang_tag"]), ("번역 제목", "原題", "JA"))

    def test_detail_image_urls_are_cleaned_and_unsafe_ones_dropped(self):
        view = card_view({**DOC, "detailImageUrls": [
            "https://cdn.example.com/p/1-detail-1.jpg",
            "javascript:alert(1)",
            "https://cdn.example.com/p/1-detail-2.jpg",
        ]})
        self.assertEqual(view["detail_image_urls"], [
            "https://cdn.example.com/p/1-detail-1.jpg", "https://cdn.example.com/p/1-detail-2.jpg",
        ])

    def test_stored_template_placeholders_are_not_shown_as_detail_images(self):
        view = card_view({**DOC, "detailImageUrls": [
            "https://ttabbaemall.co.kr/product/%7B%24js-src%7D",
            "https://ttabbaemall.co.kr/web/upload/NNEditor/20240822/a.jpg",
        ]})
        self.assertEqual(view["detail_image_urls"], ["https://ttabbaemall.co.kr/web/upload/NNEditor/20240822/a.jpg"])

    def test_missing_detail_image_urls_give_an_empty_list(self):
        self.assertEqual(card_view(DOC)["detail_image_urls"], [])


class InboxCardRenderingTests(unittest.TestCase):
    def setUp(self):
        self.old = review.app.config.get("TESTING")
        self.addCleanup(lambda: review.app.config.update(TESTING=self.old))
        review.app.config.update(TESTING=True)
        self.client = review.app.test_client()

    def inbox(self, *snapshots):
        with patch.object(review, "fetch_contents_page", return_value=(list(snapshots), False, "")), \
                patch.object(review, "fetch_recommended_items", return_value=[]):
            return self.client.get("/inbox").get_data(as_text=True)

    def test_card_markup(self):
        card = first_card(self.inbox(snapshot()))
        self.assertEqual(classes(card), [
            "card item-card", "card-row", "card-thumb-col", "card-thumb", "card-main", "card-title",
            "card-meta-row", "card-meta", "card-summary", "card-summary",
        ])
        self.assertIn('<img class="card-thumb-img" src="https://cdn.example.com/p/1.jpg"', card)
        self.assertIn('referrerpolicy="no-referrer"', card)
        self.assertIn("붕괴 스타레일 스파키 1/7 피규어", card)
        self.assertIn("자세히보기", card)
        self.assertIn("따빼몰 · 예약중 · 269,000원", card)
        self.assertIn("예약 접수 중", card)
        self.assertNotIn("(마감 지남)", card)

    def test_card_has_status_buttons_and_no_draft_selection(self):
        card = first_card(self.inbox(snapshot()))
        self.assertIn("/items/FIGURE/abc/status", card)
        self.assertNotIn('name="source_ids"', card)
        self.assertNotIn("card-select", card)

    def test_detail_images_show_next_to_the_main_thumbnail(self):
        card = first_card(self.inbox(snapshot(detailImageUrls=[
            "https://cdn.example.com/p/1-detail-1.jpg", "https://cdn.example.com/p/1-detail-2.jpg",
        ])))
        self.assertIn('class="card-detail-thumbs"', card)
        self.assertIn('src="https://cdn.example.com/p/1-detail-1.jpg"', card)
        self.assertIn('src="https://cdn.example.com/p/1-detail-2.jpg"', card)

    def test_item_without_detail_images_shows_no_detail_strip(self):
        self.assertNotIn("card-detail-thumbs", first_card(self.inbox(snapshot())))

    def test_item_without_a_photo_shows_the_category_placeholder(self):
        card = first_card(self.inbox(snapshot(imageUrl=None)))
        self.assertIn("card-thumb card-thumb-empty", card)
        self.assertNotIn("<img", card)
        self.assertIn("피규어", card)

    def test_unsafe_image_and_link_are_not_rendered(self):
        html = self.inbox(snapshot(imageUrl="javascript:alert(1)", url="javascript:alert(1)"))
        self.assertNotIn('src="javascript:', html)
        self.assertNotIn('href="javascript:', html)

    def test_elapsed_preorder_deadline_is_flagged(self):
        old = snapshot(preorderEndAt=(NOW - timedelta(days=30)).date().isoformat())
        self.assertIn("(마감 지남)", first_card(self.inbox(old)))

    def test_nav_links_only_to_the_remaining_screens(self):
        html = self.inbox(snapshot())
        self.assertIn('href="/sources"', html)
        for gone in ("/library", "/drafts", "/erd"):
            self.assertNotIn(f'href="{gone}', html)
        self.assertEqual(self.client.get("/").headers["Location"], "/inbox")
        for gone in ("/library", "/drafts", "/erd", "/sources/samples?name=x"):
            self.assertEqual(self.client.get(gone).status_code, 404, gone)


if __name__ == "__main__":
    unittest.main()
