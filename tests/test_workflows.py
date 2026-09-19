"""Offline regression checks; no credentials, network, or live database writes."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

import ai_drafts
import app as review
from collectors.local_browser import _extract_candidate_url
from content_model import content_id, content_ref
from content_store import ContentStore, doc_id
from drafts_store import DraftError, _load_contents, create_draft, list_drafts
from presentation import content_score, effective_date


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        # Real SDK reference objects validate paths without making requests.
        self.client = Client(project="offline-tests", credentials=AnonymousCredentials())
        self.db = MagicMock()
        self.drafts = MagicMock()
        self.db.collection.side_effect = lambda name: (
            self.drafts if name == "drafts" else self.client.collection(name)
        )
        self.duplicates = self.drafts.where.return_value.select.return_value
        self.duplicates.stream.return_value = []
        self.drafts.document.return_value.id = "new-draft"

    def snapshot(self, source_id, data, exists=True):
        ref = content_ref(self.client, source_id)
        snapshot = Mock(reference=ref, id=ref.id, exists=exists)
        snapshot.to_dict.return_value = dict(data)
        return snapshot

    def test_storage_identity_survives_category_edit(self):
        snapshot = self.snapshot("FIGURE:abc", {"category": "GOODS"})
        self.assertEqual(content_id(snapshot), "FIGURE:abc")
        self.assertEqual(review.cursor_token(snapshot), "FIGURE:abc")
        self.db.collection_group.return_value.limit.return_value.stream.return_value = [snapshot]
        self.assertEqual(ai_drafts._load_candidates(self.db, "GOODS")[0]["_id"], "FIGURE:abc")

    def test_review_forms_use_storage_category(self):
        snapshot = self.snapshot("FIGURE:abc", {"category": "GOODS", "title": "자료", "status": "NEW"})
        with patch.object(review, "fetch_contents_page", return_value=([snapshot], False, "")):
            response = review.app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('/items/FIGURE/abc/status', response.get_data(as_text=True))
        self.assertIn('value="FIGURE:abc"', response.get_data(as_text=True))

    def test_invalid_reference_rejected(self):
        for source_id in ("", "FIGURE", ":abc", "FIGURE:", "FIGURE:abc/def"):
            with self.subTest(source_id=source_id), self.assertRaises(ValueError):
                content_ref(self.db, source_id)

    def test_bulk_read_preserves_order_and_missing_is_rejected(self):
        first = self.snapshot("FIGURE:a", {"title": "first"})
        second = self.snapshot("GOODS:b", {"title": "second"})
        self.db.get_all.return_value = [second, first]
        items = _load_contents(self.db, ["FIGURE:a", "GOODS:b"])
        self.assertEqual([item["title"] for item in items], ["first", "second"])
        self.db.get_all.assert_called_once()
        self.db.get_all.return_value = [second]
        with self.assertRaises(DraftError):
            _load_contents(self.db, ["FIGURE:a", "GOODS:b"])

    def test_duplicate_skips_expensive_body_generation(self):
        self.db.get_all.return_value = [self.snapshot("FIGURE:a", {})]
        duplicate = Mock()
        duplicate.to_dict.return_value = {"sourceIds": ["FIGURE:a"]}
        self.duplicates.stream.return_value = [duplicate]
        writer = Mock()
        with self.assertRaisesRegex(DraftError, "이미 있습니다"):
            create_draft(self.db, ["FIGURE:a"], angle="NEWS", body_factory=writer)
        writer.assert_not_called()
        self.drafts.document.assert_not_called()
        self.assertEqual(self.drafts.where.call_args.kwargs["filter"].value, "NEWS")

    def test_factory_gets_fresh_sources_and_deduplicated_ids(self):
        self.db.get_all.return_value = [self.snapshot("FIGURE:a", {"title": "fresh"})]
        writer = Mock(return_value="AI body")
        self.assertEqual(create_draft(self.db, [" FIGURE:a ", "FIGURE:a"], body_factory=writer), "new-draft")
        self.assertEqual(writer.call_args.args[0][0]["title"], "fresh")
        self.assertEqual(writer.call_args.args[1], "NEWS")
        saved = self.drafts.document.return_value.set.call_args.args[0]
        self.assertEqual(saved["sourceIds"], ["FIGURE:a"])
        self.assertEqual(saved["body"], "AI body")
        self.db.get_all.assert_called_once()

    def test_posted_news_is_rejected_before_writing_other_angles_allowed(self):
        self.db.get_all.return_value = [self.snapshot("FIGURE:a", {"postedAt": "posted"})]
        writer = Mock(return_value="body")
        with self.assertRaises(DraftError):
            create_draft(self.db, ["FIGURE:a"], angle="NEWS", body_factory=writer)
        writer.assert_not_called()
        create_draft(self.db, ["FIGURE:a"], angle="COMPARE", body_factory=writer)
        writer.assert_called_once()

    def test_failed_writer_does_not_save_draft(self):
        self.db.get_all.return_value = [self.snapshot("FIGURE:a", {})]
        with self.assertRaises(RuntimeError):
            create_draft(self.db, ["FIGURE:a"], body_factory=Mock(side_effect=RuntimeError("failed")))
        self.drafts.document.assert_not_called()

    def test_draft_listing_shares_sources_and_keeps_missing_placeholder(self):
        draft = Mock(id="draft")
        draft.to_dict.return_value = {"status": "DRAFT", "sourceIds": ["FIGURE:a", "GOODS:b"]}
        self.drafts.order_by.return_value.limit.return_value.stream.return_value = [draft, draft]
        self.db.get_all.return_value = [self.snapshot("FIGURE:a", {"title": "present", "postedAt": "posted"})]
        result = list_drafts(self.db)
        self.db.get_all.assert_called_once()
        self.assertEqual(len(self.db.get_all.call_args.args[0]), 2)
        self.assertEqual(result[0]["_sources"][0]["_title"], "present")
        self.assertTrue(result[0]["_sources"][0]["_used"])
        self.assertEqual(result[1]["_sources"][1]["_title"], "(없는 항목)")

    def test_ai_flow_defers_writer_and_validates_size(self):
        with patch.object(ai_drafts, "_load_candidates", return_value=[{"_id": "FIGURE:a"}]), \
             patch.object(ai_drafts, "write_draft_body") as writer, \
             patch.object(ai_drafts, "create_draft", return_value="draft") as create:
            self.assertEqual(ai_drafts.create_trending_draft(self.db), "draft")
            writer.assert_not_called()
            self.assertIs(create.call_args.kwargs["body_factory"], writer)
        for size in (0, -1, 21, True):
            with self.subTest(size=size), self.assertRaises(DraftError):
                ai_drafts.create_trending_draft(self.db, size=size)

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
        with patch.object(ai_drafts, "create_draft", side_effect=["d1", "d2", "d3"]) as create, \
             patch.object(ai_drafts, "write_draft_body"):
            results = ai_drafts.create_work_drafts(self.db, library)
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

    def test_collect_still_runs_mixed_trending_draft(self):
        import collect as collect_mod
        with patch.object(collect_mod, "load_sources", return_value=[]), \
             patch.object(collect_mod, "get_db", return_value=self.db), \
             patch.object(collect_mod, "run_collection") as run, \
             patch.object(collect_mod, "run_trending_draft", return_value="[AI 초안] ok") as draft:
            collect_mod.main([])
        run.assert_called_once()
        draft.assert_called_once_with(self.db)

    def test_manual_vs_automatic_source_filters(self):
        from sources_config import automatic_sources, is_manual_source, manual_sources

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
        import collect as collect_mod
        with patch.object(collect_mod, "load_sources", return_value=[
            {"name": "KADOKAWA Anime YouTube", "manual_only": True},
        ]):
            with self.assertRaises(SystemExit):
                collect_mod.main(["--source", "KADOKAWA Anime YouTube"])

    def test_local_browser_ready_wait_uses_random_sleep(self):
        from collectors import local_browser as lb

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

    def test_url_deduplication_stays_canonical(self):
        store = ContentStore()
        first = store.save({"url": "https://example.com/item?utm_source=x#detail", "category": "FIGURE"})
        second = store.save({"url": "https://example.com/item", "category": "GOODS"})
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["existing"], 1)
        self.assertEqual(doc_id("https://example.com/item#x"), doc_id("https://example.com/item"))


    def test_datetime_publish_date_drives_recency(self):
        published = datetime(2026, 1, 1, tzinfo=timezone.utc)
        item = {"publishedAt": published, "collectedAt": datetime(2026, 1, 3)}
        self.assertEqual(effective_date(item), published)
        self.assertEqual(content_score(item, now=published), 36.0)
        self.assertIsNotNone(effective_date({"collectedAt": datetime(2026, 1, 3)}).tzinfo)

    def test_local_onclick_relative_link_and_absent_link(self):
        locator = Mock()
        locator.get_attribute.side_effect = lambda name: "location.href='/product/1'" if name == "onclick" else None
        self.assertEqual(_extract_candidate_url(locator, "https://example.com"), "https://example.com/product/1")
        locator.get_attribute.side_effect = lambda name: None
        self.assertIsNone(_extract_candidate_url(locator, "https://example.com"))


if __name__ == "__main__":
    unittest.main()
