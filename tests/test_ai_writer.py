"""Offline checks for AI write-prompt assembly and reply building (no Gemini / network)."""

import json
import unittest
from unittest.mock import patch

from subculture.drafts.infrastructure import ai_writer


def product(name, url, **fields):
    return {"title": name, "titleKo": name, "url": url, "category": "FIGURE",
            "entityType": "PRODUCT", "shop": "피규어팜", **fields}


def model_json(post1="본문 글 #피규어", *names):
    return json.dumps({
        "post1": post1,
        "products": [{"index": index, "display_name": name} for index, name in names],
    }, ensure_ascii=False)


def write(items, response):
    with patch.object(ai_writer, "api_key", return_value="fake-key"), patch.object(
        ai_writer, "_call_gemini", return_value=response
    ) as call:
        posts = ai_writer.write_draft_posts(items, "COMPARE")
    return posts, call


class AiWriterPromptTests(unittest.TestCase):
    def test_material_block_has_no_anime_airing_or_popularity_hints(self):
        material = ai_writer._material_block(
            [
                {
                    "title": "테스트 애니",
                    "source": "애니 소식",
                    "trending": 1200,
                    "popularity": 50000,
                    "episode": 5,
                    "nextAiringAt": "2026-09-20T12:00:00+00:00",
                    "category": "ANIME",
                }
            ]
        )
        self.assertNotIn("분위기:", material)
        self.assertNotIn("방영:", material)
        self.assertIn("출처: 애니 소식", material)

    def test_selection_block_has_no_anilist_metrics(self):
        block = ai_writer._selection_block([{"title": "작품", "trending": 100, "popularity": 5}])
        self.assertNotIn("AniList", block)
        self.assertNotIn("트렌딩", block)

    def test_material_block_keeps_shop_source(self):
        material = ai_writer._material_block(
            [
                {
                    "title": "피규어",
                    "source": "피규어팜 예약상품",
                    "category": "FIGURE",
                    "entityType": "PRODUCT",
                    "shop": "피규어팜",
                }
            ]
        )
        self.assertIn("출처: 피규어팜 예약상품", material)

    def test_material_block_never_carries_a_url(self):
        material = ai_writer._material_block([product("피규어", "https://shop.example.com/1")])
        self.assertNotIn("https://", material)

    def test_material_block_lists_linked_work_names(self):
        material = ai_writer._material_block([
            product("페른 피규어", "https://shop.example.com/1", _workNames=["프리렌", "장송의 프리렌"]),
            product("이름만 있는 피규어", "https://shop.example.com/2"),
            product("빈 목록", "https://shop.example.com/3", _workNames=[]),
            product("공백만", "https://shop.example.com/4", _workNames=["  ", ""]),
        ])
        self.assertIn("   작품: 프리렌, 장송의 프리렌", material)
        self.assertEqual(material.count("   작품:"), 1)

    def test_prompts_and_hints_no_longer_mention_anilist_or_anime(self):
        self.assertNotIn("ANIME", ai_writer.CATEGORY_HINTS)
        for template in (ai_writer.SELECT_PROMPT_TEMPLATE, ai_writer.PROMPT_TEMPLATE):
            self.assertNotIn("AniList", template)
            self.assertNotIn("트렌딩", template)

    def test_prompt_asks_for_a_link_free_post_varied_openings_and_preorder_vs_regular(self):
        prompt = ai_writer.PROMPT_TEMPLATE.format(
            angle="COMPARE", category_hint="힌트", body_target=260, material="1. 소재")
        self.assertIn("URL, 링크", prompt)
        self.assertIn("260자 이내", prompt)
        self.assertIn("[문장 다양성]", prompt)
        self.assertIn("[예약/일반 구분]", prompt)
        self.assertIn("판매유형", prompt)
        self.assertIn("display_name", prompt)

    def test_prompt_makes_the_account_a_curator_not_a_seller(self):
        prompt = ai_writer.PROMPT_TEMPLATE.format(
            angle="COMPARE", category_hint="힌트", body_target=260, material="1. 소재")
        self.assertIn("큐레이션 계정", prompt)
        self.assertIn("판매자가 아니라", prompt)
        self.assertIn("[정보 공유 계정]", prompt)
        for seller_phrase in ("구매하세요", "예약하세요", "특가", "서두르세요", "저희"):
            self.assertIn(seller_phrase, prompt)  # listed as forbidden phrases
        self.assertIn("실물을 본 것처럼 쓰지 마", prompt)
        # The preorder-vs-regular example must not sound like a shop either.
        self.assertNotIn("바로 구매 가능", prompt)
        for hint in ai_writer.CATEGORY_HINTS.values():
            self.assertNotIn("판매처", hint)

    def test_figure_hint_weaves_character_and_work_with_a_light_observation(self):
        hint = ai_writer.CATEGORY_HINTS["FIGURE"]
        self.assertIn("작품", hint)
        self.assertIn("캐릭터", hint)
        self.assertIn("가벼운 관찰", hint)
        self.assertIn("추측하지 마", hint)
        self.assertIn("가격·사이즈·발매", hint)

    def test_prompt_asks_for_casual_korean_speech(self):
        prompt = ai_writer.PROMPT_TEMPLATE.format(
            angle="COMPARE", category_hint="힌트", body_target=260, material="1. 소재")
        self.assertIn("반말", prompt)
        self.assertIn("구어체", prompt)
        self.assertIn("'합니다', '해요'체", prompt)


class SaleTypeTests(unittest.TestCase):
    def hint(self, **fields):
        return ai_writer._sale_type_hint({"entityType": "PRODUCT", **fields}, today="2026-09-20")

    def test_preorder_regular_and_sold_out_are_told_apart(self):
        self.assertEqual(self.hint(saleStatus="PREORDER"), "예약")
        self.assertEqual(self.hint(saleStatus="IN_STOCK"), "일반 판매(재고 있음)")
        self.assertEqual(self.hint(saleStatus="SOLD_OUT"), "품절")

    def test_preorder_keeps_its_deadline_and_arrival(self):
        hint = self.hint(saleStatus="PREORDER", preorderEndAt="2026-09-30", releaseWindowText="2027년 1월")
        self.assertEqual(hint, "예약 · 예약마감 2026-09-30 · 입고 2027년 1월")

    def test_an_elapsed_preorder_deadline_is_not_called_a_preorder(self):
        hint = self.hint(saleStatus="PREORDER", preorderEndAt="2026-09-01")
        self.assertTrue(hint.startswith("예약 마감 지남"), hint)
        self.assertNotIn("예약마감", hint)

    def test_unknown_status_and_non_products_give_no_hint(self):
        self.assertEqual(self.hint(), "")
        self.assertEqual(ai_writer._sale_type_hint({"saleStatus": "PREORDER"}), "")

    def test_material_block_gives_each_product_its_price_on_its_own_line(self):
        material = ai_writer._material_block([
            product("한국 피규어", "https://shop.example.com/1", price=72000),
            product("해외 피규어", "https://shop.example.com/2", price=30, currency="USD"),
            product("가격 모름", "https://shop.example.com/3"),
            {"title": "상품이 아님", "price": 5000},
        ])
        self.assertIn("   가격: 72,000원", material)
        self.assertIn("   가격: 30 USD", material)
        self.assertEqual(material.count("   가격:"), 2)  # no line where there is no price to state

    def test_prompt_requires_stated_prices_without_inventing_or_judging(self):
        prompt = ai_writer.PROMPT_TEMPLATE.format(
            angle="COMPARE", category_hint="힌트", body_target=260, material="1. 소재")
        self.assertIn("[가격 정보]", prompt)
        self.assertIn("가격을 빠뜨리지 마", prompt)
        self.assertIn("가격이 없는 소재의 가격은 언급하지 마", prompt)
        self.assertIn("가성비", prompt)  # listed as a judgement not to make
        self.assertIn("display_name에는 가격을 넣지 마", prompt)
        self.assertNotIn("가격/스케일/이름을 한 문장에 억지로 넣지 마", prompt)  # no longer discourages prices

    def test_material_block_lists_the_sale_type(self):
        material = ai_writer._material_block([
            product("예약 피규어", "https://shop.example.com/1", saleStatus="PREORDER"),
            product("재고 피규어", "https://shop.example.com/2", saleStatus="IN_STOCK"),
            product("상태 모름", "https://shop.example.com/3"),
        ])
        self.assertIn("   판매유형: 예약", material)
        self.assertIn("   판매유형: 일반 판매(재고 있음)", material)
        self.assertEqual(material.count("판매유형"), 2)


class WriteDraftPostsTests(unittest.TestCase):
    items = [
        product("[예약] 엘렌 조 피규어", "https://shop.example.com/1"),
        product("호시미 미야비 피규어", "https://shop.example.com/2"),
    ]

    def test_the_body_has_no_link_and_the_reply_carries_every_real_url_in_order(self):
        posts, call = write(self.items, model_json("본문 글 #피규어", (1, "엘렌 조"), (2, "호시미 미야비")))
        self.assertEqual(posts.body, "본문 글 #피규어\n")
        self.assertNotIn("https://", posts.body)
        self.assertEqual(
            posts.reply,
            "상품 페이지 참고 ↓\n\n엘렌 조\nhttps://shop.example.com/1\n\n호시미 미야비\nhttps://shop.example.com/2\n",
        )
        prompt, _, schema = call.call_args.args[0], call.call_args.args[1], call.call_args.args[2]
        self.assertNotIn("https://", prompt)
        self.assertIs(schema, ai_writer.POSTS_SCHEMA)

    def test_a_link_the_model_invents_is_never_used(self):
        response = model_json("본문 https://evil.example.com", (1, "엘렌 조 https://evil.example.com/x"), (2, "미야비"))
        posts, _ = write(self.items, response)
        self.assertNotIn("evil.example.com", posts.reply)
        self.assertIn("https://shop.example.com/1", posts.reply)
        self.assertIn("엘렌 조", posts.reply)

    def test_missing_or_invalid_names_fall_back_to_the_cleaned_title_and_keep_the_link(self):
        response = model_json("본문", (2, "미야비"), (2, "중복"), (9, "범위 밖"), (0, "영번"))
        posts, _ = write(self.items, response)
        self.assertIn("엘렌 조 피규어\nhttps://shop.example.com/1", posts.reply)  # [예약] and the shop removed
        self.assertIn("미야비\nhttps://shop.example.com/2", posts.reply)
        self.assertNotIn("중복", posts.reply)
        self.assertNotIn("범위 밖", posts.reply)

    def test_sources_without_a_link_are_left_out_of_the_reply(self):
        items = [self.items[0], {"title": "링크 없음", "category": "FIGURE"}]
        posts, _ = write(items, model_json("본문", (1, "엘렌 조"), (2, "링크 없음")))
        self.assertEqual(posts.reply, "상품 페이지 참고 ↓\n\n엘렌 조\nhttps://shop.example.com/1\n")

    def test_a_reply_for_non_products_is_headed_plain_links(self):
        items = [{"title": "새 애니 소식", "category": "ANIME", "url": "https://news.example.com/1"}]
        posts, _ = write(items, model_json("본문", (1, "새 애니 소식")))
        self.assertTrue(posts.reply.startswith("링크 ↓\n"))

    def test_bad_model_output_is_an_error_and_writes_nothing(self):
        for response in ("not json", "[]", json.dumps({"post1": "  ", "products": []}), json.dumps({"products": []})):
            with self.subTest(response=response), self.assertRaises(ai_writer.AiWriterError):
                write(self.items, response)

    def test_a_missing_key_or_empty_items_is_an_error(self):
        with patch.object(ai_writer, "api_key", return_value=""), self.assertRaises(ai_writer.AiWriterError):
            ai_writer.write_draft_posts(self.items, "COMPARE")
        with patch.object(ai_writer, "api_key", return_value="fake-key"), self.assertRaises(ai_writer.AiWriterError):
            ai_writer.write_draft_posts([], "COMPARE")


class GeminiRequestTests(unittest.TestCase):
    def sent_body(self, schema):
        response = type("Response", (), {"status_code": 200})()
        with patch.object(ai_writer.requests, "post", return_value=response) as post, \
                patch.object(ai_writer, "_throttle"):
            ai_writer._post_gemini("prompt", "key", schema)
        return post.call_args.kwargs["json"]["generationConfig"]

    def test_a_schema_switches_gemini_to_json_output(self):
        config = self.sent_body(ai_writer.POSTS_SCHEMA)
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertIs(config["responseSchema"], ai_writer.POSTS_SCHEMA)

    def test_no_schema_means_plain_text_output(self):
        config = self.sent_body(None)
        self.assertNotIn("responseMimeType", config)
        self.assertNotIn("responseSchema", config)


class SelectTopItemsTests(unittest.TestCase):
    ITEMS = [{"title": f"item {number}"} for number in range(1, 6)]

    def select(self, response=None, error=None):
        with patch.object(ai_writer, "api_key", return_value="fake-key"), patch.object(
            ai_writer, "_call_gemini", return_value=response, side_effect=error
        ) as call:
            picked = ai_writer.select_top_items(self.ITEMS, 2)
        return picked, call

    def test_selection_asks_for_a_json_array_of_numbers(self):
        picked, call = self.select("[3, 1]")
        self.assertEqual(picked, [self.ITEMS[2], self.ITEMS[0]])
        self.assertIs(call.call_args.args[2], ai_writer.SELECTION_SCHEMA)

    def test_out_of_range_and_repeated_numbers_are_ignored(self):
        picked, _ = self.select("[9, 2, 2, 4]")
        self.assertEqual(picked, [self.ITEMS[1], self.ITEMS[3]])

    def test_an_unparseable_or_failed_selection_falls_back_to_score_order(self):
        for kwargs in ({"response": "모르겠어요"}, {"error": ai_writer.AiWriterError("down")}):
            with self.subTest(kwargs=kwargs):
                picked, _ = self.select(**kwargs)
                self.assertEqual(picked, self.ITEMS[:2])

    def test_no_call_when_every_candidate_is_needed(self):
        with patch.object(ai_writer, "_call_gemini") as call:
            self.assertEqual(ai_writer.select_top_items(self.ITEMS[:2], 2), self.ITEMS[:2])
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
