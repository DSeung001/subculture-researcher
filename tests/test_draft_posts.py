"""Offline checks for the two posts of a draft: the content post and the link reply."""

import unittest

from subculture.drafts.domain.posts import (
    BODY_TARGET, URL_LENGTH, DraftPosts, build_reply, post_length, reply_header, short_product_name,
)
from subculture.drafts.domain.rules import build_posts


def product(title, url="https://shop.example.com/1", **fields):
    return {"title": title, "url": url, "entityType": "PRODUCT", **fields}


class ShortProductNameTests(unittest.TestCase):
    def test_shop_tags_at_either_end_are_removed(self):
        self.assertEqual(short_product_name(product("[예약] 엘렌 조 피규어")), "엘렌 조 피규어")
        self.assertEqual(short_product_name(product("【특전】[예약] 엘렌 조 피규어 [재입고]")), "엘렌 조 피규어")

    def test_the_maker_and_shop_names_are_removed_when_known(self):
        item = product("굿스마일컴퍼니 호시미 미야비 피규어 - 따빼몰", manufacturer="굿스마일컴퍼니", shop="따빼몰")
        self.assertEqual(short_product_name(item), "호시미 미야비 피규어")

    def test_the_korean_title_wins_and_an_empty_result_falls_back_to_the_title(self):
        self.assertEqual(short_product_name(product("Ellen Joe", titleKo="엘렌 조")), "엘렌 조")
        self.assertEqual(short_product_name(product("[예약]")), "[예약]")

    def test_brackets_inside_the_name_stay(self):
        self.assertEqual(short_product_name(product("넨도로이드 [아리아] 피규어")), "넨도로이드 [아리아] 피규어")


class ReplyTests(unittest.TestCase):
    def test_header_depends_on_whether_any_source_is_a_product(self):
        self.assertEqual(reply_header([product("a")]), "상품 페이지 참고 ↓")
        self.assertEqual(reply_header([{"title": "소식"}, product("a")]), "상품 페이지 참고 ↓")
        self.assertEqual(reply_header([{"title": "소식"}]), "링크 ↓")

    def test_reply_is_a_header_and_a_name_url_pair_per_source_in_order(self):
        items = [product("[예약] 엘렌 조", "https://shop.example.com/1"),
                 product("미야비", "https://shop.example.com/2")]
        self.assertEqual(
            build_reply(items, {1: "호시미 미야비"}),
            "상품 페이지 참고 ↓\n\n엘렌 조\nhttps://shop.example.com/1\n\n호시미 미야비\nhttps://shop.example.com/2\n",
        )

    def test_a_source_without_a_usable_link_is_skipped_and_none_gives_an_empty_reply(self):
        items = [product("링크 없음", url=""), product("위험", url="javascript:alert(1)"),
                 product("정상", "https://shop.example.com/3")]
        self.assertEqual(build_reply(items), "상품 페이지 참고 ↓\n\n정상\nhttps://shop.example.com/3\n")
        self.assertEqual(build_reply(items[:2]), "")

    def test_names_are_flattened_and_stripped_of_links(self):
        items = [product("원본", "https://shop.example.com/1")]
        reply = build_reply(items, {0: "새\n이름 https://evil.example.com/x"})
        self.assertEqual(reply, "상품 페이지 참고 ↓\n\n새 이름\nhttps://shop.example.com/1\n")


class LengthTests(unittest.TestCase):
    def test_every_link_counts_as_23_characters(self):
        text = "상품 페이지 참고 ↓\nhttps://shop.example.com/a/very/long/path?with=query&and=more"
        self.assertEqual(post_length(text), len("상품 페이지 참고 ↓\n") + URL_LENGTH)
        self.assertEqual(post_length("링크 http://a.co 그리고 https://b.co"), len("링크  그리고 ") + 2 * URL_LENGTH)

    def test_plain_text_is_counted_by_characters(self):
        self.assertEqual(post_length("한글 열 글자입니다 ok"), 13)
        self.assertEqual(BODY_TARGET, 260)


class BuildPostsTests(unittest.TestCase):
    def test_the_quick_draft_keeps_links_out_of_the_body(self):
        items = [
            {"title": "엘렌 조", "titleKo": "엘렌 조 피규어", "url": "https://shop.example.com/1",
             "source": "따빼몰", "summary": "요약", "note": "확인 필요", "entityType": "PRODUCT"},
        ]
        posts = build_posts(items, "NEWS")
        self.assertIsInstance(posts, DraftPosts)
        self.assertIn("엘렌 조 피규어", posts.body)
        self.assertIn("메모: 확인 필요", posts.body)
        self.assertNotIn("https://", posts.body)
        self.assertEqual(posts.reply, "상품 페이지 참고 ↓\n\n엘렌 조 피규어\nhttps://shop.example.com/1\n")


if __name__ == "__main__":
    unittest.main()
