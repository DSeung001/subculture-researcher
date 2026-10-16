"""Offline regressions for visual extract profiles and extractor YAML overlays."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from subculture.collection.domain.extract_fields import (
    apply_parse,
    parse_date,
    parse_krw,
    parse_sale_status,
)
from subculture.collection.domain.extract_profile import ExtractProfileError, normalize_extract
from subculture.collection.domain.image_collection import image_collection_flags
from subculture.collection.infrastructure.extractors_config import (
    load_extractor_files,
    merge_sources_with_extractors,
    save_extractor,
)
from subculture.collection.infrastructure.mapped_extract import (
    apply_detail_extract,
    extract_list_items,
)
from subculture.collection.infrastructure.preview_html import sanitize_preview_html
from subculture.collection.infrastructure.collectors.html_links import extract_links
from bs4 import BeautifulSoup


LIST_HTML = """
<html><body>
<ul class="products">
  <li class="item">
    <a class="link" href="/product/1"><span class="name">테스트 피규어 A</span></a>
    <span class="price">판매가 12,000원</span>
    <span class="badge">예약</span>
    <img class="thumb" src="/img/a.jpg" alt="상품">
    <span class="noise">참고가 99,000원</span>
  </li>
  <li class="item">
    <a class="link" href="/product/2"><span class="name">테스트 피규어 B</span></a>
    <span class="price">판매가 8,500원</span>
    <img class="sold" src="/icon/sold.png" alt="품절">
    <img class="thumb" src="/img/b.jpg" alt="상품">
  </li>
</ul>
<script>window.hack = true;</script>
<iframe src="https://evil.example/"></iframe>
</body></html>
"""

DETAIL_HTML = """
<html><body>
<div class="gallery">
  <img src="/g/1.jpg">
  <img src="/g/2.jpg">
</div>
</body></html>
"""

EXTRACT = {
    "list": {
        "item": "li.item",
        "fields": {
            "link": {"selector": "a.link", "attr": "href", "parse": "text"},
            "title": {"selector": ".name", "parse": "text"},
            "price": {"selector": ".price", "parse": "krw"},
            "image": {"selector": "img.thumb", "attr": "src", "parse": "text"},
            "status": {"selector": ".badge, img.sold", "attr": "alt", "parse": "sale_status"},
        },
    },
    "detail": {
        "fields": {
            "gallery": {"selector": ".gallery img", "attr": "src", "parse": "text", "many": True},
        },
    },
}


class ParseTests(unittest.TestCase):
    def test_krw_and_status_and_date(self):
        self.assertEqual(parse_krw("판매가 12,000원"), 12000)
        self.assertIsNone(parse_krw("900원"))
        self.assertEqual(parse_sale_status("예약 진행"), "PREORDER")
        self.assertEqual(parse_sale_status("예약 품절"), "SOLD_OUT")
        self.assertEqual(parse_date("26년 3월 15일"), "2026-03-15")
        self.assertEqual(apply_parse("krw", "3,000원"), 3000)


class ProfileNormalizeTests(unittest.TestCase):
    def test_requires_link_and_title(self):
        with self.assertRaises(ExtractProfileError):
            normalize_extract({"list": {"item": "li", "fields": {"link": {"selector": "a"}}}})

    def test_normalizes_fields(self):
        out = normalize_extract(EXTRACT)
        self.assertEqual(out["list"]["item"], "li.item")
        self.assertEqual(out["list"]["fields"]["price"]["parse"], "krw")
        self.assertTrue(out["detail"]["fields"]["gallery"]["many"])


class MappedExtractTests(unittest.TestCase):
    def test_list_items_use_field_selectors_not_whole_card_price(self):
        source = {
            "name": "테스트샵",
            "url": "https://shop.example/list",
            "extract": normalize_extract(EXTRACT),
        }
        items = extract_list_items(LIST_HTML, source["url"], source)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "테스트 피규어 A")
        self.assertEqual(items[0]["price"], 12000)
        self.assertNotEqual(items[0]["price"], 99000)
        self.assertEqual(items[0]["saleStatus"], "PREORDER")
        self.assertTrue(items[0]["url"].endswith("/product/1"))
        self.assertIn("/img/a.jpg", items[0]["imageUrl"])
        self.assertEqual(items[1]["saleStatus"], "SOLD_OUT")

    def test_extract_links_routes_to_mapped_extract(self):
        source = {
            "name": "테스트샵",
            "url": "https://shop.example/list",
            "extract": normalize_extract(EXTRACT),
            "link_selector": "a.should-not-matter",
        }
        items = list(extract_links(LIST_HTML, source["url"], source))
        self.assertEqual(len(items), 2)

    def test_detail_gallery(self):
        source = {"name": "테스트샵", "extract": normalize_extract(EXTRACT)}
        item = {"url": "https://shop.example/product/1", "title": "A"}
        soup = BeautifulSoup(DETAIL_HTML, "html.parser")
        apply_detail_extract(soup, "https://shop.example/product/1", source, item)
        self.assertEqual(len(item["detailImageUrls"]), 2)

    def test_image_flags_from_extract(self):
        flags = image_collection_flags({"extract": normalize_extract(EXTRACT)})
        self.assertTrue(flags["main"])
        self.assertTrue(flags["detail"])


class ExtractorMergeTests(unittest.TestCase):
    def test_overlay_and_standalone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_extractor(
                {
                    "name": "기존 샵",
                    "extract": EXTRACT,
                },
                directory=root,
            )
            save_extractor(
                {
                    "name": "새 샵",
                    "url": "https://new.example/",
                    "type": "html",
                    "category": "GOODS",
                    "region": "KR",
                    "content_angle": "PRICE",
                    "source_tier": "MEDIA",
                    "enabled": False,
                    "extract": EXTRACT,
                },
                directory=root,
            )
            overlays = load_extractor_files(root)
            merged = merge_sources_with_extractors(
                [
                    {"name": "기존 샵", "url": "https://old.example/", "type": "html", "enabled": True},
                    {"name": "다른 샵", "url": "https://other.example/", "type": "html"},
                ],
                overlays,
            )
            by_name = {s["name"]: s for s in merged}
            self.assertIn("extract", by_name["기존 샵"])
            self.assertNotIn("extract", by_name["다른 샵"])
            self.assertTrue(by_name["새 샵"].get("_from_extractor"))
            self.assertFalse(by_name["새 샵"]["enabled"])


class PreviewSanitizeTests(unittest.TestCase):
    def test_strips_script_and_iframe(self):
        html = sanitize_preview_html(LIST_HTML, "https://shop.example/list")
        self.assertNotIn("<script>window.hack", html)
        self.assertNotIn("evil.example", html)
        self.assertIn("extract-pick", html)
        self.assertIn('href="https://shop.example/product/1"', html)

    def test_keeps_shop_stylesheets_but_drops_other_links(self):
        page = (
            '<html><head><link rel="stylesheet" href="/css/shop.css">'
            '<link rel="preload" href="/js/app.js" as="script"></head>'
            '<body><p>x</p></body></html>'
        )
        soup = BeautifulSoup(sanitize_preview_html(page, "https://shop.example/list"), "html.parser")
        links = soup.find_all("link")
        self.assertEqual([link["href"] for link in links], ["https://shop.example/css/shop.css"])


class ExtractPickerUiTests(unittest.TestCase):
    def setUp(self):
        from subculture.web import app as review
        self.review = review
        self.client = review.app.test_client()

    def test_sources_page_shows_extract_link_for_html(self):
        html_source = {
            "name": "픽커샵",
            "url": "https://picker.example/",
            "type": "html",
            "category": "GOODS",
            "region": "KR",
            "source_tier": "MEDIA",
            "enabled": True,
        }
        with patch.object(self.review, "load_sources", return_value=[html_source]):
            response = self.client.get("/sources")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("추출 만들기", body)
        self.assertIn("사이트 추가", body)

    def test_sample_endpoint_with_fixture_html(self):
        source = {
            "name": "픽커샵",
            "url": "https://shop.example/list",
            "type": "html",
            "category": "GOODS",
            "region": "KR",
            "source_tier": "MEDIA",
            "enabled": True,
        }
        with patch.object(self.review, "load_sources", return_value=[source]):
            response = self.client.post(
                "/sources/%ED%94%BD%EC%BB%A4%EC%83%B5/extract/sample",
                json={"extract": EXTRACT, "html": LIST_HTML, "base_url": source["url"]},
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["items"][0]["price"], 12000)

    def test_preview_is_served_in_an_opaque_origin_sandbox(self):
        source = {
            "name": "픽커샵",
            "url": "https://shop.example/list",
            "type": "html",
            "category": "GOODS",
            "region": "KR",
            "source_tier": "MEDIA",
            "enabled": True,
        }
        preview = sanitize_preview_html(LIST_HTML, source["url"])
        with patch.object(self.review, "load_sources", return_value=[source]), \
                patch.object(self.review, "preview_document", return_value=(preview, source["url"])):
            response = self.client.get("/sources/%ED%94%BD%EC%BB%A4%EC%83%B5/extract/preview")
        self.assertEqual(response.status_code, 200)
        policy = response.headers.get("Content-Security-Policy", "")
        self.assertIn("sandbox", policy)
        self.assertNotIn("allow-same-origin", policy)

    def test_save_extractor_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {
                "name": "픽커샵",
                "url": "https://shop.example/list",
                "type": "html",
                "category": "GOODS",
                "region": "KR",
                "source_tier": "MEDIA",
                "enabled": True,
            }
            with patch.object(self.review, "load_sources", return_value=[source]), \
                 patch("subculture.web.app.extractor_path_for", return_value=root / "picker.yaml"), \
                 patch("subculture.web.app.save_extractor", side_effect=lambda data, path=None, directory=None: save_extractor(data, path=path or (root / "picker.yaml"), directory=directory)):
                response = self.client.post(
                    "/sources/픽커샵/extract",
                    json={"extract": EXTRACT},
                    headers={"Accept": "application/json"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertTrue((root / "picker.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
