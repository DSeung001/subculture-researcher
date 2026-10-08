"""Offline regression checks; no credentials, network, or live database writes."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

from subculture.web import app as review
from subculture.collection.infrastructure.collectors.local_browser import _extract_candidate_url
from subculture.shared.content_model import content_id, content_ref
from subculture.collection.infrastructure.content_store import ContentStore
from subculture.collection.domain.content_rules import doc_id, normalize_url
from subculture.shared.presentation import content_score, effective_date


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        # Real SDK reference objects validate paths without making requests.
        self.client = Client(project="offline-tests", credentials=AnonymousCredentials())
        self.db = MagicMock()
        self.db.collection.side_effect = lambda name: self.client.collection(name)

    def snapshot(self, source_id, data, exists=True):
        ref = content_ref(self.client, source_id)
        snapshot = Mock(reference=ref, id=ref.id, exists=exists)
        snapshot.to_dict.return_value = dict(data)
        return snapshot

    def test_storage_identity_survives_category_edit(self):
        snapshot = self.snapshot("FIGURE:abc", {"category": "GOODS"})
        self.assertEqual(content_id(snapshot), "FIGURE:abc")
        self.assertEqual(review.cursor_token(snapshot), "FIGURE:abc")

    def test_review_forms_use_storage_category(self):
        snapshot = self.snapshot("FIGURE:abc", {"category": "GOODS", "title": "자료", "status": "NEW"})
        with patch.object(review, "fetch_contents_page", return_value=([snapshot], False, "")), \
                patch.object(review, "fetch_recommended_items", return_value=[]):
            response = review.app.test_client().get("/inbox")
        self.assertEqual(response.status_code, 200)
        self.assertIn('/items/FIGURE/abc/status', response.get_data(as_text=True))
        self.assertIn('/items/FIGURE/abc/note', response.get_data(as_text=True))

    def test_invalid_reference_rejected(self):
        for source_id in ("", "FIGURE", ":abc", "FIGURE:", "FIGURE:abc/def"):
            with self.subTest(source_id=source_id), self.assertRaises(ValueError):
                content_ref(self.db, source_id)

    def test_manual_vs_automatic_source_filters(self):
        from subculture.collection.infrastructure.sources_config import automatic_sources, is_manual_source, manual_sources

        manual = {"name": "예시 수동 소스", "manual_only": True}
        browser = {"name": "예시 브라우저", "local_only": True}
        auto = {"name": "피규어팜 예약상품"}
        sources = [manual, browser, auto]
        self.assertTrue(is_manual_source(manual))
        self.assertTrue(is_manual_source(browser))
        self.assertFalse(is_manual_source(auto))
        self.assertEqual(automatic_sources(sources), [auto])
        self.assertEqual(manual_sources(sources), [manual, browser])

    def test_collect_rejects_manual_source_flag(self):
        from subculture.collection.interface import collect_cli as collect_mod
        with patch.object(collect_mod, "load_sources", return_value=[
            {"name": "예시 수동 소스", "manual_only": True},
        ]):
            with self.assertRaises(SystemExit):
                collect_mod.main(["--source", "예시 수동 소스"])

    def test_app_help_prints_usage_without_starting_the_server(self):
        from subculture.web import app as web_app
        with patch.object(web_app.app, "run") as run, patch("sys.stdout"):
            with self.assertRaises(SystemExit) as exit_:
                web_app.main(["--help"])
        self.assertEqual(exit_.exception.code, 0)
        run.assert_not_called()
        with patch.object(web_app.app, "run") as run:
            web_app.main([])
        run.assert_called_once_with(host="127.0.0.1", port=5001, debug=True)

    def test_local_browser_ready_wait_uses_random_sleep(self):
        from subculture.collection.infrastructure.collectors import local_browser as lb

        with patch.object(lb.random, "uniform", return_value=11.5) as uniform:
            self.assertEqual(lb._ready_wait_seconds({
                "ready_wait_min_seconds": 10,
                "ready_wait_max_seconds": 12,
            }), 11.5)
            uniform.assert_called_once_with(10.0, 12.0)

        with patch.object(lb, "_ready_wait_seconds", return_value=11.0), \
             patch.object(lb.time, "sleep") as sleep, \
             patch("builtins.input") as stdin:
            lb._wait_until_ready({
                "name": "테스트 브라우저",
                "interactive_ready": True,
                "interactive_message": "준비하세요.",
            })
        sleep.assert_called_once_with(11.0)
        stdin.assert_not_called()

        with patch.object(lb.time, "sleep") as sleep, patch("builtins.input") as stdin:
            lb._wait_until_ready({"name": "noop", "interactive_ready": False})
        sleep.assert_not_called()
        stdin.assert_not_called()

    def run_local_browser(self, source):
        """Drive local_browser_items against a fake Playwright; returns (playwright, browser, context)."""
        import sys
        from subculture.collection.infrastructure.collectors import local_browser as lb

        context = MagicMock()
        context.pages = []
        page = context.new_page.return_value
        page.url = "https://example.com/list"
        page.locator.return_value.count.return_value = 0
        browser = MagicMock()
        browser.new_context.return_value = context
        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser
        playwright.chromium.launch_persistent_context.return_value = context
        sync_api = MagicMock()
        sync_api.sync_playwright.return_value.__enter__.return_value = playwright
        with patch.dict(sys.modules, {"playwright": MagicMock(), "playwright.sync_api": sync_api}), \
             patch.object(lb.time, "sleep"):
            self.assertEqual(list(lb.local_browser_items({"name": "예시", "url": "https://example.com/list", **source})), [])
        return playwright, browser, context

    def test_local_browser_uses_a_private_context_by_default(self):
        playwright, browser, context = self.run_local_browser({"scroll_steps": 0})
        playwright.chromium.launch.assert_called_once()
        self.assertFalse(playwright.chromium.launch.call_args.kwargs["headless"])
        browser.new_context.assert_called_once_with(no_viewport=True)
        playwright.chromium.launch_persistent_context.assert_not_called()
        context.close.assert_called_once()
        browser.close.assert_called_once()

    def test_local_browser_persistent_profile_is_opt_in(self):
        with patch("subculture.collection.infrastructure.collectors.local_browser.Path.mkdir"):
            playwright, browser, context = self.run_local_browser({"scroll_steps": 0, "persistent_profile": True})
        playwright.chromium.launch.assert_not_called()
        playwright.chromium.launch_persistent_context.assert_called_once()
        self.assertFalse(playwright.chromium.launch_persistent_context.call_args.kwargs["headless"])
        context.close.assert_called_once()

    def test_url_deduplication_stays_canonical(self):
        store = ContentStore()
        first = store.save({"url": "https://example.com/item?utm_source=x#detail", "category": "FIGURE"})
        second = store.save({"url": "https://example.com/item", "category": "GOODS"})
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["existing"], 1)
        self.assertEqual(doc_id("https://example.com/item#x"), doc_id("https://example.com/item"))

    def test_cafe24_product_urls_collapse_to_product_no(self):
        short = "https://m.figurepresso.com/product/detail.html?product_no=79738"
        variants = [
            short,
            "https://m.figurepresso.com/product/detail.html?product_no=79738&cate_no=24",
            "https://m.figurepresso.com/product/some-slug/79738/",
            "https://www.figurepresso.com/product/a/b/79738",
            "https://figurepresso.com/product/detail.html?product_no=79738&utm_source=x",
        ]
        for url in variants:
            with self.subTest(url=url):
                self.assertEqual(normalize_url(url), short)
                self.assertEqual(doc_id(url), doc_id(short))
        # List / category pages have no product_no and must stay unchanged.
        listing = "https://m.figurepresso.com/product/preorder.html?cate_no=24"
        self.assertEqual(normalize_url(listing), listing)
        ttabbae = "https://ttabbaemall.co.kr/product/detail.html?product_no=42"
        self.assertEqual(
            normalize_url("https://www.ttabbaemall.co.kr/product/hoyoverse-goods/42/"),
            ttabbae,
        )
        self.assertEqual(
            normalize_url("https://m.ttabbaemall.co.kr/product/detail.html?product_no=42&cate_no=1"),
            ttabbae,
        )
        # List-page SEO links end in /category/N/display/N/; the id is the number before that tail.
        comics = "https://comics-art.co.kr/product/detail.html?product_no=257347"
        for url in (
            "https://comics-art.co.kr/product/골든-헤드-피규어/257347/category/1215/display/1/",
            "https://www.comics-art.co.kr/product/slug/257347/category/49/display/1",
            "https://m.comics-art.co.kr/product/slug/257347/",
            "https://comics-art.co.kr/product/detail.html?product_no=257347&cate_no=1215&display_group=1",
        ):
            with self.subTest(url=url):
                self.assertEqual(normalize_url(url), comics)
        template = "https://comics-art.co.kr/product/{$url}"
        self.assertEqual(normalize_url(template), template)  # the unfilled skin template keeps no product_no
        for host, product_no, path in (
            ("herotime.co.kr", 76677, "/product/블리츠웨이-카보틱스-마징가z-보스보로트/76677/category/51/display/1/"),
            ("dokidokigoods.co.kr", 176907, "/product/detail.html?product_no=176907&cate_no=28&display_group=3"),
        ):
            for prefix in ("", "www.", "m."):
                with self.subTest(host=prefix + host):
                    self.assertEqual(
                        normalize_url(f"https://{prefix}{host}{path}"),
                        f"https://{host}/product/detail.html?product_no={product_no}",
                    )
        maniahouse = "https://maniahouse.co.kr/product/detail.html?product_no=25843"
        for url in (
            "https://maniahouse.co.kr/product/detail.html?product_no=25843&cate_no=45&display_group=1",
            "https://www.maniahouse.co.kr/product/some-figure/25843/",
        ):
            with self.subTest(url=url):
                self.assertEqual(normalize_url(url), maniahouse)


    def test_datetime_publish_date_drives_recency(self):
        published = datetime(2026, 1, 1, tzinfo=timezone.utc)
        item = {"publishedAt": published, "collectedAt": datetime(2026, 1, 3)}
        self.assertEqual(effective_date(item), published)
        # Freshness-only baseline: no trend/magnitude/bonus signals, so this is exactly
        # the freshness weight (100 * FRESHNESS_WEIGHT) - see presentation.score_components.
        self.assertEqual(content_score(item, now=published), 35.0)
        self.assertIsNotNone(effective_date({"collectedAt": datetime(2026, 1, 3)}).tzinfo)

    def test_local_onclick_relative_link_and_absent_link(self):
        locator = Mock()
        locator.get_attribute.side_effect = lambda name: "location.href='/product/1'" if name == "onclick" else None
        self.assertEqual(_extract_candidate_url(locator, "https://example.com"), "https://example.com/product/1")
        locator.get_attribute.side_effect = lambda name: None
        self.assertIsNone(_extract_candidate_url(locator, "https://example.com"))


if __name__ == "__main__":
    unittest.main()
