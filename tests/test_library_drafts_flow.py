"""Offline checks for 작품·기획 → 글: the selection bar, the draft route, and the UI that was removed."""

import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from subculture.library.interface import routes as library_routes
from subculture.drafts.domain.posts import DraftPosts
from subculture.drafts.infrastructure.ai_writer import AiWriterError
from subculture.drafts.application.drafts import list_drafts, publish_draft
from subculture.library.infrastructure.models import Draft
from subculture.library.infrastructure.local_library import Library


def snapshot(doc_id, title="Frieren 피규어 예약", category="FIGURE", **fields):
    return SimpleNamespace(
        id=doc_id,
        reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id=category))),
        to_dict=lambda: {"title": title, "url": f"https://example.com/{doc_id}", "source": "Shop",
                         "category": category, **fields},
    )


def cloud(*snapshots):
    db = Mock()
    db.collection_group.return_value.stream.return_value = iter(snapshots)
    return db


class FlowCase(unittest.TestCase):
    def setUp(self):
        from subculture.web.app import app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.old_config = {k: app.config.get(k) for k in ("LIBRARY_PATH", "LIBRARY_CLOUD_DB", "TESTING")}
        self.addCleanup(lambda: app.config.update(self.old_config))
        app.config.update(TESTING=True, LIBRARY_PATH=self.path,
                          LIBRARY_CLOUD_DB=Mock(side_effect=AssertionError("the library flow used the cloud")))
        self.client = app.test_client()
        self.lib = Library(self.path)
        self.lib.sync(cloud(
            snapshot("a", title="첫 소재", imageUrl="https://cdn.example.com/a.jpg"),
            snapshot("b", title="둘째 소재"),
            snapshot("c", title="이미 발행", postedAt="2026-09-01T00:00:00+00:00"),
        ))

    def drafts(self):
        return list_drafts(self.lib, "ALL")

    def create(self, item_ids, mode="plain", **kwargs):
        return self.client.post("/library/drafts", data={
            "item_ids": item_ids, "mode": mode, "next": "/library?q=x"}, **kwargs)


class DraftFlowTests(FlowCase):
    def test_quick_draft_is_made_locally_and_opens_on_the_new_draft(self):
        response = self.create(["FIGURE:a", "FIGURE:b"])
        (draft,) = self.drafts()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"/drafts#draft-{draft['_id']}"))
        self.assertEqual(draft["sourceIds"], ["FIGURE:a", "FIGURE:b"])
        self.assertIn("첫 소재", draft["body"])  # the plain body lists titles, no AI
        self.assertEqual(draft["status"], "DRAFT")

    def test_ai_mode_writes_the_body_with_the_model_and_only_then(self):
        with patch.object(library_routes, "write_draft_posts", return_value=DraftPosts("AI 본문", "AI 댓글")) as writer:
            self.create(["FIGURE:a"], mode="plain")
            writer.assert_not_called()
            self.create(["FIGURE:a", "FIGURE:b"], mode="ai")
        writer.assert_called_once()
        items, _ = writer.call_args.args
        self.assertEqual([item["_id"] for item in items], ["FIGURE:a", "FIGURE:b"])
        posts = {(d["body"], d["reply"]) for d in self.drafts()}
        self.assertIn(("AI 본문", "AI 댓글"), posts)

    def test_the_landing_page_shows_the_new_draft_with_its_photo(self):
        response = self.create(["FIGURE:a"], follow_redirects=True)
        html = response.get_data(as_text=True)
        draft_id = self.drafts()[0]["_id"]
        self.assertIn(f'id="draft-{draft_id}"', html)
        self.assertIn("https://cdn.example.com/a.jpg", html)
        self.assertIn("글을 만들었습니다", html)

    def test_errors_flash_on_the_same_list_and_save_nothing(self):
        cases = {
            "선택": [],
            "20개": [f"FIGURE:{i}" for i in range(21)],
            "없는 자료": ["FIGURE:a", "FIGURE:ghost"],
            "잘못된": ["nocategory"],
        }
        for expected, ids in cases.items():
            with self.subTest(expected=expected):
                response = self.create(ids, follow_redirects=True)
                html = response.get_data(as_text=True)
                self.assertEqual(response.request.path, "/library")
                self.assertIn(expected, html)
        self.assertEqual(self.drafts(), [])

    def test_duplicate_and_reused_news_sources_are_refused(self):
        self.create(["FIGURE:a", "FIGURE:b"])
        again = self.create(["FIGURE:b", "FIGURE:a"], follow_redirects=True)
        self.assertIn("이미 있습니다", again.get_data(as_text=True))
        posted = self.create(["FIGURE:c"], follow_redirects=True)  # a single posted item defaults to NEWS
        self.assertIn("뉴스", posted.get_data(as_text=True))
        self.assertEqual(len(self.drafts()), 1)

    def test_model_failure_flashes_and_saves_nothing(self):
        with patch.object(library_routes, "write_draft_posts", side_effect=AiWriterError("GEMINI_API_KEY 없음")):
            html = self.create(["FIGURE:a"], mode="ai", follow_redirects=True).get_data(as_text=True)
        self.assertIn("GEMINI_API_KEY", html)
        self.assertEqual(self.drafts(), [])

    def test_a_published_source_only_blocks_news_drafts(self):
        self.create(["FIGURE:a", "FIGURE:b"])
        publish_draft(self.lib, self.drafts()[0]["_id"])
        news = self.create(["FIGURE:a"], follow_redirects=True)  # one item defaults to NEWS
        self.assertIn("뉴스", news.get_data(as_text=True))
        self.assertEqual(len(self.drafts()), 1)
        compare = self.create(["FIGURE:a", "FIGURE:c"])  # several items make a COMPARE draft
        self.assertTrue(compare.headers["Location"].endswith(f"#draft-{self.drafts()[0]['_id']}"))
        self.assertEqual(len(self.drafts()), 2)


class SelectionBarTests(FlowCase):
    def test_the_bar_offers_both_buttons_on_the_bulk_form(self):
        html = self.client.get("/library").get_data(as_text=True)
        bar = re.search(r'<div id="library-draft-bar".*?</div>', html, re.S).group(0)
        self.assertIn("hidden", bar)  # shown by library.js once something is selected
        self.assertEqual(bar.count('form="library-bulk"'), 2)
        self.assertEqual(bar.count('formaction="/library/drafts"'), 2)
        self.assertIn('name="mode" value="plain"', bar)
        self.assertRegex(bar, r'name="mode" value="ai"[^>]*data-ai-busy')
        self.assertNotRegex(re.search(r'<button[^>]*value="plain"[^>]*>', bar).group(0), "data-ai-busy")
        self.assertIn('data-max="20"', bar)
        self.assertIn('id="ai-draft-busy"', html)
        # the item checkboxes already belong to that form
        self.assertIn('form="library-bulk" class="library-item-select"', html)

    def test_the_drafts_page_and_the_library_share_the_busy_notice(self):
        self.create(["FIGURE:a"])
        drafts_html = self.client.get("/drafts").get_data(as_text=True)
        self.assertEqual(drafts_html.count('id="ai-draft-busy"'), 1)

    def test_draft_source_rows_no_longer_share_the_inbox_checkbox_class(self):
        self.create(["FIGURE:a"])
        html = self.client.get("/drafts").get_data(as_text=True)
        self.assertIn('class="draft-source-row"', html)
        self.assertNotIn('class="draft-source"', html)  # that class belongs to the inbox checkbox


class RemovedUiTests(FlowCase):
    def test_removed_panels_and_controls_are_gone(self):
        self.lib.save_collection("기획")
        for url in ("/library", "/library?collection=1", "/library/settings"):
            html = self.client.get(url).get_data(as_text=True)
            for gone in ("저장 필터", "필터 저장", "제안입니다", "연결 확정", "소개 순서", "소개 메모",
                         "정보 유형", "태그", 'name="information_types"', 'name="tags"'):
                self.assertNotIn(gone, html, (url, gone))

    def test_product_categories_and_works_remain(self):
        html = self.client.get("/library").get_data(as_text=True)
        self.assertIn("제품 카테고리", html)
        self.assertIn("작품·IP", html)
        settings = self.client.get("/library/settings").get_data(as_text=True)
        self.assertIn("제품 카테고리", settings)

    def test_collection_members_can_still_be_removed(self):
        group = self.lib.save_collection("기획")
        self.lib.add_to_collection(group, ["FIGURE:a", "FIGURE:b"])
        html = self.client.get(f"/library?collection={group}").get_data(as_text=True)
        self.assertEqual(html.count("기획에서 빼기"), 2)
        self.client.post("/library/collections/member", data={
            "collection_id": group, "item_id": "FIGURE:a", "next": f"/library?collection={group}"})
        rows, total = self.lib.items({}, collection_id=group)
        self.assertEqual([r["id"] for r in rows], ["FIGURE:b"])

    def test_removed_routes_are_gone(self):
        self.assertEqual(self.client.post("/library/filters", data={"name": "x"}).status_code, 404)
        self.assertEqual(self.client.get("/library?saved=1").status_code, 200)  # ignored now, no redirect

    def test_terms_that_are_no_longer_offered_are_rejected_and_their_rows_kept(self):
        with self.lib.engine.begin() as con:
            con.exec_driver_sql("INSERT INTO tags VALUES (8, '관심', '관심')")
            con.exec_driver_sql("INSERT INTO item_tags VALUES ('FIGURE:a', 8)")
            con.exec_driver_sql("INSERT INTO saved_filters VALUES (1, '필터', '{}')")
        response = self.client.post("/library/terms/tags", data={"name": "새 태그"}, follow_redirects=True)
        self.assertIn("잘못된 분류", response.get_data(as_text=True))
        rows, _ = self.lib.items({})
        self.assertEqual(len(rows), 3)  # the page still lists items with a hidden tag link
        with self.lib.engine.connect() as con:
            self.assertEqual(con.exec_driver_sql("SELECT COUNT(*) FROM item_tags").scalar(), 1)
            self.assertEqual(con.exec_driver_sql("SELECT COUNT(*) FROM saved_filters").scalar(), 1)
        self.assertEqual(self.client.get("/library").status_code, 200)
        self.assertIsNotNone(Draft)  # models untouched


if __name__ == "__main__":
    unittest.main()
