"""Offline checks for image-link collection; HTML fixtures mirror the real site DOMs."""

import unittest
from unittest.mock import MagicMock, Mock, patch

from bs4 import BeautifulSoup

from collectors import anilist, json_api, youtube_feed
from collectors.common import extract_product_fields
from collectors.html_links import extract_links, html_items
from collectors.images import card_of, detail_image, img_url
from collectors.local_browser import _card_image
from content_store import ContentStore
from image_urls import clean_image_url, http_url
from presentation import product_caption

BASE = "https://shop.example.com/list"
# HOBBY Watch style: the photo sits in a sibling block of the title link, same <li>.
NEWS_LIST = """
<ul>
  <li class="item"><div class="image"><a href="/docs/news/1.html"><img src="https://asset.example.com/1/list.jpg"></a></div>
      <p><a href="/docs/news/1.html">기사 하나 제목</a></p></li>
  <li class="item"><div class="image"><a href="/docs/news/2.html"><img src="https://asset.example.com/2/list.jpg"></a></div>
      <p><a href="/docs/news/2.html">기사 둘 제목</a></p></li>
  <li class="item"><p><a href="/docs/news/3.html">사진 없는 기사</a></p></li>
</ul>"""
# 따빼몰 style: icons and a lazy-load blank come before the real thumbnail.
SHOP_LIST = """
<ul>
  <li class="item"><img class="likePrdIcon" src="/web/upload/icon_1.png">
      <img src="/_wg/img/_btn/list_blank.png" data-src="/web/product/medium/a.jpg" alt="상품 A">
      <p class="name"><a href="/product/detail.html?product_no=1">상품 A</a></p></li>
  <li class="item"><img class="likePrdIcon" src="/web/upload/icon_1.png">
      <img src="/web/product/medium/b.jpg" alt="상품 B">
      <p class="name"><a href="/product/detail.html?product_no=2">상품 B</a></p></li>
</ul>"""


class UrlRuleTests(unittest.TestCase):
    def test_only_photos_survive(self):
        good = {
            "https://cdn.example.com/a/b.jpg": "https://cdn.example.com/a/b.jpg",
            "/web/product/big/c.jpg": "https://shop.example.com/web/product/big/c.jpg",
            "//cdn.example.com/x.png": "https://cdn.example.com/x.png",
            "https://pbs.twimg.com/media/G6M?format=jpg&amp;name=large": "https://pbs.twimg.com/media/G6M?format=jpg&name=large",
            "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
        }
        for raw, expected in good.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_image_url(raw, "https://shop.example.com/x/"), expected)
        for raw in (
            "", None, "data:image/gif;base64,R0lGOD", "javascript:alert(1)", "ftp://x.example/a.jpg",
            "https://www.goodsmile.com/img/common/ogp.png", "https://www.animatetimes.com/img/ogimage.png",
            "https://ttabbaemall.co.kr/web/upload/share-image-1-76f6.png", "/_wg/img/_btn/list_blank.png",
            "/web/upload/icon_202309.png", "/skin/common/logo.png", "/img/noimage.jpg", "/a/b.svg",
            "https://user:pw@example.com/a.jpg",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(clean_image_url(raw, BASE))

    def test_per_source_deny_patterns_and_scheme_check(self):
        wix = "https://static.wixstatic.com/media/x~mv2.jpg/v1/fill/w_333,h_250,blur_30,q_30/x~mv2.webp"
        self.assertIsNone(clean_image_url(wix, deny=[r"blur_\d+"]))
        self.assertEqual(clean_image_url(wix), wix)
        self.assertEqual(http_url("https://a.example/x.jpg"), "https://a.example/x.jpg")
        self.assertIsNone(http_url("javascript:alert(1)"))
        self.assertIsNone(http_url("https://" + "a" * 2100))


class DomExtractionTests(unittest.TestCase):
    def test_lazy_src_beats_placeholder_and_tiny_images_are_skipped(self):
        soup = BeautifulSoup(
            '<img src="/_wg/img/list_blank.png" data-src="/p/real.jpg">'
            '<img src="/p/badge.png" width="24" height="24"><img srcset="/p/s.jpg 1x, /p/l.jpg 2x">', "html.parser")
        first, badge, srcset = soup.find_all("img")
        self.assertEqual(img_url(first, BASE), "https://shop.example.com/p/real.jpg")
        self.assertIsNone(img_url(badge, BASE))
        self.assertEqual(img_url(srcset, BASE), "https://shop.example.com/p/s.jpg")

    def test_each_list_card_gets_its_own_photo_never_a_neighbours(self):
        source = {"link_selector": 'a[href*="/docs/news/"]', "list_image_selector": "img"}
        items = list(extract_links(NEWS_LIST, BASE, source))
        images = {item["url"].rsplit("/", 1)[1]: item.get("imageUrl") for item in items}
        self.assertEqual(images["1.html"], "https://asset.example.com/1/list.jpg")
        self.assertEqual(images["2.html"], "https://asset.example.com/2/list.jpg")
        self.assertIsNone(images["3.html"])  # no photo of its own: must not borrow another card's

    def test_card_stops_before_a_second_article(self):
        soup = BeautifulSoup(NEWS_LIST, "html.parser")
        anchor = soup.select('a[href="/docs/news/2.html"]')[-1]
        card = card_of(anchor, 'a[href*="/docs/news/"]', BASE)
        self.assertEqual(card.name, "li")
        self.assertEqual(len(card.select("img")), 1)

    def test_shop_list_skips_icons_and_placeholders(self):
        source = {"link_selector": "p.name a", "list_image_selector": "img"}
        items = list(extract_links(SHOP_LIST, "https://shop.example.com/c/", source))
        self.assertEqual([i["imageUrl"] for i in items], [
            "https://shop.example.com/web/product/medium/a.jpg",
            "https://shop.example.com/web/product/medium/b.jpg",
        ])

    def test_no_image_key_unless_source_opts_in(self):
        items = list(extract_links(NEWS_LIST, BASE, {"link_selector": 'a[href*="/docs/news/"]'}))
        self.assertTrue(all("imageUrl" not in item for item in items))

    def test_detail_image_prefers_selector_then_article_og_over_site_default(self):
        page = BeautifulSoup(
            '<meta property="og:image" content="https://www.site.example/img/common/ogp.png">'
            '<meta name="twitter:image" content="/media/article.jpg"><img class="main" src="/media/main.jpg">',
            "html.parser")
        self.assertEqual(detail_image(page, "https://www.site.example/news/1", {}), "https://www.site.example/media/article.jpg")
        self.assertEqual(detail_image(page, "https://www.site.example/news/1", {"image_selector": "img.main"}),
                         "https://www.site.example/media/main.jpg")
        only_default = BeautifulSoup('<meta property="og:image" content="/img/common/ogp.png">', "html.parser")
        self.assertIsNone(detail_image(only_default, "https://www.site.example/n", {}))

    def test_product_fields_keep_the_photo_only_when_there_is_one(self):
        with_photo = extract_product_fields({"name": "s"}, "가격 12,000원", "https://cdn.example.com/p.jpg")
        self.assertEqual(with_photo["imageUrl"], "https://cdn.example.com/p.jpg")
        without = extract_product_fields({"name": "s"}, "가격 12,000원", "https://x.example/img/common/ogp.png")
        self.assertNotIn("imageUrl", without)  # must not overwrite a list-card photo with None


class DetailFetchTests(unittest.TestCase):
    def run_items(self, source, pages):
        def fake_get_html(url, policy, timeout=15, source=None):
            return pages[url], url
        with patch("collectors.html_links.get_html", side_effect=fake_get_html), \
                patch("collectors.html_links.RobotsPolicy"):
            return list(html_items(source))

    def test_detail_og_image_is_stored_without_a_price(self):
        listing = "https://n.example.com/list"
        pages = {
            listing: '<a href="/a/1">첫 번째 기사 제목</a>',
            "https://n.example.com/a/1": '<meta property="og:image" content="https://cdn.example.com/1.jpg">본문',
        }
        source = {"url": listing, "link_selector": "a", "fetch_detail_image": True, "respect_robots": False}
        (item,) = self.run_items(source, pages)
        self.assertEqual(item["imageUrl"], "https://cdn.example.com/1.jpg")
        self.assertNotIn("entityType", item)  # image mode does not tag news as a product

    def test_shop_gets_price_and_photo_together(self):
        listing = "https://s.example.com/list"
        pages = {
            listing: '<a href="/p/1">상품 이름 하나</a>',
            "https://s.example.com/p/1": '<meta property="og:image" content="https://cdn.example.com/p1.jpg">예약 12,000원',
        }
        source = {"name": "shop", "url": listing, "link_selector": "a", "product_mode": True, "respect_robots": False}
        (item,) = self.run_items(source, pages)
        self.assertEqual(item["imageUrl"], "https://cdn.example.com/p1.jpg")
        self.assertEqual(item["price"], 12000)


class FeedAndApiTests(unittest.TestCase):
    FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry><yt:videoId>abcdefghijk</yt:videoId><title>PV 하나</title><link rel="alternate" href="https://www.youtube.com/watch?v=abcdefghijk"/>
  <published>2026-09-18T00:00:00+00:00</published>
  <media:group><media:thumbnail url="https://i2.ytimg.com/vi/abcdefghijk/hqdefault.jpg" width="480" height="360"/></media:group></entry>
 <entry><yt:videoId>zyxwvutsrqp</yt:videoId><title>PV 둘</title><link rel="alternate" href="https://www.youtube.com/watch?v=zyxwvutsrqp"/>
  <published>2026-09-17T00:00:00+00:00</published></entry>
</feed>"""

    def test_youtube_thumbnail_from_feed_or_video_id(self):
        response = Mock(content=self.FEED.encode(), status_code=200)
        response.raise_for_status = Mock()
        with patch.object(youtube_feed.requests, "get", return_value=response):
            items = list(youtube_feed.youtube_feed_items({"channel_id": "UC" + "a" * 22, "max_items": 5}))
        self.assertEqual(items[0]["imageUrl"], "https://i2.ytimg.com/vi/abcdefghijk/hqdefault.jpg")
        self.assertEqual(items[1]["imageUrl"], "https://i.ytimg.com/vi/zyxwvutsrqp/hqdefault.jpg")

    def test_anilist_cover_image(self):
        payload = {"data": {"Page": {"media": [
            {"id": 1, "siteUrl": "https://anilist.co/anime/1", "title": {"native": "작품"},
             "coverImage": {"large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx1-x.jpg"}},
            {"id": 2, "siteUrl": "https://anilist.co/anime/2", "title": {"native": "표지 없음"}, "coverImage": None},
        ]}}}
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = payload
        with patch.object(anilist.requests, "post", return_value=response):
            items = list(anilist.anilist_items({"max_items": 2}))
        self.assertTrue(items[0]["imageUrl"].endswith("bx1-x.jpg"))
        self.assertNotIn("imageUrl", items[1])

    def test_json_api_first_image_in_html_body_is_unescaped(self):
        payload = {"listData": [
            {"idx": 1, "title": "타임테이블", "content": '<p><img src="https://pbs.twimg.com/media/G6M?format=jpg&amp;name=large"></p>'},
            {"idx": 2, "title": "이미지 없음", "content": "<p>본문만</p>"},
        ]}
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = payload
        source = {"url": "https://api.example.com/list", "items_path": "listData", "id_field": "idx",
                  "title_field": "title", "detail_url_template": "https://www.example.com/post/{id}",
                  "image_html_field": "content"}
        with patch.object(json_api.requests, "get", return_value=response):
            items = list(json_api.json_api_items(source))
        self.assertEqual(items[0]["imageUrl"], "https://pbs.twimg.com/media/G6M?format=jpg&name=large")
        self.assertNotIn("imageUrl", items[1])

    def test_local_browser_card_image_skips_placeholders_and_tiny_badges(self):
        locator = Mock()
        locator.evaluate.return_value = [
            {"lazy": "", "src": "https://x.example/static/logo.png", "width": 300, "height": 80},
            {"lazy": "", "src": "https://x.example/p/badge.jpg", "width": 24, "height": 24},
            {"lazy": "https://x.example/p/poster.jpg", "src": "data:image/gif;base64,R0lG", "width": 300, "height": 420},
        ]
        self.assertEqual(_card_image({"list_image_selector": "img"}, locator, "https://x.example/"),
                         "https://x.example/p/poster.jpg")
        locator.evaluate.side_effect = RuntimeError("detached")
        self.assertIsNone(_card_image({}, locator, "https://x.example/"))


class StoreImageTests(unittest.TestCase):
    def test_unsafe_image_links_are_never_stored(self):
        store = ContentStore()
        for index, bad in enumerate(("javascript:alert(1)", "data:image/png;base64,AAAA", "  ", None)):
            store.save({"url": f"https://example.com/{index}", "title": "t", "imageUrl": bad})
        store.save({"url": "https://example.com/ok", "title": "t", "imageUrl": "https://cdn.example.com/a.jpg"})
        by_url = {row["url"]: row for row in store.preview}
        self.assertTrue(all("imageUrl" not in by_url[f"https://example.com/{i}"] for i in range(4)))
        self.assertEqual(by_url["https://example.com/ok"]["imageUrl"], "https://cdn.example.com/a.jpg")

    def test_recollection_backfills_the_photo_on_existing_documents(self):
        store = ContentStore()
        store.db = MagicMock()
        ref = Mock()
        store.by_url["https://example.com/a"] = [{"id": "abc", "status": "KEEP", "ref": ref}]
        result = store.save({"url": "https://example.com/a", "title": "t", "imageUrl": "https://cdn.example.com/a.jpg"})
        self.assertEqual(result["existing"], 1)
        ref.update.assert_called_once()
        self.assertEqual(ref.update.call_args.args[0]["imageUrl"], "https://cdn.example.com/a.jpg")


class ProductCaptionTests(unittest.TestCase):
    def test_elapsed_deadline_is_flagged(self):
        item = {"entityType": "PRODUCT", "saleStatus": "PREORDER", "preorderEndAt": "2026-06-12"}
        self.assertIn("(마감 지남)", product_caption(item, today="2026-09-19"))
        self.assertNotIn("(마감 지남)", product_caption(item, today="2026-06-12"))


if __name__ == "__main__":
    unittest.main()
