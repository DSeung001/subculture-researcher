"""Offline checks for detail skipping, pagination, force refresh, image backfill,
untitled leftover cleanup, keyword matching and the inbox period filter."""

import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

from subculture.web import app as review
from subculture.collection.application import image_backfill
from subculture.collection.infrastructure.collectors import json_api
from subculture.collection.infrastructure.collectors.common import RobotsDenied
from subculture.collection.infrastructure.collectors.html_links import html_items
from subculture.collection.infrastructure.collectors.http import page_url
from subculture.shared.content_model import content_ref
from subculture.shared.untitled_content import UNTITLED_TITLE, is_untitled_laftel_home, is_untitled_leftover
from subculture.collection.infrastructure.content_store import ContentStore
from subculture.collection.application.untitled_cleanup import delete_untitled_x_contents
from subculture.collection.domain.content_rules import doc_id
from subculture.library.application.catalog import load_catalog
from subculture.library.domain.keywords import compile_works, match_keyword, match_works, normalized
from subculture.collection.infrastructure.sources_config import load_sources

SOURCES = {source["name"]: source for source in load_sources()}
NOW = datetime.now(timezone.utc)


def stored(url, **fields):
    """A Firestore snapshot as the URL index sees it."""
    return SimpleNamespace(
        id=doc_id(url), reference=Mock(),
        to_dict=lambda: {"url": url, "status": "NEW", **fields},
    )


def store_with(*snapshots):
    db = Mock()
    db.collection_group.return_value.select.return_value.stream.return_value = iter(snapshots)
    return ContentStore(db)


class NeedsDetailTests(unittest.TestCase):
    URL = "https://s.example.com/p/1"

    def test_dry_run_and_unknown_url_always_fetch(self):
        self.assertTrue(ContentStore(None).needs_detail(self.URL, product_mode=True))
        self.assertTrue(store_with().needs_detail(self.URL, product_mode=True))

    def test_photo_only_page_is_skipped_once_it_has_a_photo(self):
        store = store_with(stored(self.URL, imageUrl="https://cdn.example.com/a.jpg"))
        self.assertFalse(store.needs_detail(self.URL))

    def test_photo_less_page_is_retried_only_after_the_refresh_window(self):
        recent = store_with(stored(self.URL, detailCheckedAt=NOW - timedelta(hours=1)))
        old = store_with(stored(self.URL, detailCheckedAt=NOW - timedelta(hours=100)))
        legacy = store_with(stored(self.URL))  # no stamp: check it once
        self.assertFalse(recent.needs_detail(self.URL, refresh_hours=72))
        self.assertTrue(old.needs_detail(self.URL, refresh_hours=72))
        self.assertTrue(legacy.needs_detail(self.URL, refresh_hours=72))

    def test_product_page_refreshes_on_schedule_even_with_a_photo(self):
        fresh = store_with(stored(self.URL, imageUrl="https://c.example.com/a.jpg", price=100,
                                  productCheckedAt=NOW - timedelta(hours=2)))
        stale = store_with(stored(self.URL, imageUrl="https://c.example.com/a.jpg", price=100,
                                  productCheckedAt=NOW - timedelta(hours=200)))
        self.assertFalse(fresh.needs_detail(self.URL, product_mode=True, refresh_hours=72))
        self.assertTrue(stale.needs_detail(self.URL, product_mode=True, refresh_hours=72))

    def test_missing_detail_gallery_forces_one_backfill(self):
        fresh = store_with(stored(
            self.URL, imageUrl="https://c.example.com/a.jpg", price=100,
            productCheckedAt=NOW - timedelta(hours=2),
        ))
        filled = store_with(stored(
            self.URL, imageUrl="https://c.example.com/a.jpg", price=100,
            detailImageUrls=["https://c.example.com/d.jpg"],
            productCheckedAt=NOW - timedelta(hours=2),
        ))
        empty_checked = store_with(stored(
            self.URL, imageUrl="https://c.example.com/a.jpg", price=100,
            detailImageUrls=[],
            productCheckedAt=NOW - timedelta(hours=2),
        ))
        self.assertTrue(fresh.needs_detail(
            self.URL, product_mode=True, refresh_hours=72, want_detail_images=True,
        ))
        self.assertFalse(filled.needs_detail(
            self.URL, product_mode=True, refresh_hours=72, want_detail_images=True,
        ))
        self.assertFalse(empty_checked.needs_detail(
            self.URL, product_mode=True, refresh_hours=72, want_detail_images=True,
        ))

    def test_zero_refresh_hours_turns_skipping_off(self):
        store = store_with(stored(self.URL, imageUrl="https://c.example.com/a.jpg"))
        self.assertTrue(store.needs_detail(self.URL, refresh_hours=0))

    def test_index_reads_only_the_needed_fields(self):
        store = store_with()
        store.db.collection_group.return_value.select.assert_called_once()
        fields = store.db.collection_group.return_value.select.call_args.args[0]
        self.assertIn("imageUrl", fields)
        self.assertIn("detailImageUrls", fields)
        self.assertNotIn("summary", fields)


class ContentStoreEngagementFieldTests(unittest.TestCase):
    """View/like counts, their velocities and AniList signals are no longer stored."""
    URL = "https://s.example.com/velocity"
    DROPPED = ("viewCountVelocity", "likeCountVelocity", "viewCountCheckedAt", "likeCountCheckedAt",
               "trendingVelocity", "popularityVelocity", "signalCheckedAt")

    def test_resave_never_writes_counts_or_velocities(self):
        store = store_with(stored(self.URL, viewCount=100, viewCountCheckedAt=NOW - timedelta(hours=2)))
        result = store.save({"url": self.URL, "category": "FIGURE", "viewCount": 300, "likeCount": 5,
                             "trending": 30})
        store.by_url[self.URL][0]["ref"].update.assert_not_called()
        self.assertEqual(result["updated"], 0)

    def test_a_new_document_gets_no_derived_engagement_fields(self):
        store = ContentStore(None)
        store.save({"url": self.URL, "category": "FIGURE", "title": "t"})
        saved = store.preview[0]
        for field in ("viewCount", "likeCount", *self.DROPPED):
            self.assertNotIn(field, saved)

class DetailSkipInHtmlItemsTests(unittest.TestCase):
    LISTING = "https://s.example.com/list"
    PAGES = {
        LISTING: '<a href="/p/1">상품 이름 하나</a><a href="/p/2">상품 이름 둘</a>',
        "https://s.example.com/p/1": '<meta property="og:image" content="https://cdn.example.com/1.jpg">예약 12,000원',
        "https://s.example.com/p/2": '<meta property="og:image" content="https://cdn.example.com/2.jpg">예약 13,000원',
    }
    SOURCE = {"name": "shop", "url": LISTING, "link_selector": "a", "product_mode": True,
              "respect_robots": False}

    def run_items(self, store):
        fetched = []

        def fake_get_html(url, policy, timeout=15, source=None):
            fetched.append(url)
            return self.PAGES[url], url
        with patch("subculture.collection.infrastructure.collectors.html_links.get_html", side_effect=fake_get_html), \
                patch("subculture.collection.infrastructure.collectors.html_links.RobotsPolicy"):
            return list(html_items(self.SOURCE, store)), fetched

    def test_known_fresh_product_skips_its_detail_page_but_stays_listed(self):
        store = Mock()
        store.needs_detail.side_effect = lambda url, **kw: url.endswith("/2")
        items, fetched = self.run_items(store)
        self.assertEqual([i["url"] for i in items], ["https://s.example.com/p/1", "https://s.example.com/p/2"])
        self.assertNotIn("https://s.example.com/p/1", fetched)
        self.assertIn("https://s.example.com/p/2", fetched)
        self.assertNotIn("price", items[0])
        self.assertEqual(items[1]["price"], 13000)
        self.assertIn("detailCheckedAt", items[1])

    def test_without_a_store_every_detail_page_is_fetched(self):
        items, fetched = self.run_items(None)
        self.assertEqual(len(fetched), 3)  # list + 2 details
        self.assertEqual(len(items), 2)


class PaginationTests(unittest.TestCase):
    def source(self, **extra):
        return {"url": "https://s.example.com/list?cat=8", "link_selector": "a", "page_param": "page",
                "max_pages": 3, "respect_robots": False, **extra}

    def run_items(self, source, pages):
        requested = []

        def fake_get_html(url, policy, timeout=15, source=None):
            requested.append(url)
            return pages[url], url
        with patch("subculture.collection.infrastructure.collectors.html_links.get_html", side_effect=fake_get_html), \
                patch("subculture.collection.infrastructure.collectors.html_links.RobotsPolicy"):
            return list(html_items(source)), requested

    def test_page_url_keeps_page_one_and_replaces_the_param(self):
        self.assertEqual(page_url("https://a.example/l?cat=8", "page", 1), "https://a.example/l?cat=8")
        self.assertEqual(page_url("https://a.example/l?cat=8", "page", 2), "https://a.example/l?cat=8&page=2")
        self.assertEqual(page_url("https://a.example/l?page=9&cat=8", "page", 3), "https://a.example/l?cat=8&page=3")
        self.assertEqual(page_url("https://a.example/l", None, 2), "https://a.example/l")

    def test_pages_are_followed_until_max_pages(self):
        pages = {
            "https://s.example.com/list?cat=8": '<a href="/a/1">기사 제목 하나</a><a href="/a/2">기사 제목 둘</a>',
            "https://s.example.com/list?cat=8&page=2": '<a href="/a/3">기사 제목 셋</a>',
            "https://s.example.com/list?cat=8&page=3": '<a href="/a/4">기사 제목 넷</a>',
        }
        items, requested = self.run_items(self.source(max_pages=2), pages)
        self.assertEqual(len(items), 3)
        self.assertEqual(len(requested), 2)

    def test_stops_when_a_page_adds_nothing_new(self):
        same = '<a href="/a/1">기사 제목 하나</a>'
        pages = {"https://s.example.com/list?cat=8": same, "https://s.example.com/list?cat=8&page=2": same}
        items, requested = self.run_items(self.source(), pages)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(requested), 2)  # page 3 was never asked for

    def test_max_items_cuts_across_pages(self):
        pages = {
            "https://s.example.com/list?cat=8": '<a href="/a/1">기사 제목 하나</a><a href="/a/2">기사 제목 둘</a>',
            "https://s.example.com/list?cat=8&page=2": '<a href="/a/3">기사 제목 셋</a>',
        }
        items, requested = self.run_items(self.source(max_items=3), pages)
        self.assertEqual(len(items), 3)
        self.assertEqual(len(requested), 2)

    def test_without_page_param_only_the_first_page_is_read(self):
        source = self.source()
        del source["page_param"]
        pages = {"https://s.example.com/list?cat=8": '<a href="/a/1">기사 제목 하나</a>'}
        items, requested = self.run_items(source, pages)
        self.assertEqual((len(items), len(requested)), (1, 1))

    def test_later_page_disallowed_by_robots_keeps_earlier_results(self):
        first = "https://s.example.com/list?cat=8"

        def fake_get_html(url, policy, timeout=15, source=None):
            if url != first:
                raise RobotsDenied("page 2 disallowed")
            return '<a href="/a/1">기사 제목 하나</a>', url
        with patch("subculture.collection.infrastructure.collectors.html_links.get_html", side_effect=fake_get_html), \
                patch("subculture.collection.infrastructure.collectors.html_links.RobotsPolicy"):
            items = list(html_items(self.source(), None))
        self.assertEqual(len(items), 1)

    def test_first_page_disallowed_by_robots_still_raises(self):
        with patch("subculture.collection.infrastructure.collectors.html_links.get_html", side_effect=RobotsDenied("no")), \
                patch("subculture.collection.infrastructure.collectors.html_links.RobotsPolicy"):
            with self.assertRaises(RobotsDenied):
                list(html_items(self.source(), None))

    def test_json_api_follows_pages_and_stops_at_page_count(self):
        def response(entries):
            reply = Mock()
            reply.raise_for_status = Mock()
            reply.json.return_value = {"listData": entries, "pageCount": 2}
            return reply
        replies = {
            "https://api.example.com/l?board=1&gotoPage=1": response([{"idx": 1, "title": "하나"}, {"idx": 2, "title": "둘"}]),
            "https://api.example.com/l?board=1&gotoPage=2": response([{"idx": 3, "title": "셋"}]),
        }
        source = {"url": "https://api.example.com/l?board=1&gotoPage=1", "items_path": "listData",
                  "id_field": "idx", "title_field": "title", "page_param": "gotoPage", "max_pages": 4,
                  "page_count_field": "pageCount", "detail_url_template": "https://www.example.com/post/{id}"}
        seen = []

        def fake_get(url, **kwargs):
            seen.append(url)
            return replies[url]
        with patch.object(json_api.requests, "get", side_effect=fake_get):
            items = list(json_api.json_api_items(source))
        self.assertEqual([i["title"] for i in items], ["하나", "둘", "셋"])
        self.assertEqual(len(seen), 2)  # pageCount reached: no third request

    def test_configured_listing_sources_paginate(self):
        for name, param in (("따빼몰 호요버스 굿즈", "page"), ("따빼몰 명조 굿즈", "page"),
                            ("따빼몰 신규입고", "page"), ("따빼몰 신규예약", "page"),
                            ("코믹스아트 신작 상품", "page"), ("코믹스아트 입고 완료 당일 발송", "page"),
                            ("마니아하우스 예약상품", "page"), ("마니아하우스 입고완료", "page"),
                            ("애니메이트 코리아 신상품", "page"), ("Animate Times 굿즈", "p"),
                            ("AGF Korea 공지사항", "gotoPage")):
            with self.subTest(name=name):
                source = SOURCES[name]
                self.assertEqual(source["page_param"], param)
                self.assertGreater(source["max_pages"], 1)
                self.assertGreaterEqual(source["max_items"], 50)
                self.assertNotEqual(page_url(source["url"], param, 2), source["url"])


class FigureFarmTests(unittest.TestCase):
    LISTING = "https://m.figurefarm.net/shop/big_section.php?cno1=1554"
    CARDS = """
    <div class="ffm-product-card"><div class="prdimg"><a href="https://m.figurefarm.net/shop/detail.php?pno=AAA"><img src="https://c.example.com/a.jpg"></a></div>
      <div class="info"><p class="name"><a href="https://m.figurefarm.net/shop/detail.php?pno=AAA">[입고] 블루 아카이브 피규어</a></p></div></div>
    <div class="ffm-product-card"><div class="prdimg"><a href="https://m.figurefarm.net/shop/detail.php?pno=BBB"><img src="https://c.example.com/b.jpg"></a></div>
      <div class="info"><p class="name"><a href="https://m.figurefarm.net/shop/detail.php?pno=BBB">캐릭터 머그컵 세트</a></p></div></div>
    <a href="https://m.figurefarm.net/shop/detail.php?pno=CCC"><img src="https://c.example.com/c.jpg"></a>
    """
    DETAIL = "<title>x</title><meta property='og:title' content='{title}'>예약마감일 : 26년 10월 1일 39,000원"

    def run_items(self, store):
        from subculture.collection.infrastructure.collectors import figurefarm
        fetched = []

        def fake_get_html(url, policy, timeout=15, source=None):
            fetched.append(url)
            if url == self.LISTING:
                return self.CARDS, url
            return self.DETAIL.format(title="피규어 " + url[-3:]), url
        with patch.object(figurefarm, "get_html", side_effect=fake_get_html),                 patch.object(figurefarm, "RobotsPolicy"):
            return list(figurefarm.figurefarm_items({"url": self.LISTING, "max_items": 10}, store)), fetched

    def test_non_figure_list_cards_are_not_fetched(self):
        items, fetched = self.run_items(None)
        self.assertNotIn("https://m.figurefarm.net/shop/detail.php?pno=BBB", fetched)  # mug: rejected from the card name
        self.assertIn("https://m.figurefarm.net/shop/detail.php?pno=CCC", fetched)  # no card name: fall back to the detail page
        self.assertEqual(len(items), 2)

    def test_known_fresh_products_skip_the_detail_page(self):
        store = Mock()
        store.needs_detail.return_value = False
        items, fetched = self.run_items(store)
        self.assertEqual(fetched, [self.LISTING])
        self.assertEqual([i["_errors"] for i in items], [[], []])
        self.assertEqual(items[0]["title"], "[입고] 블루 아카이브 피규어")


class ImageDenyPatternTests(unittest.TestCase):
    def test_site_wide_default_og_image_is_not_a_photo(self):
        from bs4 import BeautifulSoup
        from subculture.collection.infrastructure.collectors.images import detail_image
        source = {"image_deny_patterns": ["^/common/"]}
        page = BeautifulSoup('<meta property="og:image" content="https://prtimes.jp/common/pc_v4/og.png">', "html.parser")
        self.assertIsNone(detail_image(page, "https://prtimes.jp/main/html/rd/p/1.html", source))
        real = BeautifulSoup('<meta property="og:image" content="https://prcdn.freetls.fastly.net/release_image/1/a.jpg?format=jpeg">', "html.parser")
        self.assertTrue(detail_image(real, "https://prtimes.jp/main/html/rd/p/1.html", source).endswith("a.jpg?format=jpeg"))


class ForceRefreshTests(unittest.TestCase):
    def test_run_collection_passes_force_refresh_to_collectors(self):
        from subculture.collection.application import collection_runner
        seen = []

        def fake(db, source, store=None):
            seen.append(source.get("force_refresh"))
            return dict(processed=0, inserted=0, existing=0, updated=0, failed=0)
        with patch.dict(collection_runner.COLLECTORS, {"fake": fake}), \
                patch.object(collection_runner, "ContentStore") as store:
            store.return_value.duplicates.return_value = []
            store.return_value.invalid_urls = []
            collection_runner.run_collection([{"name": "s", "type": "fake"}], db=Mock(), force_refresh=True)
            collection_runner.run_collection([{"name": "s", "type": "fake"}], db=Mock())
        self.assertEqual(seen, [True, None])


def content(doc_id_, **fields):
    return SimpleNamespace(id=doc_id_, reference=Mock(), to_dict=lambda: dict(fields))


class ImageBackfillTests(unittest.TestCase):
    def test_only_missing_photos_are_filled(self):
        source = {"name": "뉴스", "type": "html", "fetch_detail_image": True, "respect_robots": False}
        have = content("a", url="https://x.example/1", imageUrl="https://cdn.example.com/keep.jpg", source="뉴스")
        missing = content("b", url="https://x.example/2", title="기사", source="뉴스")
        video = content("c", url="https://www.youtube.com/watch?v=abcdefghijk", title="PV")  # no longer derived
        nothing = content("d", url="https://x.example/n", title="사진 없음", source="수동 입력")
        db = Mock()
        db.collection_group.return_value.stream.return_value = iter([have, missing, video, nothing])
        page = '<meta property="og:image" content="https://cdn.example.com/2.jpg">'
        with patch.object(image_backfill, "get_html", side_effect=lambda url, *a, **k: (page, url)) as get:
            counts = image_backfill.backfill_images(db, [source])
        have.reference.update.assert_not_called()
        missing.reference.update.assert_called_once_with({"imageUrl": "https://cdn.example.com/2.jpg"})
        video.reference.update.assert_not_called()
        nothing.reference.update.assert_not_called()
        self.assertEqual(get.call_count, 1)
        self.assertEqual((counts["updated"], counts["still_missing"]), (1, 2))

    def test_detail_pages_respect_the_limit_and_missing_photos(self):
        source = {"name": "PR TIMES", "type": "html", "fetch_detail_image": True, "respect_robots": False}
        docs = [content(f"d{i}", url=f"https://n.example.com/a/{i}", title=f"기사 {i}", source="PR TIMES")
                for i in range(3)]
        db = Mock()
        db.collection_group.return_value.stream.return_value = iter(docs)
        pages = {
            "https://n.example.com/a/0": '<meta property="og:image" content="https://cdn.example.com/0.jpg">',
            "https://n.example.com/a/1": "<p>이미지 없음</p>",
        }
        with patch.object(image_backfill, "get_html", side_effect=lambda url, *a, **k: (pages[url], url)):
            counts = image_backfill.backfill_images(db, [source], detail_limit=2)
        docs[0].reference.update.assert_called_once_with({"imageUrl": "https://cdn.example.com/0.jpg"})
        docs[1].reference.update.assert_not_called()
        docs[2].reference.update.assert_not_called()  # beyond the limit
        self.assertEqual((counts["updated"], counts["still_missing"]), (1, 2))

    def test_collect_cli_has_the_backfill_mode(self):
        from subculture.collection.interface import collect_cli as collect
        with patch.object(collect, "get_db", return_value=Mock()), \
                patch.object(collect, "load_sources", return_value=[]), \
                patch.object(collect, "backfill_images") as backfill:
            collect.main(["--backfill-images"])
        backfill.assert_called_once()


class UntitledLaftelTests(unittest.TestCase):
    def test_matches_only_the_bare_home_with_the_placeholder_title(self):
        for url in ("https://laftel.net/", "https://laftel.net", "https://www.laftel.net/"):
            self.assertTrue(is_untitled_laftel_home(url, UNTITLED_TITLE), url)
        self.assertFalse(is_untitled_laftel_home("https://laftel.net/item/3", UNTITLED_TITLE))
        self.assertFalse(is_untitled_laftel_home("https://store.laftel.net/", UNTITLED_TITLE))
        self.assertFalse(is_untitled_laftel_home("https://laftel.net/", "라프텔"))
        self.assertTrue(is_untitled_leftover("https://x.com/u/status/1", UNTITLED_TITLE))

    def test_firestore_cleanup_removes_the_home_and_keeps_products(self):
        def snap(doc_id_, url, title):
            ref = Mock()
            ref.parent.parent.id = "ANIME"
            return SimpleNamespace(id=doc_id_, reference=ref, to_dict=lambda: {"url": url, "title": title})
        home = snap("home", "https://laftel.net/", UNTITLED_TITLE)
        product = snap("p", "https://laftel.net/item/3", UNTITLED_TITLE)
        db = Mock()
        db.collection_group.return_value.stream.return_value = iter([home, product])
        result = delete_untitled_x_contents(db, dry_run=False)
        self.assertEqual(result["matched"], 1)
        home.reference.delete.assert_called_once()
        product.reference.delete.assert_not_called()


class KeywordMatchTests(unittest.TestCase):
    def test_latin_alias_next_to_hangul_or_kana_matches(self):
        for title in ("Bleach넨도로이드", "블리치 BLEACH 피규어", "[예약]BLEACHフィギュア"):
            with self.subTest(title=title):
                self.assertEqual(match_keyword(normalized(title), "BLEACH"), "BLEACH")

    def test_latin_alias_inside_another_word_does_not_match(self):
        for title in ("Bleached hair", "sonebleach", "BLEACH2"):
            with self.subTest(title=title):
                self.assertIsNone(match_keyword(normalized(title), "BLEACH"))

    def test_colon_variants_match_the_same_keyword(self):
        keyword = "붕괴: 스타레일"
        for title in (
            "붕괴:스타레일 반디 피규어",
            "붕괴: 스타레일 아크릴스탠드",
            "붕괴 스타레일 굿즈",
        ):
            with self.subTest(title=title):
                self.assertEqual(match_keyword(normalized(title), keyword), keyword)
        self.assertEqual(
            match_keyword(normalized("Re: 제로부터 시작하는 이세계 생활 4기"), "Re:제로"),
            "Re:제로",
        )

    def test_space_stripped_shop_titles_match_catalog_aliases(self):
        # Shop titles omit or keep spaces; catalog keeps both forms as keywords.
        cases = (
            ("체인소 맨 하이 프리미엄 피규어", "체인소 맨"),
            ("체인소맨 레제 넨도로이드", "체인소맨"),
            ("붕괴스타레일 효광 미토스", "붕괴스타레일"),
            ("귀멸의칼날 토미오카기유", "귀멸의칼날"),
            ("블루아카이브 아로나", "블루아카이브"),
        )
        for title, keyword in cases:
            with self.subTest(title=title, keyword=keyword):
                self.assertEqual(match_keyword(normalized(title), keyword), keyword)

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.compiled = compile_works(cls.catalog)
        cls.names = {entry["name"] for entry in cls.catalog}

    def linker(self, titles):
        """(linked(work name) -> matching item ids, number of titles no work matched)."""
        works = {key: match_works({"title": title}, self.compiled) for key, title in titles.items()}

        def linked(name):
            self.assertIn(name, self.names)
            return {f"FIGURE:{key}" for key, found in works.items() if name in found}

        return linked, sum(1 for found in works.values() if not found)

    def test_genshin_is_in_the_catalog_and_links_hoyoverse_titles(self):
        self.assertEqual(match_works({"title": "[원신] 클리어 파일"}, self.compiled), ["원신"])

    def test_azur_lane_is_in_the_catalog_and_links_shop_titles(self):
        self.assertEqual(
            match_works({"title": "[예약]벽람항로 아주르 레인 키어사지 피규어"}, self.compiled), ["벽람항로"],
        )

    def test_catalog_links_spaced_variants_and_new_ips_without_false_hits(self):
        titles = {
            "love": "(26년 12월 발매) 공식 러브 라이브 찻집 시리즈 아크릴 스탠드 굿즈",
            "titan": "[예약]진격의 거인 넨도로이드 라이너 브라운 (재판)",
            "collab": "메가하우스 Lucrea 아이카츠 x 프리파라 THE MOVIE",
            "zoid": "Zoid x Patraber – Code Name B.U.D.D.Y. - 1/35 스케일 잉그램",
            "store": "히메노짱 × 빌리지 뱅가드 한정 콜라보레이션 굿즈 출시!!",
            "stage": "에일리언 스테이지 아크릴 스탠드",
        }
        linked, _ = self.linker(titles)
        self.assertEqual(linked("러브라이브"), {"FIGURE:love"})
        self.assertEqual(linked("진격의 거인"), {"FIGURE:titan"})
        self.assertEqual(linked("아이카츠"), {"FIGURE:collab"})
        self.assertEqual(linked("프리파라"), {"FIGURE:collab"})
        self.assertEqual(linked("조이드"), {"FIGURE:zoid"})
        self.assertEqual(linked("기동경찰 패트레이버"), {"FIGURE:zoid"})
        self.assertEqual(linked("카드파이트!! 뱅가드"), set())
        self.assertEqual(linked("에일리언 (영화)"), set())
        self.assertEqual(linked("에일리언 스테이지"), {"FIGURE:stage"})

    def test_catalog_links_limbus_and_japanese_titled_anime_without_false_hits(self):
        titles = {
            "limbus": "【굿즈-키홀더】 Limbus Company 아크릴 키홀더 G 히스클리프",
            "hanakimi": "佐野と踊りたいなあ｜TVアニメ「#花ざかりの君たちへ」第2期 #HanaKimi #anime",
            "arya": "[입고완료] 테니톨톨 가끔씩툭하고러시아어로부끄러워하는옆자리의아랴양 젖소 코스튬 ver.",
            "multi": "『グレンラガン』『ノゲノラ』『着せ恋』からヨーコや白、喜多川海夢のスタチューが発表！",
            "original": "[예약판매] 네이티브 사랑과 번영의 천사 프리엘 by 마타로 핑크캣 0432",
        }
        linked, unclassified = self.linker(titles)
        self.assertEqual(linked("림버스 컴퍼니"), {"FIGURE:limbus"})
        self.assertEqual(linked("아름다운 그대에게"), {"FIGURE:hanakimi"})
        self.assertEqual(linked("가끔씩 툭하고 러시아어로 부끄러워하는 옆자리의 아랴 양"), {"FIGURE:arya"})
        self.assertEqual(linked("천원돌파 그렌라간"), {"FIGURE:multi"})
        self.assertEqual(linked("노 게임 노 라이프"), {"FIGURE:multi"})
        self.assertEqual(linked("그 비스크 돌은 사랑을 한다"), {"FIGURE:multi"})
        self.assertEqual(unclassified, 1)

    def test_catalog_links_unclassified_shop_titles_without_short_alias_hits(self):
        titles = {
            "shin": "[예약판매] 짱구는못말려 액션가면 프라모델",
            "hunter": "넨도로이드 몬스터헌터 얀쿡쿡",
            "kaguya": "초가구야공주! 카구야 콜라보 라이브 ver.",
            "trigun": "넨도로이드 트라이건 밧슈더스탬피드",
            "steins": "슈타인즈게이트 마키세크리스 레이싱 ver.",
            "jojo": "죠죠의 기묘한 모험 스톤 오션 엔리코",
            "spy": "【굿즈-스티커】 SPY x FAMILY 애니판 트레이딩 스티커",
            "link": "시광대리인 공식 정품 굿즈 리톈시",
            "iruma": "악마에 입문했습니다! 이루마 군 아크릴스탠드",
            "zaku": "ROBOT혼 SIDE MS 샤아 전용 자쿠 ver. ANIM",
            "koujaku": "드라마티컬머더 코우자쿠",
            "original": "네이티브 사랑과 번영의 천사 프리엘 by 마타로",
            "notice": "AGF KOREA 2025 스폰서 공개",
        }
        linked, unclassified = self.linker(titles)
        self.assertEqual(linked("크레용 신짱"), {"FIGURE:shin"})
        self.assertEqual(linked("몬스터 헌터"), {"FIGURE:hunter"})
        self.assertEqual(linked("초 가구야 공주"), {"FIGURE:kaguya"})
        self.assertEqual(linked("트라이건"), {"FIGURE:trigun"})
        self.assertEqual(linked("슈타인즈 게이트"), {"FIGURE:steins"})
        self.assertEqual(linked("죠죠의 기묘한 모험"), {"FIGURE:jojo"})
        self.assertEqual(linked("SPY×FAMILY"), {"FIGURE:spy"})
        self.assertEqual(linked("시간대리인"), {"FIGURE:link"})
        self.assertEqual(linked("마법에 걸렸습니다! 이루마군"), {"FIGURE:iruma"})
        self.assertEqual(linked("기동전사 건담"), {"FIGURE:zaku"})
        self.assertEqual(linked("드라마티컬 머더"), {"FIGURE:koujaku"})
        self.assertNotIn("FIGURE:koujaku", linked("기동전사 건담"))
        self.assertEqual(unclassified, 2)

    def test_catalog_aliases_are_plain_strings(self):
        for entry in self.catalog:
            for alias in entry.get("aliases") or []:
                self.assertIsInstance(alias, str, entry["name"])

    def test_unquoted_colon_alias_is_rejected_instead_of_stored_as_a_dict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.yaml"
            path.write_text("works:\n  - name: 퍼니싱\n    aliases:\n      - Punishing: Gray Raven\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "따옴표"):
                load_catalog(path)


class InboxPeriodTests(unittest.TestCase):
    def filters(self, query=""):
        with review.app.test_request_context("/" + query):
            return review.current_filters()

    def test_defaults_are_new_items_of_the_last_14_days(self):
        filters = self.filters()
        self.assertEqual((filters["status"], filters["days"]), ("NEW", "14"))

    def test_days_accepts_known_choices_only(self):
        self.assertEqual(self.filters("?days=ALL")["days"], "ALL")
        self.assertEqual(self.filters("?days=30")["days"], "30")
        self.assertEqual(self.filters("?days=abc")["days"], "14")
        self.assertEqual(self.filters("?days=99999")["days"], "14")
        self.assertEqual(self.filters("?status=ACTIVE")["status"], "ACTIVE")

    def test_period_becomes_a_collected_at_range_on_the_query(self):
        query = Mock()
        query.where.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.stream.return_value = []
        with patch.object(review, "contents_query", return_value=query):
            review.fetch_contents_page("", "ALL", "7")
        field_filter = query.where.call_args.kwargs["filter"]
        self.assertEqual((field_filter.field_path, field_filter.op_string), ("collectedAt", ">="))
        self.assertLess(abs((datetime.now(timezone.utc) - field_filter.value) - timedelta(days=7)), timedelta(minutes=1))

    def test_all_period_adds_no_range_filter(self):
        query = Mock()
        query.order_by.return_value = query
        query.limit.return_value = query
        query.stream.return_value = []
        with patch.object(review, "contents_query", return_value=query):
            review.fetch_contents_page("", "ALL", "ALL")
        query.where.assert_not_called()

    def test_page_shows_period_chips(self):
        with patch.object(review, "fetch_contents_page", return_value=([], False, "")) as fetch, \
                patch.object(review, "fetch_recommended_items", return_value=[]):
            html = review.app.test_client().get("/inbox").get_data(as_text=True)
        self.assertEqual(fetch.call_args.args[2], "14")
        page = BeautifulSoup(html, "html.parser")
        period_group = page.find("span", string="수집 기간").parent
        links = period_group.select("a[href]")
        periods = {parse_qs(urlsplit(link["href"]).query)["days"][0] for link in links}
        self.assertEqual(periods, {"7", "14", "30", "ALL"})
        active = [parse_qs(urlsplit(link["href"]).query)["days"][0]
                  for link in links if "active" in link.get("class", [])]
        self.assertEqual(active, ["14"])


class RecommendedItemsTests(unittest.TestCase):
    """`fetch_recommended_items` is the inbox's filter-independent "post this next" pool."""

    CLIENT = Client(project="offline-tests", credentials=AnonymousCredentials())

    def make_snapshot(self, source_id, **fields):
        ref = content_ref(self.CLIENT, source_id)
        data = {
            "title": "테스트 항목", "url": f"https://example.com/{ref.id}", "source": "테스트 소스",
            "category": source_id.split(":")[0], "collectedAt": NOW, "postedAt": None, "status": "NEW",
            **fields,
        }
        return SimpleNamespace(id=ref.id, reference=ref, to_dict=lambda: data)

    def query_returning(self, *snapshots):
        query = Mock()
        query.where.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.stream.return_value = list(snapshots)
        db = Mock()
        db.collection_group.return_value = query
        return db, query

    def test_excludes_ignored_and_already_posted_items(self):
        keep = self.make_snapshot("FIGURE:keep", status="NEW")
        ignored = self.make_snapshot("FIGURE:ignored", status="IGNORE")
        posted = self.make_snapshot("FIGURE:posted", postedAt=NOW)
        db, _ = self.query_returning(keep, ignored, posted)
        with patch.object(review, "db", return_value=db):
            items = review.fetch_recommended_items()
        self.assertEqual([item["_id"] for item in items], ["keep"])

    def test_sorted_by_score_descending_and_capped_at_the_recommended_count(self):
        snapshots = [
            # Freshness-only items, newest first in Firestore order - the boring baseline.
            self.make_snapshot(f"FIGURE:{i}", collectedAt=NOW - timedelta(hours=i))
            for i in range(review.RECOMMENDATION_COUNT + 5)
        ]
        # An older, last-in-Firestore-order item that still outscores every fresher one
        # on real signal strength, so it must land first - proving this is a score sort,
        # not just a pass-through of the collectedAt-descending Firestore order.
        standout = self.make_snapshot(
            "FIGURE:standout", collectedAt=NOW - timedelta(days=3), title="스탠드아웃 한정판 피규어",
            sourceTier="OFFICIAL", region="KR",
            entityType="PRODUCT", saleStatus="PREORDER",
        )
        db, _ = self.query_returning(*snapshots, standout)
        with patch.object(review, "db", return_value=db):
            items = review.fetch_recommended_items()
        self.assertEqual(len(items), review.RECOMMENDATION_COUNT)
        self.assertEqual(items[0]["_id"], "standout")
        scores = [item["_view"]["signal_score"] for item in items]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_query_is_bounded_by_days_and_limit_independent_of_page_filters(self):
        db, query = self.query_returning()
        with patch.object(review, "db", return_value=db):
            review.fetch_recommended_items(days=9, limit=50)
        query.limit.assert_called_once_with(50)
        field_filter = query.where.call_args.kwargs["filter"]
        self.assertEqual((field_filter.field_path, field_filter.op_string), ("collectedAt", ">="))
        self.assertLess(abs((datetime.now(timezone.utc) - field_filter.value) - timedelta(days=9)), timedelta(minutes=1))


if __name__ == "__main__":
    unittest.main()
