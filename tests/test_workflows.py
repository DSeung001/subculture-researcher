"""Offline regression checks; no credentials, network, or live database writes."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

from subculture.drafts.application import ai_drafts
from subculture.web import app as review
from subculture.collection.infrastructure.collectors.local_browser import _extract_candidate_url
from subculture.shared.content_model import content_id, content_ref
from subculture.collection.infrastructure.content_store import ContentStore
from subculture.collection.domain.content_rules import doc_id, normalize_url
from subculture.drafts.domain.rules import DraftError
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
        self.assertIn('value="FIGURE:abc"', response.get_data(as_text=True))

    def test_invalid_reference_rejected(self):
        for source_id in ("", "FIGURE", ":abc", "FIGURE:", "FIGURE:abc/def"):
            with self.subTest(source_id=source_id), self.assertRaises(ValueError):
                content_ref(self.db, source_id)

    def test_ai_flow_defers_writer_and_validates_size(self):
        library = Mock()
        library.draft_candidates.return_value = [{"_id": "FIGURE:a"}]
        library.drafted_item_ids.return_value = set()
        with patch.object(ai_drafts, "write_draft_posts") as writer, \
             patch.object(ai_drafts, "create_draft", return_value=7) as create:
            self.assertEqual(ai_drafts.create_trending_draft(library), 7)
            writer.assert_not_called()
            self.assertIs(create.call_args.kwargs["body_factory"], writer)
            self.assertIs(create.call_args.args[0], library)
        for size in (0, -1, 21, True):
            with self.subTest(size=size), self.assertRaises(DraftError):
                ai_drafts.create_trending_draft(library, size=size)

    def test_trending_draft_leaves_out_items_already_in_a_draft(self):
        library = Mock()
        library.draft_candidates.return_value = [{"_id": "FIGURE:a"}, {"_id": "FIGURE:b"}]
        library.drafted_item_ids.return_value = {"FIGURE:a"}
        with patch.object(ai_drafts, "select_top_items", side_effect=lambda pool, size: pool[:size]) as select, \
             patch.object(ai_drafts, "create_draft", return_value=7) as create:
            self.assertEqual(ai_drafts.create_trending_draft(library, size=1), 7)
            self.assertEqual(select.call_args.args[0], [{"_id": "FIGURE:b"}])
            self.assertEqual(create.call_args.args[1], ["FIGURE:b"])

        library.drafted_item_ids.return_value = {"FIGURE:a", "FIGURE:b"}
        with patch.object(ai_drafts, "select_top_items") as select, \
             patch.object(ai_drafts, "create_draft") as create:
            self.assertIsNone(ai_drafts.create_trending_draft(library))
            select.assert_not_called()  # no candidates left: no Gemini call
            create.assert_not_called()

    def test_work_drafts_skip_shared_sources_and_ignore_unusable(self):
        groups = [
            {
                "work_id": 1,
                "work_name": "피규어 작품",
                "items": [
                    {"id": "FIGURE:a", "storage_category": "FIGURE", "data": {"title": "fig"}},
                    {"id": "FIGURE:b", "storage_category": "FIGURE", "data": {"title": "fig2"}},
                    {"id": "FIGURE:ignored", "storage_category": "FIGURE", "data": {"status": "IGNORE"}},
                    {"id": "FIGURE:posted", "storage_category": "FIGURE", "data": {"postedAt": "x"}},
                ],
            },
            {
                "work_id": 2,
                "work_name": "애니 작품",
                "items": [
                    {"id": "ANIME:c", "storage_category": "ANIME", "data": {"title": "anime"}},
                ],
            },
            {
                "work_id": 3,
                "work_name": "혼합 작품",
                "items": [
                    {"id": "FIGURE:e", "storage_category": "FIGURE", "data": {"title": "fig3"}},
                    {"id": "GOODS:d", "storage_category": "GOODS", "data": {"title": "goods"}},
                ],
            },
        ]
        library = Mock()
        library.linked_work_items.return_value = groups
        library.posted_item_ids.return_value = set()
        with patch.object(ai_drafts, "create_draft", side_effect=["d1", "d2", "d3"]) as create, \
             patch.object(ai_drafts, "write_draft_posts"):
            results = ai_drafts.create_work_drafts(library)
        self.assertEqual([r[0] for r in results], ["FIGURE", "ANIME", "MIXED"])
        self.assertEqual([r[1] for r in results], ["d1", "d2", "d3"])
        calls = [call.args[1] for call in create.call_args_list]
        self.assertTrue(all(sid.startswith("FIGURE:") for sid in calls[0]))
        self.assertNotIn("FIGURE:ignored", calls[0])
        self.assertNotIn("FIGURE:posted", calls[0])
        self.assertEqual(calls[1], ["ANIME:c"])
        used = set(calls[0]) | set(calls[1])
        self.assertTrue(set(calls[2]).isdisjoint(used))
        mixed_cats = {sid.partition(":")[0] for sid in calls[2]}
        self.assertGreaterEqual(len(mixed_cats), 2)

    def test_work_drafts_can_target_one_work(self):
        groups = [
            {
                "work_id": 1,
                "work_name": "피규어 작품",
                "items": [
                    {"id": "FIGURE:a", "storage_category": "FIGURE", "data": {"title": "fig"}},
                ],
            },
            {
                "work_id": 2,
                "work_name": "애니 작품",
                "items": [
                    {"id": "ANIME:c", "storage_category": "ANIME", "data": {"title": "anime"}},
                ],
            },
        ]
        library = Mock()
        library.linked_work_items.return_value = groups
        library.posted_item_ids.return_value = set()
        with patch.object(ai_drafts, "create_draft", side_effect=["d1"]) as create, \
             patch.object(ai_drafts, "write_draft_posts"):
            results = ai_drafts.create_work_drafts(library, work_id=2)
        self.assertEqual(create.call_args_list[0].args[1], ["ANIME:c"])
        by_type = {draft_type: draft_id for draft_type, draft_id, _ in results}
        self.assertEqual(by_type["ANIME"], "d1")
        self.assertIsNone(by_type["FIGURE"])
        self.assertIsNone(by_type["MIXED"])

    def test_collect_still_runs_mixed_trending_draft(self):
        from subculture.collection.interface import collect_cli as collect_mod
        with patch.object(collect_mod, "load_sources", return_value=[]), \
             patch.object(collect_mod, "get_db", return_value=self.db), \
             patch.object(collect_mod, "run_collection", return_value={"total": {"inserted": 2}}) as run, \
             patch.object(collect_mod, "run_local_trending_draft", return_value="[AI 초안] ok") as draft, \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("CI", None)
            collect_mod.main([])
        run.assert_called_once()
        draft.assert_called_once_with(None)  # the draft goes to the local library, not Firestore

    def test_collect_skips_the_draft_when_nothing_new_was_inserted(self):
        from subculture.collection.interface import collect_cli as collect_mod
        from subculture.collection.interface import collect_manual_cli as manual_mod
        for module, argv in ((collect_mod, []), (manual_mod, ["--ai-draft"])):
            with self.subTest(module=module.__name__), \
                 patch.object(module, "load_sources", return_value=[]), \
                 patch.object(module, "get_db", return_value=self.db), \
                 patch.object(module, "run_collection", return_value={"total": {"inserted": 0}}), \
                 patch.object(module, "sync_local"), \
                 patch.object(module, "run_local_trending_draft") as draft, \
                 patch.dict("os.environ", {}, clear=False):
                import os
                os.environ.pop("CI", None)
                module.main(argv)
            draft.assert_not_called()

    def test_cloud_run_never_writes_a_draft(self):
        from subculture.collection.interface import collect_cli as collect_mod
        with patch.object(collect_mod, "load_sources", return_value=[]), \
             patch.object(collect_mod, "get_db", return_value=self.db), \
             patch.object(collect_mod, "run_collection", return_value={"total": {"inserted": 2}}), \
             patch.object(collect_mod, "run_local_trending_draft") as draft, \
             patch.dict("os.environ", {"CI": "true"}):
            collect_mod.main([])
        draft.assert_not_called()

    def test_manual_vs_automatic_source_filters(self):
        from subculture.collection.infrastructure.sources_config import automatic_sources, is_manual_source, manual_sources

        youtube = {"name": "KADOKAWA Anime YouTube", "manual_only": True}
        browser = {"name": "예시 브라우저", "local_only": True}
        auto = {"name": "피규어팜 예약상품"}
        sources = [youtube, browser, auto]
        self.assertTrue(is_manual_source(youtube))
        self.assertTrue(is_manual_source(browser))
        self.assertFalse(is_manual_source(auto))
        self.assertEqual(automatic_sources(sources), [auto])
        self.assertEqual(manual_sources(sources), [youtube, browser])

    def test_collect_rejects_manual_source_flag(self):
        from subculture.collection.interface import collect_cli as collect_mod
        with patch.object(collect_mod, "load_sources", return_value=[
            {"name": "KADOKAWA Anime YouTube", "manual_only": True},
        ]):
            with self.assertRaises(SystemExit):
                collect_mod.main(["--source", "KADOKAWA Anime YouTube"])

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
