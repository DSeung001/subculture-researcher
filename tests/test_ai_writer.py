"""Offline checks for AI write-prompt assembly (no Gemini / network)."""

import unittest
from unittest.mock import patch

import ai_writer


class AiWriterPromptTests(unittest.TestCase):
    def test_material_block_hides_anilist_source_and_adds_popularity_hint(self):
        material = ai_writer._material_block(
            [
                {
                    "title": "테스트 애니",
                    "titleKo": "테스트 애니",
                    "source": "AniList 트렌딩 애니",
                    "trending": 1200,
                    "popularity": 50000,
                    "episode": 5,
                    "nextAiringAt": "2026-09-20T12:00:00+00:00",
                    "category": "ANIME",
                }
            ]
        )
        self.assertNotIn("AniList", material)
        self.assertNotIn("트렌딩", material)
        self.assertIn("분위기: 인기 있는 작품", material)
        self.assertIn("방영: 5화 · 다음 방영 2026-09-20T12:00:00+00:00", material)

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

    def test_write_prompt_forbids_anilist_and_uses_sns_tone(self):
        items = [
            {
                "title": "테스트 애니",
                "source": "AniList 트렌딩 애니",
                "trending": 100,
                "category": "ANIME",
                "url": "https://anilist.co/anime/1",
            }
        ]
        category_hint = ai_writer.CATEGORY_HINTS["ANIME"]
        material = ai_writer._material_block(items)
        prompt = ai_writer.PROMPT_TEMPLATE.format(
            angle="NEWS",
            category_hint=category_hint,
            material=material,
        )
        # Material must not leak the internal source name; the forbid rule may name them.
        self.assertNotIn("AniList", material)
        self.assertNotIn("트렌딩", material)
        self.assertIn("인기 있는", material)
        self.assertNotIn("AniList 트렌딩", prompt)
        self.assertIn("AniList, 트렌딩", prompt)
        self.assertIn("집계 사이트", category_hint)

    def test_write_draft_body_still_appends_real_source_urls(self):
        items = [
            {
                "title": "테스트 애니",
                "titleKo": "테스트 애니",
                "source": "AniList 트렌딩 애니",
                "trending": 100,
                "category": "ANIME",
                "url": "https://anilist.co/anime/1",
            }
        ]
        with patch.object(ai_writer, "api_key", return_value="fake-key"), patch.object(
            ai_writer, "_call_gemini", return_value="본문\n#애니"
        ) as call:
            body = ai_writer.write_draft_body(items, "NEWS")
        prompt = call.call_args.args[0]
        self.assertNotIn("AniList 트렌딩", prompt)
        self.assertNotIn("출처: AniList", prompt)
        self.assertIn("출처", body)
        self.assertIn("https://anilist.co/anime/1", body)
        self.assertIn("테스트 애니", body)


if __name__ == "__main__":
    unittest.main()
