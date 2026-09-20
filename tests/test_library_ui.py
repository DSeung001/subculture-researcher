"""Offline checks for the 작품·기획 exploration UI (filter chips, deadlines, paging)."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from subculture.library.domain.taxonomy import FILTER_KEYS
from subculture.library.infrastructure.local_library import Library


def snapshot(doc_id, title="Frieren 피규어 예약", category="FIGURE", **fields):
    return SimpleNamespace(
        id=doc_id,
        reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id=category))),
        to_dict=lambda: {"title": title, "url": f"https://example.com/{doc_id}", "source": "Shop", **fields},
    )


def cloud(*snapshots):
    db = Mock()
    db.collection_group.return_value.stream.return_value = iter(snapshots)
    return db


class LibraryUiTests(unittest.TestCase):
    def setUp(self):
        from subculture.web.app import app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.old_config = {k: app.config.get(k) for k in ("LIBRARY_PATH", "LIBRARY_CLOUD_DB", "TESTING")}
        self.addCleanup(lambda: app.config.update(self.old_config))
        app.config.update(TESTING=True, LIBRARY_PATH=self.path,
                          LIBRARY_CLOUD_DB=Mock(side_effect=AssertionError("offline page used the cloud")))
        self.app = app
        self.client = app.test_client()
        self.lib = Library(self.path)

    def test_items_are_listed_newest_collected_first(self):
        # One sync stamps every row with the same synced_at, so the order has to come from the document.
        self.lib.sync(cloud(
            snapshot("old", "오래된 소식", collectedAt="2026-09-01T00:00:00+00:00"),
            snapshot("none", "수집 시각 없음"),
            snapshot("new", "새 소식", collectedAt="2026-09-19T12:30:00+00:00"),
            snapshot("mid", "중간 소식", collectedAt="2026-09-10T08:00:00+00:00"),
        ))
        rows, total = self.lib.items({})
        self.assertEqual(total, 4)
        self.assertEqual([row["id"] for row in rows],
                         ["FIGURE:new", "FIGURE:mid", "FIGURE:old", "FIGURE:none"])
        page = self.client.get("/library").get_data(as_text=True)
        self.assertLess(page.index("새 소식"), page.index("오래된 소식"))

    def test_the_app_opens_on_the_work_planning_page_and_the_inbox_moved(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 302)
        self.assertTrue(home.headers["Location"].endswith("/library"))
        landing = self.client.get("/", follow_redirects=True)
        self.assertEqual(landing.status_code, 200)
        self.assertIn('topnav-link active', landing.get_data(as_text=True))
        self.assertEqual(self.app.url_map.bind("localhost").match("/inbox")[0], "index")

    def test_active_filter_chips_drop_only_their_own_condition(self):
        from subculture.library.interface.routes import active_filters
        work = self.lib.save_term("works", "프리렌")
        filters = {**dict.fromkeys(FILTER_KEYS, ""), "works": str(work), "q": "피규어", "unclassified": "1"}
        with self.app.test_request_context():
            chips = active_filters(filters, self.lib.terms(), collection_id=7)
        by_label = {c["label"]: c for c in chips}
        self.assertEqual(by_label["작품·IP"]["value"], "프리렌")
        self.assertEqual(by_label["검색"]["value"], "피규어")
        self.assertEqual(by_label["작품"]["value"], "미분류만")
        self.assertEqual(len(chips), 3)
        without_search = by_label["검색"]["remove_url"]
        self.assertIn(f"works={work}", without_search)
        self.assertIn("unclassified=1", without_search)
        self.assertIn("collection=7", without_search)
        self.assertNotIn("q=", without_search)
        with self.app.test_request_context():
            self.assertEqual(active_filters(dict.fromkeys(FILTER_KEYS, ""), self.lib.terms()), [])

    def test_page_shows_chips_and_reset_only_when_filtered(self):
        self.lib.sync(cloud(snapshot("a")))
        plain = self.client.get("/library").get_data(as_text=True)
        self.assertNotIn("filter-chip", plain)
        self.assertNotIn("초기화", plain)
        filtered = self.client.get("/library?q=Frieren").get_data(as_text=True)
        self.assertIn("filter-chip", filtered)
        self.assertIn("초기화", filtered)
        self.assertNotIn("저장 필터", filtered)

    def test_past_deadline_is_marked_and_sale_status_is_labelled(self):
        product = {"entityType": "PRODUCT", "shop": "따빼몰", "currency": "KRW"}
        self.lib.sync(cloud(
            snapshot("old", preorderEndAt="2000-01-01", saleStatus="PREORDER", price=12000, **product),
            snapshot("future", preorderEndAt="2999-01-01", saleStatus="SOLD_OUT", **product),
        ))
        html = self.client.get("/library").get_data(as_text=True)
        self.assertEqual(html.count("(마감 지남)"), 1)
        self.assertIn("예약중", html)
        self.assertIn("품절", html)
        self.assertIn("12,000원", html)

    def test_pager_appears_only_beyond_one_page(self):
        self.lib.sync(cloud(*[snapshot(f"item{i}") for i in range(51)]))
        html = self.client.get("/library").get_data(as_text=True)
        self.assertIn("51개 소재", html)
        self.assertIn("1 / 2 페이지", html)
        self.assertIn("다음", html)
        second = self.client.get("/library?page=2").get_data(as_text=True)
        self.assertIn("이전", second)
        self.assertNotIn(">다음<", second)
        empty = self.client.get("/library?q=no-such-title").get_data(as_text=True)
        self.assertIn("0개 소재", empty)
        self.assertNotIn('class="pager"', empty)

    def test_settings_and_work_pages_use_shared_layout(self):
        work = self.lib.save_term("works", "프리렌", aliases="Frieren")
        for url in ("/library/settings", f"/library/works/{work}"):
            html = self.client.get(url).get_data(as_text=True)
            self.assertIn('class="page-header"', html)
            self.assertNotIn("library-header", html)
            self.assertNotIn("library-message", html)

    def test_work_sidebar_exposes_search_and_alias_data(self):
        self.lib.save_term("works", "프리렌", aliases="Frieren")
        html = self.client.get("/library").get_data(as_text=True)
        self.assertIn('id="work-search"', html)
        self.assertIn('data-search="프리렌 Frieren"', html)
        self.assertIn('id="work-search-empty"', html)
        self.assertIn("library-works-panel", html)


if __name__ == "__main__":
    unittest.main()
