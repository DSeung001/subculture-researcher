"""Offline checks for detail skipping, pagination, cache versioning, image backfill,
untitled leftover cleanup, keyword matching and the inbox period filter."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from subculture.web import app as review
from subculture.collection.application import image_backfill
from subculture.collection.infrastructure.collectors import anilist, json_api
from subculture.collection.infrastructure.collectors.common import RobotsDenied
from subculture.collection.infrastructure.collectors.html_links import html_items
from subculture.collection.infrastructure.collectors.http import page_url
from subculture.collection.infrastructure.collectors.youtube_feed import youtube_thumbnail
from subculture.shared.untitled_content import UNTITLED_TITLE, is_untitled_laftel_home, is_untitled_leftover
from subculture.collection.infrastructure.content_store import ContentStore
from subculture.collection.application.untitled_cleanup import delete_untitled_x_contents
from subculture.collection.domain.content_rules import doc_id
from subculture.library.infrastructure.local_library import Library
from subculture.library.domain.keywords import match_keyword, normalized
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

    def test_zero_refresh_hours_turns_skipping_off(self):
        store = store_with(stored(self.URL, imageUrl="https://c.example.com/a.jpg"))
        self.assertTrue(store.needs_detail(self.URL, refresh_hours=0))

    def test_index_reads_only_the_needed_fields(self):
        store = store_with()
        store.db.collection_group.return_value.select.assert_called_once()
        fields = store.db.collection_group.return_value.select.call_args.args[0]
        self.assertIn("imageUrl", fields)
        self.assertNotIn("summary", fields)


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


class PrTimesDefaultImageTests(unittest.TestCase):
    def test_site_wide_default_og_image_is_not_a_photo(self):
        from bs4 import BeautifulSoup
        from subculture.collection.infrastructure.collectors.images import detail_image
        source = SOURCES["PR TIMES 만화·애니"]
        page = BeautifulSoup('<meta property="og:image" content="https://prtimes.jp/common/pc_v4/og.png">', "html.parser")
        self.assertIsNone(detail_image(page, "https://prtimes.jp/main/html/rd/p/1.html", source))
        real = BeautifulSoup('<meta property="og:image" content="https://prcdn.freetls.fastly.net/release_image/1/a.jpg?format=jpeg">', "html.parser")
        self.assertTrue(detail_image(real, "https://prtimes.jp/main/html/rd/p/1.html", source).endswith("a.jpg?format=jpeg"))


class AniListCacheTests(unittest.TestCase):
    def db_with(self, **state):
        db = Mock()
        snapshot = db.collection.return_value.document.return_value.get.return_value
        snapshot.exists = True
        snapshot.to_dict.return_value = state
        return db

    def test_current_version_within_window_is_cached(self):
        db = self.db_with(lastSuccessAt=NOW - timedelta(hours=1), version=anilist.CACHE_VERSION)
        self.assertTrue(anilist._cache_is_fresh(db, {"cache_hours": 24})[0])

    def test_older_cache_version_is_not_trusted(self):
        for version in (None, anilist.CACHE_VERSION - 1):
            with self.subTest(version=version):
                db = self.db_with(lastSuccessAt=NOW - timedelta(hours=1), version=version)
                self.assertFalse(anilist._cache_is_fresh(db, {"cache_hours": 24})[0])

    def test_force_refresh_collects_despite_a_fresh_cache(self):
        db = self.db_with(lastSuccessAt=NOW - timedelta(hours=1), version=anilist.CACHE_VERSION)
        with patch.object(anilist, "save_records", return_value={"failed": 0, "processed": 1}) as save, \
                patch.object(anilist, "anilist_items"):
            skipped = anilist.collect_anilist(db, {"cache_hours": 24})
            forced = anilist.collect_anilist(db, {"cache_hours": 24, "force_refresh": True})
        self.assertEqual(skipped["skipped"], 1)
        self.assertEqual(forced["processed"], 1)
        save.assert_called_once()
        written = db.collection.return_value.document.return_value.set.call_args.args[0]
        self.assertEqual(written["version"], anilist.CACHE_VERSION)

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
    def test_youtube_url_gives_a_thumbnail_without_network(self):
        self.assertEqual(youtube_thumbnail("https://www.youtube.com/watch?v=abcdefghijk"),
                         "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg")
        self.assertIsNone(youtube_thumbnail("https://laftel.net/"))
        self.assertIsNone(youtube_thumbnail("https://www.youtube.com/@aniplex"))

    def test_only_missing_photos_are_filled(self):
        have = content("a", url="https://x.example/1", imageUrl="https://cdn.example.com/keep.jpg",
                       source="AniList 트렌딩 애니", externalId="anilist:1")
        video = content("b", url="https://www.youtube.com/watch?v=abcdefghijk", title="PV")
        cover = content("c", url="https://anilist.co/anime/7", title="작품", source="AniList 트렌딩 애니",
                        externalId="anilist:7")
        nothing = content("d", url="https://x.example/n", title="사진 없음", source="수동 입력")
        db = Mock()
        db.collection_group.return_value.stream.return_value = iter([have, video, cover, nothing])
        sources = [{"name": "AniList 트렌딩 애니", "type": "anilist"}]
        with patch.object(image_backfill, "anilist_covers", return_value={7: "https://s4.anilist.co/c7.jpg"}) as covers:
            counts = image_backfill.backfill_images(db, sources)
        have.reference.update.assert_not_called()
        video.reference.update.assert_called_once_with({"imageUrl": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"})
        cover.reference.update.assert_called_once_with({"imageUrl": "https://s4.anilist.co/c7.jpg"})
        nothing.reference.update.assert_not_called()
        covers.assert_called_once_with([7], sources[0])  # one batched lookup
        self.assertEqual((counts["updated"], counts["still_missing"]), (2, 1))

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

    def test_anilist_covers_maps_ids_and_skips_missing_covers(self):
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {"data": {"Page": {"media": [
            {"id": 1, "coverImage": {"large": "https://s4.anilist.co/1.jpg"}},
            {"id": 2, "coverImage": None},
        ]}}}
        with patch.object(anilist.requests, "post", return_value=response) as post, \
                patch.object(anilist, "pause_between_requests"):
            covers = anilist.anilist_covers([1, 2])
        self.assertEqual(covers, {1: "https://s4.anilist.co/1.jpg"})
        self.assertEqual(post.call_args.kwargs["json"]["variables"]["ids"], [1, 2])

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

    def test_local_cleanup_removes_the_home_row(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(Path(directory) / "library.sqlite3")
            cloud = Mock()
            cloud.collection_group.return_value.stream.return_value = iter([
                SimpleNamespace(id="h", reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id="ANIME"))),
                                to_dict=lambda: {"url": "https://laftel.net/", "title": UNTITLED_TITLE, "source": "x"}),
                SimpleNamespace(id="k", reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id="ANIME"))),
                                to_dict=lambda: {"url": "https://laftel.net/", "title": "라프텔 홈", "source": "x"}),
            ])
            library.sync(cloud)
            result = library.delete_untitled_x()
            self.assertEqual([item["id"] for item in result["items"]], ["ANIME:h"])


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

    def test_genshin_is_in_the_catalog_and_links_hoyoverse_titles(self):
        from subculture.library.application import seed_works
        with tempfile.TemporaryDirectory() as directory:
            library = Library(Path(directory) / "library.sqlite3")
            cloud = Mock()
            cloud.collection_group.return_value.stream.return_value = iter([
                SimpleNamespace(id="g", reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id="FIGURE"))),
                                to_dict=lambda: {"url": "https://s.example.com/g", "title": "[원신] 클리어 파일", "source": "따빼몰"}),
            ])
            library.sync(cloud)
            created, linked = seed_works.seed(library)
            self.assertGreater(created, 0)
            self.assertEqual(linked, 1)
            works = {w["name"]: w["id"] for w in library.terms()["works"]}
            rows, _ = library.items({"works": str(works["원신"])})
            self.assertEqual([row["id"] for row in rows], ["FIGURE:g"])

    def test_azur_lane_is_in_the_catalog_and_links_shop_titles(self):
        from subculture.library.application import seed_works
        with tempfile.TemporaryDirectory() as directory:
            library = Library(Path(directory) / "library.sqlite3")
            cloud = Mock()
            cloud.collection_group.return_value.stream.return_value = iter([
                SimpleNamespace(
                    id="a",
                    reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id="FIGURE"))),
                    to_dict=lambda: {
                        "url": "https://s.example.com/a",
                        "title": "[예약]벽람항로 아주르 레인 키어사지 피규어",
                        "source": "따빼몰",
                    },
                ),
            ])
            library.sync(cloud)
            created, linked = seed_works.seed(library)
            self.assertGreater(created, 0)
            self.assertEqual(linked, 1)
            works = {w["name"]: w["id"] for w in library.terms()["works"]}
            rows, _ = library.items({"works": str(works["벽람항로"])})
            self.assertEqual([row["id"] for row in rows], ["FIGURE:a"])

    def test_unmatched_report_summarises_unlinked_items_by_source(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(Path(directory) / "library.sqlite3")

            def snap(doc_id_, title, source):
                return SimpleNamespace(
                    id=doc_id_, reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id="GOODS"))),
                    to_dict=lambda: {"url": f"https://s.example.com/{doc_id_}", "title": title, "source": source})
            cloud = Mock()
            cloud.collection_group.return_value.stream.return_value = iter([
                snap("1", "【굿즈-키홀더】 미지의 작품 A", "애니메이트"),
                snap("2", "【굿즈-키홀더】 미지의 작품 B", "애니메이트"),
                snap("3", "[예약] 미지의 작품 C", "라프텔 스토어"),
            ])
            library.sync(cloud)
            report = library.unclassified_report()
        self.assertEqual(report["total"], 3)
        self.assertEqual(dict(report["by_source"]), {"애니메이트": 2, "라프텔 스토어": 1})
        self.assertEqual(dict(report["bracket_tokens"])["굿즈-키홀더"], 2)
        self.assertEqual(len(report["samples"]["애니메이트"]), 2)


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
        with patch.object(review, "fetch_contents_page", return_value=([], False, "")) as fetch:
            html = review.app.test_client().get("/").get_data(as_text=True)
        self.assertEqual(fetch.call_args.args[2], "14")
        for label in ("최근 7일", "최근 14일", "최근 30일", "전체 기간"):
            self.assertIn(label, html)


if __name__ == "__main__":
    unittest.main()
