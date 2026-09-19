"""Offline checks for the new-arrival shop sources and the source list itself.

The fixtures mirror the real store DOMs and are run through the real sources.yaml entries,
so a wrong selector or pattern in the config fails here, not in a live collection.
"""

import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from collectors.html_links import extract_links, html_items
from content_store import add_manual_content, manual_shop
from sources_config import automatic_sources, is_manual_source, load_sources

SOURCES = {source["name"]: source for source in load_sources()}
LAFTEL = SOURCES["라프텔 스토어"]
ANIMATE = SOURCES["애니메이트 코리아 신상품"]
FIGUREPRESSO = SOURCES["피규어프레소 예약상품"]

# store.laftel.net: the whole product card is the link; only fresh items carry a NEW badge.
LAFTEL_HOME = """
<section><h2>하츠네미쿠 인기 상품</h2>
<a href="/products/4659"><div><img alt="[예약] 룩업" src="https://laftelstore.cafe24.com/web/product/small/202609/a.png">
  <button aria-label="찜하기"></button></div>
  <div><span>하츠네미쿠</span> <span>[예약] 룩업 하츠네 미쿠 (재판)</span> <span>44,000원</span> <span>예약구매</span> <span>NEW</span></div></a>
<a href="/products/4615"><div><img alt="[입고] 아크릴 색지" src="https://laftelstore.cafe24.com/web/product/small/202609/b.png"></div>
  <div><span>하츠네미쿠</span> <span>[입고] 하츠네 미쿠 흑백쌍생 시리즈 아크릴 색지 백 Ver.</span> <span>9,000원</span> <span>NEW</span></div></a>
<a href="/products/1400"><div><img alt="오래된 상품" src="https://laftelstore.cafe24.com/web/product/small/202602/c.png"></div>
  <div><span>하츠네미쿠</span> <span>Trio-Try-iT 피규어</span> <span>25,000원</span></div></a>
<a href="/my">NEW 내 정보 페이지 링크</a>
<a href="/products/4659">중복 링크 NEW</a>
</section>"""

# animate-onlineshop.co.kr (Godomall): title, price and photo sit in separate blocks of one <li>.
ANIMATE_LIST = """
<ul>
 <li class="goodsitem1"><div class="item_cont"><div class="item_icon_box"><img src="/data/icon/new.png"></div>
  <div class="item_photo_box"><a href="../goods/goods_view.php?goodsNo=1000073125"><img class="middle" src="http://animate.godohosting.com/Goods/6977039600751.jpg"></a></div>
  <div class="item_info_cont"><div class="item_tit_box"><a href="../goods/goods_view.php?goodsNo=1000073125"><strong class="item_name">【굿즈-키홀더】 마도조사 애니판 토끼ver. 마스코트 위무선</strong></a></div>
  <div class="item_money_box"><strong class="item_price"><span>19,500 원 </span></strong></div></div></div></li>
 <li class="goodsitem1"><div class="item_cont"><div class="item_photo_box"><a href="../goods/goods_view.php?goodsNo=1000094910"><img src="http://animate.godohosting.com/Goods/book.jpg"></a></div>
  <div class="item_info_cont"><div class="item_tit_box"><a href="../goods/goods_view.php?goodsNo=1000094910"><strong class="item_name">【국내서적-코믹스】 사랑의 낙인</strong></a></div>
  <div class="item_money_box"><strong class="item_price"><span>6,300 원 </span></strong></div></div></div></li>
 <li class="goodsitem1"><div class="item_cont"><div class="item_icon_box">품절</div><div class="item_photo_box"><a href="../goods/goods_view.php?goodsNo=1000055265"><img src="https://cdn.example.com/a.jpg"></a></div>
  <div class="item_info_cont"><div class="item_tit_box"><a href="../goods/goods_view.php?goodsNo=1000055265"><strong class="item_name">【굿즈-클리어파일】 블루 아카이브 클리어파일 하나코(수영복)</strong></a></div>
  <div class="item_money_box"><strong class="item_price"><span>6,000 원 </span></strong></div></div></div></li>
</ul>"""

# m.figurepresso.com: Cafe24 list mixes SEO paths and short detail.html?product_no= links.
FIGUREPRESSO_LIST = """
<ul>
 <li class="item"><a href="/product/look-up-hatsune/79738/">룩업 하츠네 미쿠</a></li>
 <li class="item"><a href="/product/detail.html?product_no=80001&cate_no=24">아크릴 스탠드</a></li>
 <li class="item"><a href="/product/preorder.html?cate_no=24">예약 목록</a></li>
</ul>"""


class LaftelStoreTests(unittest.TestCase):
    def items(self):
        # Through html_items, which also drops repeated links (a product shows up in several carousels).
        with patch("collectors.html_links.get_html", return_value=(LAFTEL_HOME, "https://store.laftel.net/")), \
                patch("collectors.html_links.RobotsPolicy"):
            return list(html_items(LAFTEL))

    def test_only_new_badged_product_links_are_collected_once(self):
        urls = [item["url"] for item in self.items()]
        self.assertEqual(urls, ["https://store.laftel.net/products/4659", "https://store.laftel.net/products/4615"])

    def test_title_is_the_product_name_without_price_and_badges(self):
        titles = [item["title"] for item in self.items()]
        self.assertEqual(titles[0], "하츠네미쿠 [예약] 룩업 하츠네 미쿠 (재판)")  # IP name kept for work matching
        self.assertEqual(titles[1], "하츠네미쿠 [입고] 하츠네 미쿠 흑백쌍생 시리즈 아크릴 색지 백 Ver.")

    def test_price_status_shop_and_photo_come_from_the_card(self):
        preorder, in_stock = self.items()
        self.assertEqual((preorder["entityType"], preorder["saleStatus"], preorder["price"]), ("PRODUCT", "PREORDER", 44000))
        self.assertEqual((in_stock["saleStatus"], in_stock["price"]), ("IN_STOCK", 9000))
        self.assertEqual(preorder["shop"], "Laftel")
        self.assertEqual(preorder["imageUrl"], "https://laftelstore.cafe24.com/web/product/small/202609/a.png")
        self.assertEqual(in_stock["imageUrl"], "https://laftelstore.cafe24.com/web/product/small/202609/b.png")

    def test_no_detail_page_is_requested(self):
        with patch("collectors.html_links.get_html", return_value=(LAFTEL_HOME, "https://store.laftel.net/")) as fetch, \
                patch("collectors.html_links.RobotsPolicy"):
            items = list(html_items(LAFTEL))
        self.assertEqual(len(items), 2)
        self.assertEqual(fetch.call_count, 1)  # the list page only


class AnimateNewArrivalTests(unittest.TestCase):
    def items(self):
        base = "https://www.animate-onlineshop.co.kr/goods/goods_list.php?cateCd=008"
        return list(extract_links(ANIMATE_LIST, base, ANIMATE))

    def test_books_are_excluded_and_relative_links_resolve(self):
        items = self.items()
        self.assertEqual([item["url"] for item in items], [
            "https://www.animate-onlineshop.co.kr/goods/goods_view.php?goodsNo=1000073125",
            "https://www.animate-onlineshop.co.kr/goods/goods_view.php?goodsNo=1000055265",
        ])
        self.assertTrue(all("서적" not in item["title"] for item in items))

    def test_price_status_and_the_product_photo_not_the_icon(self):
        keyholder, clear_file = self.items()
        self.assertEqual((keyholder["price"], keyholder["saleStatus"], keyholder["shop"]), (19500, "IN_STOCK", "애니메이트 코리아"))
        self.assertEqual(keyholder["imageUrl"], "http://animate.godohosting.com/Goods/6977039600751.jpg")
        self.assertEqual(clear_file["saleStatus"], "SOLD_OUT")  # "품절" badge sits in the card, outside the link
        self.assertEqual(clear_file["imageUrl"], "https://cdn.example.com/a.jpg")


class FigurePressoTests(unittest.TestCase):
    def items(self):
        base = "https://m.figurepresso.com/product/preorder.html?cate_no=24"
        return list(extract_links(FIGUREPRESSO_LIST, base, FIGUREPRESSO))

    def test_seo_and_short_links_become_one_product_no_url_each(self):
        urls = [item["url"] for item in self.items()]
        self.assertEqual(urls, [
            "https://m.figurepresso.com/product/detail.html?product_no=79738",
            "https://m.figurepresso.com/product/detail.html?product_no=80001",
        ])


class SourceListTests(unittest.TestCase):
    REMOVED = {
        "Good Smile Company 뉴스", "애니메이트 코리아 페어·이벤트", "animate 서울홍대점",
        "일러스타 페스", "코믹월드", "Kotobukiya 뉴스", "라프텔 인기·신작",
    }

    def test_unsuitable_sources_are_gone_and_names_are_unique(self):
        names = [source["name"] for source in load_sources()]
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(self.REMOVED & set(names))

    def test_no_x_scraping_and_no_source_that_robots_forbids(self):
        for source in load_sources():
            host = urlsplit(source["url"]).hostname or ""
            self.assertNotIn(host, {"x.com", "twitter.com"}, source["name"])       # AGENTS.md: no X scraping
            self.assertNotEqual(host, "brand.naver.com", source["name"])            # robots.txt: Disallow: /

    def test_shop_sources_are_automatic_robots_checked_html(self):
        for source in (LAFTEL, ANIMATE):
            self.assertEqual(source["type"], "html")
            self.assertFalse(is_manual_source(source))
            self.assertTrue(source["respect_robots"])
            self.assertIn(source, automatic_sources())
        # Laftel is store HTML only; no laftel.net local_browser source.
        self.assertTrue(all(
            (urlsplit(s["url"]).hostname or "") != "laftel.net" for s in load_sources()
        ))


class ManualShopTests(unittest.TestCase):
    def test_naver_kotobukiya_mall_and_laftel_are_saved_as_products(self):
        self.assertEqual(manual_shop("https://brand.naver.com/kotobukiyamall/products/123"),
                         ("Kotobukiya Mall (Naver)", "코토부키야 몰(네이버)"))
        self.assertEqual(manual_shop("https://store.laftel.net/products/4659"), ("Laftel Store", "Laftel"))
        self.assertIsNone(manual_shop("https://brand.naver.com/othershop/products/1"))
        self.assertIsNone(manual_shop("https://notlaftel.net/products/1"))

    def saved(self, url, category="FIGURE", image_url=""):
        with patch("content_store.ContentStore") as store_class:
            store_class.return_value.save.return_value = {"inserted": 1}
            add_manual_content(None, url, "코토부키야 신상", category, "NEWS", "OFFICIAL", image_url)
            return store_class.return_value.save.call_args.args[0]

    def test_manual_product_fields_and_optional_photo(self):
        item = self.saved("https://brand.naver.com/kotobukiyamall/products/123", image_url="https://shop-phinf.pstatic.net/a.jpg")
        self.assertEqual((item["entityType"], item["shop"], item["sourceType"]), ("PRODUCT", "코토부키야 몰(네이버)", "manual_product"))
        self.assertEqual(item["imageUrl"], "https://shop-phinf.pstatic.net/a.jpg")
        goods = self.saved("https://brand.naver.com/kotobukiyamall/products/123", category="GOODS")
        self.assertIsNone(goods["entityType"])  # products only for the FIGURE category, as before
        self.assertEqual(goods["source"], "수동 입력")

    def test_non_http_photo_address_is_rejected(self):
        with self.assertRaises(ValueError):
            add_manual_content(None, "https://example.com/a", "t", "FIGURE", "NEWS", "MEDIA", "javascript:alert(1)")


if __name__ == "__main__":
    unittest.main()
