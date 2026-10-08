"""Comparison post for X: text rules and the session-only page (offline, nothing stored)."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

from subculture.shared.compare_post import MAX_SOURCES, build_compare_posts, post_length, short_product_name
from subculture.shared.content_model import content_ref
from subculture.web import app as review

CLIENT = Client(project="offline-tests", credentials=AnonymousCredentials())
FIGURE_A = {
    "title": "[예약] 굿스마일 넨도로이드 프리렌 [한정판]", "url": "https://shop.example.com/a", "source": "헤로타임 최신예약",
    "entityType": "PRODUCT", "shop": "헤로타임", "manufacturer": "굿스마일", "saleStatus": "PREORDER",
    "price": 62000, "currency": "KRW", "category": "FIGURE",
}
FIGURE_B = {
    "title": "ねんどろいど フリーレン", "titleKo": "넨도로이드 프리렌", "url": "https://store.example.com/b",
    "source": "코믹스아트 신작", "entityType": "PRODUCT", "shop": "코믹스아트", "saleStatus": "IN_STOCK",
    "price": 58000, "currency": "KRW", "category": "FIGURE",
}
NEWS = {"title": "프리렌 2기 굿즈 발표", "url": "https://news.example.com/n", "source": "애니플러스 뉴스", "category": "ANIME"}


class ComparePostTests(unittest.TestCase):
    def test_short_name_drops_bracket_tags_and_shop_and_maker_names(self):
        self.assertEqual(short_product_name(FIGURE_A), "넨도로이드 프리렌")
        self.assertEqual(short_product_name(FIGURE_B), "넨도로이드 프리렌")
        self.assertEqual(short_product_name({"title": "[예약]"}), "[예약]")
        self.assertEqual(short_product_name({}), "(제목 없음)")

    def test_body_lists_numbered_facts_without_links(self):
        posts = build_compare_posts([FIGURE_A, FIGURE_B])
        self.assertEqual(posts.body, (
            "1. 넨도로이드 프리렌\n"
            "   헤로타임 · 예약중 · 62,000원 · 굿스마일\n"
            "2. 넨도로이드 프리렌\n"
            "   코믹스아트 · 판매중 · 58,000원\n"
        ))
        self.assertNotIn("http", posts.body)

    def test_reply_keeps_the_same_numbers_with_each_sources_own_link(self):
        posts = build_compare_posts([FIGURE_A, FIGURE_B])
        self.assertEqual(posts.reply, (
            "상품 페이지 참고 ↓\n\n"
            "1. 넨도로이드 프리렌\nhttps://shop.example.com/a\n\n"
            "2. 넨도로이드 프리렌\nhttps://store.example.com/b\n"
        ))

    def test_non_products_use_the_source_name_and_a_plain_header(self):
        posts = build_compare_posts([NEWS])
        self.assertEqual(posts.body, "1. 프리렌 2기 굿즈 발표\n   애니플러스 뉴스\n")
        self.assertTrue(posts.reply.startswith("링크 ↓\n\n1. 프리렌 2기 굿즈 발표\nhttps://news.example.com/n"))

    def test_unsafe_or_missing_links_are_left_out_of_the_reply(self):
        posts = build_compare_posts([{**FIGURE_A, "url": "javascript:alert(1)"}, {**FIGURE_B, "url": ""}])
        self.assertEqual(posts.reply, "")
        self.assertIn("2. 넨도로이드 프리렌", posts.body)

    def test_post_length_counts_a_link_as_23_characters(self):
        self.assertEqual(post_length("가 https://example.com/" + "x" * 80), 2 + 23)


class ComparePageTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.collection.side_effect = lambda name: CLIENT.collection(name)
        patcher = patch.object(review, "db", return_value=self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.old = review.app.config.get("TESTING")
        self.addCleanup(lambda: review.app.config.update(TESTING=self.old))
        review.app.config.update(TESTING=True)
        self.client = review.app.test_client()

    def snapshot(self, source_id, data, exists=True):
        ref = content_ref(CLIENT, source_id)
        return SimpleNamespace(id=ref.id, reference=ref, exists=exists, to_dict=lambda: dict(data))

    def post(self, ids):
        return self.client.post("/compare", data={"source_ids": ids, "next": "/inbox?days=7"})

    def test_page_shows_both_posts_in_the_ticked_order_and_writes_nothing(self):
        # get_all answers in its own order, with a document that no longer exists.
        self.db.get_all.return_value = [
            self.snapshot("FIGURE:b", FIGURE_B), self.snapshot("FIGURE:gone", {}, exists=False),
            self.snapshot("FIGURE:a", FIGURE_A),
        ]
        response = self.post(["FIGURE:a", "FIGURE:gone", "FIGURE:b", "FIGURE:a"])
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.db.get_all.call_args.args[0]), 3)  # the repeated id is read once
        self.assertIn("1. 넨도로이드 프리렌\n   헤로타임 · 예약중 · 62,000원 · 굿스마일\n2. 넨도로이드 프리렌", html)
        self.assertIn("1. 넨도로이드 프리렌\nhttps://shop.example.com/a\n\n2. 넨도로이드 프리렌\nhttps://store.example.com/b", html)
        self.assertIn('data-copy-target="post-body"', html)
        self.assertIn('data-copy-target="post-reply"', html)
        self.assertIn('data-x-post-target="post-body"', html)
        self.assertIn('href="/inbox?days=7"', html)
        self.assertNotIn("<form", html)  # nothing to save
        for call in self.db.mock_calls:
            self.assertNotIn(call[0].split(".")[-1], ("set", "update", "add", "delete", "batch"), call)

    def test_json_preserves_order_deduplicates_and_reports_missing_without_writes(self):
        self.db.get_all.return_value = [self.snapshot("FIGURE:b", FIGURE_B), self.snapshot("FIGURE:a", FIGURE_A)]
        response = self.client.post("/compare", data={"source_ids": ["FIGURE:a", "FIGURE:gone", "FIGURE:b", "FIGURE:a"]}, headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual((result["count"], result["missingCount"]), (2, 1))
        self.assertEqual(result["body"], build_compare_posts([FIGURE_A, FIGURE_B]).body)
        self.assertEqual(result["reply"], build_compare_posts([FIGURE_A, FIGURE_B]).reply)
        self.assertNotIn("Set-Cookie", response.headers)
        for call in self.db.mock_calls:
            self.assertNotIn(call[0].split(".")[-1], ("set", "update", "add", "delete", "batch"))

    def test_json_errors_do_not_flash_or_create_session(self):
        for ids in ([], ["bad"], [f"FIGURE:{n}" for n in range(MAX_SOURCES + 1)], ["FIGURE:gone"]):
            self.db.get_all.return_value = []
            response = self.client.post("/compare", data={"source_ids": ids}, headers={"Accept": "application/json"})
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.get_json()["error"])
            self.assertNotIn("Set-Cookie", response.headers)

    def test_bad_requests_go_back_to_the_list_with_a_message(self):
        cases = {
            "항목을 선택해주세요.": [],
            "잘못된 항목 ID입니다.": ["FIGURE"],
            f"비교글 재료는 {MAX_SOURCES}개까지입니다.": [f"FIGURE:{n}" for n in range(MAX_SOURCES + 1)],
        }
        for message, ids in cases.items():
            with self.subTest(message=message):
                response = self.post(ids)
                self.assertEqual(response.headers["Location"], "/inbox?days=7")
                with self.client.session_transaction() as session:
                    self.assertIn(("error", message), session.pop("_flashes"))
        self.db.get_all.assert_not_called()

    def test_items_that_no_longer_exist_go_back_with_a_message(self):
        self.db.get_all.return_value = [self.snapshot("FIGURE:gone", {}, exists=False)]
        response = self.post(["FIGURE:gone"])
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertIn(("error", "선택한 항목을 찾을 수 없습니다."), session["_flashes"])


if __name__ == "__main__":
    unittest.main()
