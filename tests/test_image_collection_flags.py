"""Offline checks for sources.yaml → main/detail image collection flags."""

import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from subculture.collection.domain.image_collection import image_collection_flags
from subculture.collection.infrastructure.sources_config import load_sources


class ImageCollectionFlagsTests(unittest.TestCase):
    def test_product_with_gallery_selector(self):
        flags = image_collection_flags({
            "product_mode": True,
            "detail_images_selector": "#prdDetail img",
        })
        self.assertEqual(flags, {"main": True, "detail": True})

    def test_list_image_only(self):
        flags = image_collection_flags({"list_image_selector": "img", "list_product_mode": True})
        self.assertEqual(flags, {"main": True, "detail": False})

    def test_fetch_detail_image_only(self):
        flags = image_collection_flags({"fetch_detail_image": True})
        self.assertEqual(flags, {"main": True, "detail": False})

    def test_json_api_html_image(self):
        flags = image_collection_flags({"image_html_field": "content"})
        self.assertEqual(flags, {"main": True, "detail": False})

    def test_builtin_collector_types(self):
        self.assertEqual(image_collection_flags({"type": "figurefarm"}), {"main": True, "detail": False})
        for kind in ("anilist", "youtube_feed"):  # removed collectors
            with self.subTest(kind=kind):
                self.assertEqual(image_collection_flags({"type": kind}), {"main": False, "detail": False})

    def test_no_image_config(self):
        self.assertEqual(image_collection_flags({"type": "rss"}), {"main": False, "detail": False})
        self.assertEqual(image_collection_flags({}), {"main": False, "detail": False})

    def test_real_sources_match_expectations(self):
        by_name = {s["name"]: s for s in load_sources()}
        self.assertEqual(
            image_collection_flags(by_name["따빼몰 호요버스 굿즈"]),
            {"main": True, "detail": True},
        )
        for name in (
            "라프텔 스토어", "피규어팜 예약상품", "코믹스아트 신작 상품", "코믹스아트 입고 완료 당일 발송",
            "헤로타임 최신예약", "도키도키굿즈 신상품", "아트플렉스 전체 상품", "이딴가게 신규입고",
            "건담붐 예약상품",
        ):
            with self.subTest(name=name):
                self.assertEqual(image_collection_flags(by_name[name]), {"main": True, "detail": True})
        self.assertEqual(
            image_collection_flags(by_name["McFarlane Toys 뉴스"]),
            {"main": True, "detail": False},
        )
        self.assertEqual(
            image_collection_flags(by_name["메가하우스 몰 입고 상품"]),
            {"main": True, "detail": False},
        )


class SourcesPageImageColumnTests(unittest.TestCase):
    def test_each_source_shows_its_own_image_capabilities(self):
        from subculture.web import app as review
        sources = [
            {"name": "목록", "url": "https://example.com/list", "list_image_selector": "img"},
            {"name": "갤러리", "url": "https://example.com/gallery", "detail_images_selector": "img", "product_mode": True},
            {"name": "이미지 없음", "url": "https://example.com/plain", "type": "rss"},
        ]
        with patch.object(review, "load_sources", return_value=sources):
            response = review.app.test_client().get("/sources")
        self.assertEqual(response.status_code, 200)
        page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
        rows = page.select("tbody tr")
        self.assertEqual([row.select_one("td").get_text(strip=True) for row in rows],
                         ["목록", "갤러리", "이미지 없음"])
        self.assertEqual([row.select_one("td.image-flags").get_text(" ", strip=True) for row in rows],
                         ["대표", "대표 상세", "없음"])


if __name__ == "__main__":
    unittest.main()
