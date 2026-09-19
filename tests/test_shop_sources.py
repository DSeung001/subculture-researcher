"""Offline checks for the new-arrival shop sources and the source list itself.

The fixtures mirror the real store DOMs and are run through the real sources.yaml entries,
so a wrong selector or pattern in the config fails here, not in a live collection.
"""

import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from collectors.common import extract_product_fields
from collectors.html_links import extract_links, fetch_detail, html_items
from content_store import add_manual_content, manual_shop
from sources_config import automatic_sources, is_manual_source, load_sources

SOURCES = {source["name"]: source for source in load_sources()}
LAFTEL = SOURCES["라프텔 스토어"]
ANIMATE = SOURCES["애니메이트 코리아 신상품"]
FIGUREPRESSO = SOURCES["피규어프레소 예약상품"]
TTABBAE_NEW_ARRIVAL = SOURCES["따빼몰 신규입고"]
TTABBAE_NEW_PREORDER = SOURCES["따빼몰 신규예약"]
COMICS_ART_NEW = SOURCES["코믹스아트 신작 상품"]
COMICS_ART_IN_STOCK = SOURCES["코믹스아트 입고 완료 당일 발송"]
MANIAHOUSE_PREORDER = SOURCES["마니아하우스 예약상품"]
MANIAHOUSE_IN_STOCK = SOURCES["마니아하우스 입고완료"]

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

# ttabbaemall.co.kr list (cate_no=23/24): the thumbnail link and the name link both point at the product,
# but only p.name a is collected. The title is the last span in it, after a hidden "상품명 :" label.
TTABBAE_LIST = """
<ul>
 <li class="item"><div class="thumbnail"><a href="/product/detail.html?product_no=9055&amp;cate_no=24&amp;display_group=1"><img src="//ttabbaemall.co.kr/web/product/medium/202609/a.jpg"></a></div>
  <div class="description"><p class="name"><a href="/product/detail.html?product_no=9055&amp;cate_no=24&amp;display_group=1"><span class="title displaynone"><span>상품명</span> :</span> <span>[예약]니디걸 오버도즈 누들스토퍼 초텐짱</span></a></p></div></li>
 <li class="item"><div class="description"><p class="name"><a href="/product/detail.html?product_no=7701&amp;cate_no=24&amp;display_group=1"><span class="title displaynone"><span>상품명</span> :</span> <span>명조 미니 공명자 시리즈 봉제인형 키링 제 2탄</span></a></p></div></li>
</ul>"""

# maniahouse.co.kr list (cate_no=45/46): the image link and the name link (a.name) both point at the product.
MANIAHOUSE_LIST = """
<ul>
 <li class="xans-record-"><a href="/product/detail.html?product_no=25843&cate_no=45&display_group=1" class="prdImg"><img src="//maniahouse.co.kr/web/product/medium/202609/a.jpg" alt=""/></a>
  <a href="/product/detail.html?product_no=25843&cate_no=45&display_group=1" class="name"><span style="font-size:12px;color:#555555;">[예약판매][공식] 카보틱스 마징가Z 보스보로트 블리츠웨이 재판 3508</span></a></li>
 <li class="xans-record-"><a href="/product/detail.html?product_no=25804&cate_no=45&display_group=1" class="name"><span>[입고완료] 넨도로이드 3013 라르크앙시엘 하이도</span></a></li>
 <li><a href="/product/list.html?cate_no=46" class="name">입고 완료 상품</a></li>
</ul>"""

# The info block reads the same on every product; the 예약금/잔금 option text sits outside it.
MANIAHOUSE_DETAIL_IN_STOCK = """
<div class="detailArea"><div class="infoArea">
 <div class="xans-product-detaildesign"><table><tr><th>상품명</th><td>[입고완료][총판] 파워레인저 메가조드 프라모델</td></tr>
  <tr><th>판매가</th><td>178,000원</td></tr></table></div>
 <select><option>예약금 (7일경과시 위약금으로 소멸됩니다.)</option><option>잔금결제 (예약 결제가 없는 경우 자동취소됩니다.)</option></select>
</div></div>"""


# comics-art.co.kr list (cate_no=1215/49): links are SEO paths with a /category/N/display/N/ tail, hidden spans
# list prices before the visible text (소비자가 comes before 판매가 on discounted cards), and the last card is
# the skin's unfilled {$url} template.
COMICS_ART_LIST = """
<ul class="prdList">
 <li class="item"><div class="thumbnail"><div class="prdImg">
  <div style="display:none;"><span class="price">0원</span> <span class="sale">255,000원</span></div>
  <a href="/product/골든-헤드golden-head-17스케일-피규어/257347/category/1215/display/1/"><img src="//comics-art.co.kr/web/product/medium/202609/a.jpg"></a></div>
  <div class="icon"><div class="option"><a href="/product/detail.html?product_no=257347&amp;cate_no=1215&amp;display_group=1"><img src="https://comics11.cafe24.com/test4/new_w.png"></a></div></div></div>
  <div class="description"><strong class="name"><a href="/product/골든-헤드golden-head-17스케일-피규어/257347/category/1215/display/1/"><span class="title displaynone"><span>상품명</span> :</span> <span>골든 헤드(GOLDEN HEAD) 1/7스케일 피규어 고블린 슬레이어2</span></a></strong>
  <ul class="spec"><li>제조사 : 골든 헤드</li><li>판매가 : 255,000원</li><li>마감 : 10월 26일 오전</li><li>발매 : 27년 06월</li></ul></div></li>
 <li class="item"><div class="thumbnail"><div class="prdImg">
  <div style="display:none;"><span class="price">82,000원</span> <span class="sale">62,000원</span></div>
  <a href="/product/당일발송-굿스마일-컴퍼니-넨도로이드-레제/112066/category/49/display/1/"><img src="//comics-art.co.kr/web/product/medium/202405/b.jpg"></a></div></div>
  <div class="description"><strong class="name"><a href="/product/당일발송-굿스마일-컴퍼니-넨도로이드-레제/112066/category/49/display/1/"><span class="title displaynone"><span>상품명</span> :</span> <span>(당일발송) 굿스마일 컴퍼니 넨도로이드 피규어 체인소 맨 레제</span></a></strong>
  <ul class="spec"><li>제조사 : 굿스마일컴퍼니</li><li>소비자가 : 82,000원</li><li>판매가 : 62,000원</li></ul></div></li>
 <li class="item"><div class="thumbnail"><div class="prdImg"><a href="/product/{$url}"><img src="{$image}"></a></div></div>
  <div class="description"><strong class="name"><a href="/product/{$url}"><span>{$productName}</span></a></strong></div></li>
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


class TtabbaemallListTests(unittest.TestCase):
    def items(self, source):
        return list(extract_links(TTABBAE_LIST, source["url"], source))

    def test_lists_are_the_cafe24_new_arrival_and_new_preorder_categories(self):
        self.assertEqual(TTABBAE_NEW_ARRIVAL["url"], "https://ttabbaemall.co.kr/product/list.html?cate_no=23")
        self.assertEqual(TTABBAE_NEW_PREORDER["url"], "https://ttabbaemall.co.kr/product/list.html?cate_no=24")

    def test_each_product_becomes_one_product_no_url_with_its_title(self):
        for source in (TTABBAE_NEW_ARRIVAL, TTABBAE_NEW_PREORDER):
            with self.subTest(source=source["name"]):
                items = self.items(source)
                self.assertEqual([item["url"] for item in items], [
                    "https://ttabbaemall.co.kr/product/detail.html?product_no=9055",
                    "https://ttabbaemall.co.kr/product/detail.html?product_no=7701",
                ])  # cate_no/display_group dropped; the thumbnail link is not a second item
                self.assertEqual(items[0]["title"], "[예약]니디걸 오버도즈 누들스토퍼 초텐짱")
                self.assertEqual(items[1]["title"], "명조 미니 공명자 시리즈 봉제인형 키링 제 2탄")

    def test_sources_are_automatic_products_from_the_shop(self):
        for source in (TTABBAE_NEW_ARRIVAL, TTABBAE_NEW_PREORDER):
            with self.subTest(source=source["name"]):
                self.assertIn(source, automatic_sources())
                self.assertTrue(source["respect_robots"])
                self.assertTrue(source["product_mode"])
                self.assertEqual(source["shop"], "따빼몰")
                self.assertEqual(source["category"], "GOODS")  # mixed list: not every item is a figure


class ManiahouseListTests(unittest.TestCase):
    def items(self, source):
        return list(extract_links(MANIAHOUSE_LIST, source["url"], source))

    def test_lists_are_the_preorder_and_arrived_categories(self):
        self.assertEqual(MANIAHOUSE_PREORDER["url"], "https://maniahouse.co.kr/product/list.html?cate_no=45")
        self.assertEqual(MANIAHOUSE_IN_STOCK["url"], "https://maniahouse.co.kr/product/list.html?cate_no=46")

    def test_each_product_becomes_one_product_no_url_with_its_title(self):
        for source in (MANIAHOUSE_PREORDER, MANIAHOUSE_IN_STOCK):
            with self.subTest(source=source["name"]):
                items = self.items(source)
                self.assertEqual([item["url"] for item in items], [
                    "https://maniahouse.co.kr/product/detail.html?product_no=25843",
                    "https://maniahouse.co.kr/product/detail.html?product_no=25804",
                ])  # cate_no/display_group dropped; the image link and category link are not items
                self.assertEqual(items[0]["title"], "[예약판매][공식] 카보틱스 마징가Z 보스보로트 블리츠웨이 재판 3508")
                self.assertEqual(items[1]["title"], "[입고완료] 넨도로이드 3013 라르크앙시엘 하이도")

    def test_sources_are_automatic_products_from_the_shop(self):
        for source in (MANIAHOUSE_PREORDER, MANIAHOUSE_IN_STOCK):
            with self.subTest(source=source["name"]):
                self.assertIn(source, automatic_sources())
                self.assertTrue(source["respect_robots"])
                self.assertTrue(source["product_mode"])
                self.assertEqual(source["shop"], "마니아하우스")

    def test_preorder_option_text_does_not_turn_an_arrived_product_into_a_preorder(self):
        source = MANIAHOUSE_IN_STOCK
        detail = f'<html><head><meta property="og:image" content="https://maniahouse.co.kr/web/product/big/a.jpg"></head><body>{MANIAHOUSE_DETAIL_IN_STOCK}</body></html>'
        item = {"url": "https://maniahouse.co.kr/product/detail.html?product_no=1", "title": "t", "_errors": []}
        with patch("collectors.html_links.get_html", return_value=(detail, item["url"])):
            fetch_detail(item, source, policy=None)
        self.assertEqual((item["saleStatus"], item["price"], item["shop"]), ("IN_STOCK", 178000, "마니아하우스"))
        self.assertEqual(item["imageUrl"], "https://maniahouse.co.kr/web/product/big/a.jpg")


class ComicsArtListTests(unittest.TestCase):
    def items(self, source):
        return list(extract_links(COMICS_ART_LIST, source["url"], source))

    def test_lists_are_the_cafe24_new_release_and_same_day_shipping_categories(self):
        self.assertEqual(COMICS_ART_NEW["url"], "https://comics-art.co.kr/product/list.html?cate_no=1215")
        self.assertEqual(COMICS_ART_IN_STOCK["url"], "https://comics-art.co.kr/product/list.html?cate_no=49")

    def test_seo_links_become_their_own_product_no_and_the_template_card_is_dropped(self):
        for source in (COMICS_ART_NEW, COMICS_ART_IN_STOCK):
            with self.subTest(source=source["name"]):
                items = self.items(source)
                self.assertEqual([item["url"] for item in items], [
                    "https://comics-art.co.kr/product/detail.html?product_no=257347",
                    "https://comics-art.co.kr/product/detail.html?product_no=112066",
                ])  # not the trailing display number, and no {$url} card
                self.assertEqual(items[0]["title"], "골든 헤드(GOLDEN HEAD) 1/7스케일 피규어 고블린 슬레이어2")
                self.assertEqual(items[0]["imageUrl"], "https://comics-art.co.kr/web/product/medium/202609/a.jpg")
                self.assertEqual(items[0]["shop"], "코믹스아트")

    def test_price_is_the_selling_price_not_the_list_price(self):
        discounted = self.items(COMICS_ART_IN_STOCK)[1]
        self.assertEqual(discounted["price"], 62000)  # 소비자가 82,000원 comes first in the card

    def test_new_release_cards_are_preorders_and_same_day_cards_are_in_stock(self):
        self.assertEqual(self.items(COMICS_ART_NEW)[0]["saleStatus"], "PREORDER")  # only 발매/마감 labels, no "예약" word
        self.assertEqual(self.items(COMICS_ART_IN_STOCK)[1]["saleStatus"], "IN_STOCK")

    def test_sources_are_automatic_list_only_products(self):
        for source in (COMICS_ART_NEW, COMICS_ART_IN_STOCK):
            with self.subTest(source=source["name"]):
                self.assertIn(source, automatic_sources())
                self.assertTrue(source["respect_robots"])
                self.assertTrue(source["list_product_mode"])
                self.assertFalse(source.get("product_mode"))  # detail pages always carry a "예약주문" button
                self.assertEqual(source["category"], "FIGURE")


class ProductFieldOptionTests(unittest.TestCase):
    TEXT = "소비자가 : 82,000원 판매가 : 62,000원 발매 : 27년 06월"

    def test_defaults_are_unchanged_without_the_options(self):
        fields = extract_product_fields({"name": "s"}, self.TEXT)
        self.assertEqual((fields["price"], fields["saleStatus"]), (82000, "IN_STOCK"))

    def test_price_pattern_picks_the_labelled_amount(self):
        fields = extract_product_fields({"name": "s", "price_pattern": r"판매가\s*:\s*([\d,]+)\s*원"}, self.TEXT)
        self.assertEqual(fields["price"], 62000)

    def test_a_price_pattern_without_a_match_is_not_a_product(self):
        self.assertEqual(extract_product_fields({"name": "s", "price_pattern": r"정가\s*([\d,]+)원"}, self.TEXT), {})

    def test_preorder_words_add_to_the_defaults_and_sold_out_still_wins(self):
        source = {"name": "s", "preorder_words": ["발매 :"]}
        self.assertEqual(extract_product_fields(source, self.TEXT)["saleStatus"], "PREORDER")
        self.assertEqual(extract_product_fields(source, self.TEXT + " 품절")["saleStatus"], "SOLD_OUT")
        self.assertEqual(extract_product_fields({"name": "s"}, "예약 판매가 : 5,000원")["saleStatus"], "PREORDER")


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
