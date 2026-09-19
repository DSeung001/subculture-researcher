"""Offline checks for drafts kept in the local library, and for their page."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

from subculture.web import app as review
from subculture.drafts.interface import delete_firestore_drafts
from subculture.shared.content_model import content_ref
from subculture.drafts.domain.rules import DraftError
from subculture.drafts.application.drafts import create_draft, delete_draft, list_drafts, publish_draft, save_body
from subculture.library.infrastructure.database import SchemaError
from subculture.library.infrastructure.local_library import Library


def doc(doc_id, category="FIGURE", **fields):
    data = {"title": f"제목 {doc_id}", "url": f"https://example.com/{doc_id}", "source": "Shop",
            "category": category, **fields}
    return SimpleNamespace(
        id=doc_id,
        reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id=category))),
        to_dict=lambda: dict(data),
    )


def cloud_of(*docs):
    db = Mock()
    db.collection_group.return_value.stream.return_value = iter(docs)
    return db


class DraftCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.lib = Library(self.path)
        self.lib.sync(cloud_of(
            doc("a", imageUrl="https://cdn.example.com/a.jpg", titleKo="한글 제목", summary="요약"),
            doc("b"),
            doc("c", category="ANIME", postedAt="2026-09-01T00:00:00+00:00"),
            doc("d", status="IGNORE"),
        ))


class CreateTests(DraftCase):
    def test_ids_are_deduplicated_and_the_body_uses_the_stored_sources(self):
        writer = Mock(return_value="AI body")
        draft_id = create_draft(self.lib, [" FIGURE:a ", "FIGURE:a", "FIGURE:b"], body_factory=writer)
        self.assertIsInstance(draft_id, int)
        items, angle = writer.call_args.args
        self.assertEqual([item["_id"] for item in items], ["FIGURE:a", "FIGURE:b"])
        self.assertEqual(angle, "COMPARE")
        (draft,) = list_drafts(self.lib)
        self.assertEqual((draft["body"], draft["sourceIds"]), ("AI body", ["FIGURE:a", "FIGURE:b"]))
        self.assertEqual(draft["status"], "DRAFT")

    def test_source_count_limits_and_bad_ids(self):
        with self.assertRaisesRegex(DraftError, "선택"):
            create_draft(self.lib, [])
        with self.assertRaisesRegex(DraftError, "20개"):
            create_draft(self.lib, [f"FIGURE:{i}" for i in range(21)])
        for bad in ("FIGURE", ":a", "FIGURE:", "FIGURE:a/b"):
            with self.subTest(bad=bad), self.assertRaisesRegex(DraftError, "잘못된"):
                create_draft(self.lib, [bad])

    def test_missing_source_is_rejected_and_nothing_is_saved(self):
        with self.assertRaisesRegex(DraftError, "없는 자료"):
            create_draft(self.lib, ["FIGURE:a", "FIGURE:nope"])
        self.assertEqual(list_drafts(self.lib, "ALL"), [])

    def test_same_sources_and_angle_is_a_duplicate_in_any_order_and_state(self):
        writer = Mock(return_value="body")
        first = create_draft(self.lib, ["FIGURE:a", "FIGURE:b"], angle="COMPARE", body_factory=writer)
        writer.reset_mock()
        with self.assertRaisesRegex(DraftError, "이미 있습니다"):
            create_draft(self.lib, ["FIGURE:b", "FIGURE:a"], angle="COMPARE", body_factory=writer)
        writer.assert_not_called()  # the expensive body is never generated for a duplicate
        publish_draft(self.lib, first)
        with self.assertRaisesRegex(DraftError, "이미 있습니다"):
            create_draft(self.lib, ["FIGURE:a", "FIGURE:b"], angle="COMPARE")
        create_draft(self.lib, ["FIGURE:a", "FIGURE:b"], angle="PRICE")  # another angle is fine
        create_draft(self.lib, ["FIGURE:a"], angle="COMPARE")  # another source set is fine

    def test_news_cannot_reuse_a_posted_source_but_other_angles_can(self):
        writer = Mock(return_value="body")
        with self.assertRaisesRegex(DraftError, "뉴스"):
            create_draft(self.lib, ["ANIME:c"], angle="NEWS", body_factory=writer)  # postedAt in the document
        writer.assert_not_called()
        published = create_draft(self.lib, ["FIGURE:b"], angle="NEWS")
        publish_draft(self.lib, published)
        with self.assertRaisesRegex(DraftError, "뉴스"):
            create_draft(self.lib, ["FIGURE:b", "FIGURE:a"], angle="NEWS")  # in a published draft
        create_draft(self.lib, ["ANIME:c"], angle="COMPARE", body_factory=writer)
        writer.assert_called_once()

    def test_failed_writer_saves_nothing(self):
        with self.assertRaises(RuntimeError):
            create_draft(self.lib, ["FIGURE:a"], body_factory=Mock(side_effect=RuntimeError("failed")))
        self.assertEqual(list_drafts(self.lib, "ALL"), [])

    def test_body_and_body_factory_are_exclusive(self):
        with self.assertRaises(ValueError):
            create_draft(self.lib, ["FIGURE:a"], body="x", body_factory=Mock())

    def test_default_body_lists_titles_urls_and_notes(self):
        draft_id = create_draft(self.lib, ["FIGURE:a"])
        (draft,) = list_drafts(self.lib)
        self.assertEqual(draft["_id"], draft_id)
        self.assertIn("한글 제목", draft["body"])
        self.assertIn("https://example.com/a", draft["body"])


class MissingSourceFetchTests(DraftCase):
    def snapshots(self, *names):
        client = Client(project="offline-tests", credentials=AnonymousCredentials())
        result = []
        for name in names:
            ref = content_ref(client, f"GOODS:{name}")
            snapshot = Mock(reference=ref, id=ref.id, exists=True)
            snapshot.to_dict.return_value = {"title": f"새 {name}", "url": f"https://example.com/{name}",
                                             "source": "Shop", "category": "GOODS"}
            result.append(snapshot)
        return client, result

    def test_unsynced_sources_come_from_one_bulk_read_in_any_order(self):
        client, snapshots = self.snapshots("x", "y")
        cloud = MagicMock()
        cloud.collection.side_effect = client.collection
        cloud.get_all.return_value = list(reversed(snapshots))  # get_all does not keep the input order
        writer = Mock(return_value="body")
        create_draft(self.lib, ["GOODS:x", "FIGURE:a", "GOODS:y"], body_factory=writer, cloud=cloud)
        cloud.get_all.assert_called_once()
        self.assertEqual(len(cloud.get_all.call_args.args[0]), 2)  # only the two unsynced ones
        self.assertEqual([i["_id"] for i in writer.call_args.args[0]], ["GOODS:x", "FIGURE:a", "GOODS:y"])
        self.assertIn("GOODS:x", self.lib.items_by_id(["GOODS:x"]))  # kept locally now

    def test_still_missing_after_the_fetch_is_an_error(self):
        client, snapshots = self.snapshots("x")
        cloud = MagicMock()
        cloud.collection.side_effect = client.collection
        cloud.get_all.return_value = snapshots
        with self.assertRaisesRegex(DraftError, "없는 자료"):
            create_draft(self.lib, ["GOODS:x", "GOODS:ghost"], cloud=cloud)


class ListingTests(DraftCase):
    def test_sources_carry_photo_title_and_used_marks(self):
        create_draft(self.lib, ["FIGURE:a", "ANIME:c"], angle="COMPARE")
        (draft,) = list_drafts(self.lib)
        first, second = draft["_sources"]
        self.assertEqual((first["_title"], first["_image"]), ("한글 제목", "https://cdn.example.com/a.jpg"))
        self.assertEqual(second["_image"], "")
        self.assertEqual(second["_category"], "애니")
        self.assertTrue(second["_used"])  # already posted elsewhere
        self.assertFalse(first["_used"])

    def test_only_http_photos_are_kept(self):
        self.lib.upsert_snapshots([doc("p", imageUrl="javascript:alert(1)")])
        create_draft(self.lib, ["FIGURE:p"])
        self.assertEqual(list_drafts(self.lib)[0]["_sources"][0]["_image"], "")

    def test_removed_source_keeps_a_placeholder_and_the_draft(self):
        create_draft(self.lib, ["FIGURE:a", "FIGURE:b"])
        self.lib.delete_items(["FIGURE:b"])
        (draft,) = list_drafts(self.lib)
        self.assertEqual([s["_title"] for s in draft["_sources"]], ["한글 제목", "(없는 항목)"])

    def test_status_filter_and_newest_first(self):
        first = create_draft(self.lib, ["FIGURE:a"])
        second = create_draft(self.lib, ["FIGURE:b"])
        publish_draft(self.lib, first)
        self.assertEqual([d["_id"] for d in list_drafts(self.lib, "DRAFT")], [second])
        self.assertEqual([d["_id"] for d in list_drafts(self.lib, "POSTED")], [first])
        self.assertEqual([d["_id"] for d in list_drafts(self.lib, "ALL")], [second, first])
        posted = list_drafts(self.lib, "POSTED")[0]
        self.assertIsInstance(posted["postedAt"], datetime)
        self.assertFalse(posted["_sources"][0]["_used"])  # the published draft is itself the use


class LifecycleTests(DraftCase):
    def test_save_body_edits_only_unpublished_drafts(self):
        draft_id = create_draft(self.lib, ["FIGURE:a"])
        save_body(self.lib, draft_id, "새 본문")
        self.assertEqual(list_drafts(self.lib)[0]["body"], "새 본문")
        publish_draft(self.lib, draft_id)
        with self.assertRaisesRegex(DraftError, "수정"):
            save_body(self.lib, draft_id, "또 수정")
        with self.assertRaisesRegex(DraftError, "찾을 수 없"):
            save_body(self.lib, 999, "x")

    def test_delete_removes_the_draft_and_its_sources_but_not_published_ones(self):
        gone = create_draft(self.lib, ["FIGURE:a"])
        kept = create_draft(self.lib, ["FIGURE:b"])
        delete_draft(self.lib, gone)
        self.assertEqual([d["_id"] for d in list_drafts(self.lib, "ALL")], [kept])
        publish_draft(self.lib, kept)
        with self.assertRaisesRegex(DraftError, "삭제"):
            delete_draft(self.lib, kept)
        with self.assertRaisesRegex(DraftError, "찾을 수 없"):
            delete_draft(self.lib, gone)
        self.assertEqual(self.lib.posted_item_ids(), {"FIGURE:b"})

    def test_publish_marks_only_unposted_sources_in_firestore(self):
        draft_id = create_draft(self.lib, ["FIGURE:a", "ANIME:c"], angle="COMPARE")
        fresh = Mock(exists=True, reference=Mock())
        fresh.to_dict.return_value = {}
        already = Mock(exists=True, reference=Mock())
        already.to_dict.return_value = {"postedAt": "earlier"}
        cloud = MagicMock()
        cloud.get_all.return_value = [already, fresh]
        with patch("subculture.drafts.application.drafts.content_ref"):
            self.assertEqual(publish_draft(self.lib, draft_id, cloud=cloud), [])
        cloud.get_all.assert_called_once()
        fresh.reference.update.assert_called_once()
        self.assertIsInstance(fresh.reference.update.call_args.args[0]["postedAt"], datetime)
        already.reference.update.assert_not_called()
        self.assertEqual(list_drafts(self.lib, "POSTED")[0]["status"], "POSTED")

    def test_firestore_failure_warns_but_keeps_the_local_publish(self):
        draft_id = create_draft(self.lib, ["FIGURE:a"])
        cloud = MagicMock()
        cloud.get_all.side_effect = RuntimeError("offline")
        with patch("subculture.drafts.application.drafts.content_ref"):
            warnings = publish_draft(self.lib, draft_id, cloud=cloud)
        self.assertEqual(len(warnings), 1)
        self.assertIn("offline", warnings[0])
        self.assertEqual(list_drafts(self.lib, "POSTED")[0]["_id"], draft_id)
        with self.assertRaisesRegex(DraftError, "이미 발행"):
            publish_draft(self.lib, draft_id)

    def test_publish_without_cloud_touches_nothing_remote(self):
        draft_id = create_draft(self.lib, ["FIGURE:a"])
        self.assertEqual(publish_draft(self.lib, draft_id), [])


class CandidateTests(DraftCase):
    def test_candidates_leave_out_ignored_posted_and_published_draft_sources(self):
        self.assertEqual(sorted(i["_id"] for i in self.lib.draft_candidates()), ["FIGURE:a", "FIGURE:b"])
        publish_draft(self.lib, create_draft(self.lib, ["FIGURE:b"], angle="NEWS"))
        self.assertEqual([i["_id"] for i in self.lib.draft_candidates()], ["FIGURE:a"])
        self.assertEqual(self.lib.draft_candidates("ANIME"), [])
        self.assertEqual([i["_id"] for i in self.lib.draft_candidates("FIGURE")], ["FIGURE:a"])

    def test_draft_sources_are_never_pruned_as_orphans(self):
        create_draft(self.lib, ["FIGURE:a"])
        # Sync linked FIGURE:d → 피규어; clear it so this row is a plain orphan.
        figure = next(t for t in self.lib.terms()["product_categories"] if t["name"] == "피규어")
        self.lib.assign(["FIGURE:d"], "product_categories", figure["id"], remove=True)
        by_id = {item["id"]: item["curated"] for item in self.lib.orphan_items({"FIGURE:b"})}
        self.assertTrue(by_id["FIGURE:a"])  # a source of a draft
        self.assertFalse(by_id["FIGURE:d"])
        result = self.lib.delete_orphans({"FIGURE:b"})
        self.assertIn("FIGURE:a", self.lib.items_by_id(["FIGURE:a"]))
        self.assertEqual([item["id"] for item in result["kept_curated"]], ["FIGURE:a"])


class DraftsPageTests(DraftCase):
    def get(self, path="/drafts"):
        with patch.dict(review.app.config, {"LIBRARY_PATH": str(self.path)}):
            return review.app.test_client().get(path)

    def test_page_shows_each_sources_photo_and_a_placeholder_without_one(self):
        create_draft(self.lib, ["FIGURE:a", "FIGURE:b"])
        response = self.get()
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('src="https://cdn.example.com/a.jpg"', html)
        self.assertIn('referrerpolicy="no-referrer"', html)
        self.assertIn("card-thumb-empty", html)  # FIGURE:b has no photo
        self.assertIn("한글 제목", html)

    def test_published_drafts_show_photos_too(self):
        publish_draft(self.lib, create_draft(self.lib, ["FIGURE:a"]))
        html = self.get("/drafts?status=POSTED").get_data(as_text=True)
        self.assertIn('src="https://cdn.example.com/a.jpg"', html)

    def test_pending_schema_upgrade_shows_the_upgrade_page(self):
        with patch.object(review, "Library", side_effect=SchemaError("DB 업그레이드가 필요합니다.")):
            response = review.app.test_client().get("/drafts")
        self.assertEqual(response.status_code, 503)
        self.assertIn("업그레이드", response.get_data(as_text=True))

    def test_publish_route_flashes_a_firestore_warning(self):
        draft_id = create_draft(self.lib, ["FIGURE:a"])
        with patch.dict(review.app.config, {"LIBRARY_PATH": str(self.path)}), \
                patch.object(review, "db", return_value=Mock()), \
                patch.object(review, "publish_draft", return_value=["Firestore 기록 실패"]):
            response = review.app.test_client().post(f"/drafts/{draft_id}/publish", follow_redirects=True)
        self.assertIn("Firestore 기록 실패", response.get_data(as_text=True))

    def test_create_route_makes_a_local_draft_from_inbox_selection(self):
        with patch.dict(review.app.config, {"LIBRARY_PATH": str(self.path)}), \
                patch.object(review, "db", return_value=Mock()):
            response = review.app.test_client().post("/drafts", data={"source_ids": ["FIGURE:a", "FIGURE:b"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(list_drafts(self.lib)), 1)

    def test_page_lists_linked_works_for_by_work_drafts(self):
        work = self.lib.save_term("works", "프리렌")
        self.lib.assign(["FIGURE:a"], "works", work)
        html = self.get().get_data(as_text=True)
        self.assertIn('name="work_id"', html)
        self.assertIn(f'value="{work}"', html)
        self.assertIn("프리렌", html)
        self.assertIn("ai-draft-form", html)
        self.assertIn("ai-draft-busy", html)

    def test_by_work_route_requires_work_id_and_passes_it_through(self):
        with patch.dict(review.app.config, {"LIBRARY_PATH": str(self.path)}):
            client = review.app.test_client()
            missing = client.post("/drafts/ai/by-work", follow_redirects=True)
            self.assertIn("작품을 선택", missing.get_data(as_text=True))
            with patch.object(review, "create_work_drafts", return_value=[("FIGURE", 1, None)]) as create:
                ok = client.post("/drafts/ai/by-work", data={"work_id": "7"}, follow_redirects=True)
            create.assert_called_once()
            self.assertEqual(create.call_args.kwargs["work_id"], 7)
            self.assertIn("작품별 글 1개", ok.get_data(as_text=True))


class DeleteFirestoreDraftsTests(unittest.TestCase):
    def snapshots(self, *statuses):
        return [SimpleNamespace(id=f"d{i}", reference=Mock(), to_dict=lambda s=s: {
            "status": s, "sourceIds": ["FIGURE:a"], "body": "본문", "createdAt": datetime(2026, 9, 19, tzinfo=timezone.utc)})
            for i, s in enumerate(statuses)]

    def db(self, snapshots):
        db = Mock()
        db.collection.return_value.stream.return_value = iter(snapshots)
        return db

    def test_dry_run_reports_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            db = self.db(self.snapshots("DRAFT", "DRAFT"))
            result = delete_firestore_drafts.delete_drafts(db, dry_run=True, backup_dir=Path(directory))
            self.assertEqual((result["matched"], result["deleted"], result["statuses"]), (2, 0, {"DRAFT": 2}))
            self.assertEqual(list(Path(directory).iterdir()), [])
        db.batch.assert_not_called()

    def test_backup_is_written_before_the_batch_delete(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            snapshots = self.snapshots("DRAFT", "DRAFT", "DRAFT")
            db = self.db(snapshots)
            result = delete_firestore_drafts.delete_drafts(db, backup_dir=Path(directory))
            saved = json.loads(Path(result["backup"]).read_text(encoding="utf-8"))
        self.assertEqual([entry["id"] for entry in saved], ["d0", "d1", "d2"])
        self.assertEqual(saved[0]["createdAt"], "2026-09-19T00:00:00+00:00")
        self.assertEqual(result["deleted"], 3)
        batch = db.batch.return_value
        self.assertEqual(batch.delete.call_count, 3)
        batch.commit.assert_called_once()

    def test_failed_backup_deletes_nothing(self):
        db = self.db(self.snapshots("DRAFT"))
        with patch.object(delete_firestore_drafts, "export_drafts", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                delete_firestore_drafts.delete_drafts(db)
        db.batch.assert_not_called()

    def test_published_drafts_need_an_explicit_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            db = self.db(self.snapshots("DRAFT", "POSTED"))
            with self.assertRaisesRegex(ValueError, "--include-posted"):
                delete_firestore_drafts.delete_drafts(db, backup_dir=Path(directory))
            db.batch.assert_not_called()
            db = self.db(self.snapshots("DRAFT", "POSTED"))
            self.assertEqual(delete_firestore_drafts.delete_drafts(
                db, include_posted=True, backup_dir=Path(directory))["deleted"], 2)


if __name__ == "__main__":
    unittest.main()
