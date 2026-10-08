"""The item card: one view model for the inbox and the static site, and the inbox markup."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

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


def first_card(html):
    return BeautifulSoup(html, "html.parser").select_one("article.item-card")


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

    def test_card_renders_product_data_and_photo(self):
        card = first_card(self.inbox(snapshot()))
        image = card.select_one("img")
        self.assertEqual(image["src"], DOC["imageUrl"])
        self.assertEqual(image["referrerpolicy"], "no-referrer")
        text = card.get_text(" ", strip=True)
        for value in (DOC["title"], "따빼몰 · 예약중 · 269,000원", DOC["summary"]):
            self.assertIn(value, text)
        self.assertNotIn("(마감 지남)", text)

    def test_card_forms_preserve_storage_id_after_category_edit(self):
        html = self.inbox(snapshot(category="GOODS"))
        page = BeautifulSoup(html, "html.parser")
        card = page.select_one("article.item-card")
        for action in ("status", "note"):
            self.assertIsNotNone(page.select_one(f'form[action="/items/FIGURE/abc/{action}"]'))
        checkbox = card.select_one('input[name="source_ids"]')
        self.assertEqual(checkbox["value"], "FIGURE:abc")
        form = page.find("form", id=checkbox["form"])
        self.assertEqual((form["method"].lower(), form["action"]), ("post", "/compare"))

    def test_detail_images_are_rendered(self):
        urls = ["https://cdn.example.com/p/1-detail-1.jpg", "https://cdn.example.com/p/1-detail-2.jpg"]
        card = first_card(self.inbox(snapshot(detailImageUrls=urls)))
        self.assertEqual([image["src"] for image in card.select("img")], [DOC["imageUrl"], *urls])

    def test_item_without_detail_images_only_renders_main_photo(self):
        card = first_card(self.inbox(snapshot()))
        self.assertEqual([image["src"] for image in card.select("img")], [DOC["imageUrl"]])

    def test_item_without_a_photo_shows_the_category_placeholder(self):
        card = first_card(self.inbox(snapshot(imageUrl=None)))
        self.assertEqual(card.select("img"), [])
        self.assertIn("피규어", card.get_text())

    def test_unsafe_image_and_link_are_not_rendered(self):
        card = first_card(self.inbox(snapshot(imageUrl="javascript:alert(1)", url="javascript:alert(1)")))
        self.assertEqual(card.select("img"), [])
        self.assertFalse(any(node.get(attr, "").startswith("javascript:")
                             for node in card.find_all(True) for attr in ("href", "src")))

    def test_elapsed_preorder_deadline_is_flagged(self):
        old = snapshot(preorderEndAt=(NOW - timedelta(days=30)).date().isoformat())
        self.assertIn("(마감 지남)", first_card(self.inbox(old)).get_text())

    def test_root_redirect_and_removed_routes(self):
        self.assertEqual(self.client.get("/").headers["Location"], "/inbox")
        for gone in ("/library", "/drafts", "/erd", "/sources/samples?name=x"):
            self.assertEqual(self.client.get(gone).status_code, 404, gone)


if __name__ == "__main__":
    unittest.main()
