"""Optional offline browser regressions; no server, Firestore or external requests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from subculture.web import app as review, site_builder

ROOT = Path(__file__).resolve().parents[1]


class BrowserUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright, Error
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed")
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Error as exc:
            cls.playwright.stop()
            raise unittest.SkipTest(f"Chromium unavailable: {str(exc).splitlines()[0]}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def test_public_alias_source_combination_and_keyboard_mobile(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_builder.build([
                ("GOODS:a", {"title": "원피스 상품", "source": "샵 A", "category": "GOODS"}),
                ("GOODS:b", {"title": "다른 상품", "source": "샵 B", "category": "GOODS"}),
            ], [{"name": "ONE PIECE", "aliases": ["원피스", "ワンピース"]}], tmp)
            def route(request):
                name = request.request.url.rsplit("/", 1)[-1] or "index.html"
                file = Path(tmp) / name
                request.fulfill(path=str(file)) if file.is_file() else request.abort()
            self.page.route("**/*", route)
            self.page.goto("http://offline.test/index.html")
            self.page.wait_for_selector(".item-card")
            self.page.locator("#search-work").fill("ワンピース")
            self.page.locator("#search-work").press("ArrowDown")
            self.page.keyboard.press("Enter")
            self.assertEqual(self.page.locator(".item-card").count(), 1)
            self.page.locator("#search-source").fill("샵 B")
            self.page.locator('#filter-source button[data-value="샵 B"]').click()
            self.assertEqual(self.page.locator(".item-card").count(), 0)
            self.page.locator('#filter-source button[data-value="ALL"]').click()
            self.page.locator('#filter-work button[data-value="ALL"]').click()
            self.page.locator("#filter-q").fill("ワンピース")
            self.assertEqual(self.page.locator(".item-card").count(), 1)
            self.page.locator("#search-work").fill("없는작품")
            self.assertIn("검색 결과가 없습니다", self.page.locator("#filter-work").inner_text())
            self.page.set_viewport_size({"width": 390, "height": 844})
            self.assertTrue(self.page.locator("#search-work").is_visible())
            self.assertFalse(self.errors, self.errors)

    def test_public_grid_pagination_and_mobile_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_builder.build([
                (f"GOODS:{n}", {"title": f"상품 {n} " + "긴제목" * 20,
                                  "source": "테스트 샵", "category": "GOODS"})
                for n in range(65)
            ], [], tmp)

            def route(request):
                name = request.request.url.rsplit("/", 1)[-1] or "index.html"
                file = Path(tmp) / name
                request.fulfill(path=str(file)) if file.is_file() else request.abort()

            self.page.route("**/*", route)
            self.page.set_viewport_size({"width": 1440, "height": 900})
            self.page.goto("http://offline.test/subculture-researcher/index.html")
            self.page.wait_for_selector(".item-card")
            self.assertEqual(self.page.locator(".item-card").count(), 60)
            first = self.page.locator(".item-card").nth(0).bounding_box()
            second = self.page.locator(".item-card").nth(1).bounding_box()
            self.assertAlmostEqual(first["y"], second["y"], delta=1)
            self.assertGreater(second["x"], first["x"])
            self.page.locator("#more").scroll_into_view_if_needed()
            self.page.wait_for_function("document.querySelectorAll('.item-card').length === 65")
            self.assertTrue(self.page.locator("#more").is_hidden())
            self.page.set_viewport_size({"width": 390, "height": 844})
            self.assertTrue(self.page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"))
            self.page.locator("#filter-q").fill("상품 64 ")
            self.assertEqual(self.page.locator(".item-card").count(), 1)
            self.assertFalse(self.errors, self.errors)

    def test_public_checked_cards_become_a_comparison_post(self):
        from subculture.shared.compare_post import build_compare_posts
        from tests.test_compare_post import FIGURE_A, FIGURE_B, NEWS

        with tempfile.TemporaryDirectory() as tmp:
            site_builder.build([
                ("FIGURE:a", FIGURE_A),
                ("FIGURE:b", FIGURE_B),
                ("ANIME:n", NEWS),
            ], [], tmp)

            def route(request):
                name = request.request.url.rsplit("/", 1)[-1] or "index.html"
                file = Path(tmp) / name
                request.fulfill(path=str(file)) if file.is_file() else request.abort()

            self.page.route("**/*", route)
            self.page.set_viewport_size({"width": 1440, "height": 900})
            self.page.goto("http://offline.test/index.html")
            self.page.wait_for_selector(".draft-source")
            boxes = self.page.locator(".draft-source")
            boxes.nth(1).check()
            boxes.nth(0).check()
            self.assertIn("2개 선택", self.page.locator(".draft-bar-count").inner_text())
            self.page.locator('#compare-form [type="submit"]').click()
            self.page.wait_for_selector("#compare-panel", state="visible")
            expected = build_compare_posts([FIGURE_B, FIGURE_A])
            self.assertEqual(self.page.locator("#post-body").input_value(), expected.body)
            self.assertEqual(self.page.locator("#post-reply").input_value(), expected.reply)
            self.page.locator("#post-body").fill("직접 편집")
            boxes.nth(2).check()
            self.assertIn("선택이 변경", self.page.locator("#compare-message").inner_text())
            self.assertEqual(self.page.locator("#post-body").input_value(), "직접 편집")
            self.page.locator('#compare-form [type="submit"]').click()
            news = build_compare_posts([FIGURE_B, FIGURE_A, NEWS])
            self.assertEqual(self.page.locator("#post-body").input_value(), news.body)
            self.assertTrue(self.page.locator("#post-reply").input_value().startswith("상품 페이지 참고"))
            self.page.evaluate("""() => {
              window.copied = '';
              Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text) => { window.copied = text; } } });
            }""")
            self.page.locator('[data-copy-target="post-reply"]').click()
            self.page.wait_for_function("window.copied.startsWith('상품 페이지 참고')")
            self.assertFalse(self.errors, self.errors)

    def test_inbox_cards_share_a_row_and_keep_review_actions(self):
        from tests.test_item_card import snapshot

        with patch.object(review, "fetch_contents_page", return_value=(
                [snapshot("FIGURE:a"), snapshot("FIGURE:b", title="다른 상품")], False, "")), \
                patch.object(review, "fetch_recommended_items", return_value=[]):
            html = review.app.test_client().get("/inbox").get_data(as_text=True)

        def route(request):
            url = request.request.url
            if "/static/" in url:
                request.fulfill(path=str(ROOT / "subculture/web/static" / url.rsplit("/", 1)[-1]))
            else:
                request.fulfill(content_type="text/html", body=html)

        self.page.route("**/*", route)
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto("http://offline.test/inbox")
        self.page.wait_for_selector("#item-list .item-card")
        cards = self.page.locator("#item-list .item-card")
        self.assertEqual(cards.count(), 2)
        first = cards.nth(0).bounding_box()
        second = cards.nth(1).bounding_box()
        self.assertAlmostEqual(first["y"], second["y"], delta=1)
        self.assertGreater(second["x"], first["x"])
        adopt = cards.nth(0).locator('[aria-label="채택"]')
        self.assertTrue(adopt.is_visible())
        card_box = cards.nth(0).bounding_box()
        action_box = adopt.bounding_box()
        self.assertLessEqual(action_box["x"] + action_box["width"], card_box["x"] + card_box["width"] + 1)
        cards.nth(0).locator(".more-trigger").click()
        self.assertTrue(self.page.locator("dialog[open]").is_visible())
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertEqual(cards.count(), 2)
        narrow_first = cards.nth(0).bounding_box()
        narrow_second = cards.nth(1).bounding_box()
        self.assertGreater(narrow_second["y"], narrow_first["y"])
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
        self.assertFalse(self.errors, self.errors)

    def test_local_panel_duplicate_selection_edit_error_and_reload(self):
        with patch.object(review, "fetch_contents_page", return_value=([], False, "")), patch.object(review, "fetch_recommended_items", return_value=[]):
            html = review.app.test_client().get("/inbox").get_data(as_text=True)
        result = {"body": "1. 비교 상품", "reply": "1. 링크\nhttps://example.com/a", "count": 1, "missingCount": 0, "bodyTarget": 260}
        calls = []
        def route(request):
            url = request.request.url
            if url.endswith("/compare"):
                calls.append(request.request.post_data)
                request.fulfill(status=400 if len(calls) > 1 else 200, content_type="application/json", body=json.dumps({"error": "테스트 오류"} if len(calls) > 1 else result))
            elif "/static/" in url:
                request.fulfill(path=str(ROOT / "subculture/web/static" / url.rsplit("/", 1)[-1]))
            else:
                request.fulfill(content_type="text/html", body=html)
        self.page.route("**/*", route)
        self.page.goto("http://offline.test/inbox")
        self.page.evaluate('''() => {
          for (let n = 0; n < 2; n++) {
            const box = document.createElement('input');
            box.type = 'checkbox'; box.className = 'draft-source'; box.value = 'FIGURE:a';
            document.querySelector('#item-list').appendChild(box);
          }
        }''')
        boxes = self.page.locator(".draft-source")
        boxes.nth(0).check()
        self.assertTrue(boxes.nth(1).is_checked())
        self.page.locator('#compare-form [type="submit"]').click()
        self.page.wait_for_selector("#compare-panel", state="visible")
        self.assertEqual(self.page.locator("#post-body").input_value(), result["body"])
        self.assertEqual(calls[0].count("FIGURE:a"), 1)
        self.page.locator("#post-body").fill("직접 편집")
        self.page.evaluate("""() => {
          window.copied = ''; window.opened = '';
          Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text) => { window.copied = text; } } });
          window.open = (url) => { window.opened = url; };
          const box = document.createElement('input');
          box.type = 'checkbox'; box.className = 'draft-source'; box.value = 'FIGURE:a';
          document.querySelector('#item-list').appendChild(box);
        }""")
        self.page.wait_for_function("document.querySelectorAll('.draft-source')[2].checked")
        self.page.locator('[data-copy-target="post-body"]').click()
        self.page.wait_for_function("window.copied === '직접 편집'")
        self.page.locator('[data-copy-target="post-reply"]').click()
        self.page.wait_for_function("window.copied.includes('https://example.com/a')")
        self.page.locator('[data-x-post-target="post-body"]').click()
        self.assertIn("https://x.com/intent/post?text=", self.page.evaluate("window.opened"))
        self.page.locator("#compare-clear").click()
        self.assertEqual(self.page.locator("#post-body").input_value(), "직접 편집")
        self.assertIn("선택이 변경", self.page.locator("#compare-message").inner_text())
        boxes.nth(0).check()
        self.page.locator('#compare-form [type="submit"]').click()
        self.page.wait_for_function("document.querySelector('#compare-error').textContent === '테스트 오류'")
        self.assertEqual(self.page.locator("#post-body").input_value(), "직접 편집")
        self.page.locator("#compare-close").click()
        self.assertTrue(self.page.locator("#compare-panel").is_hidden())
        self.page.evaluate("""() => {
          for (let n = 0; n < 21; n++) {
            const box = document.createElement('input');
            box.type = 'checkbox'; box.className = 'draft-source'; box.value = `FIGURE:new${n}`;
            document.querySelector('#item-list').appendChild(box);
            box.checked = true; box.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }""")
        self.assertIn("20개 선택", self.page.locator('.draft-bar-count').inner_text())
        self.assertIn("20개까지", self.page.locator('#compare-error').inner_text())
        self.page.reload()
        self.assertEqual(self.page.locator("#post-body").input_value(), "")
        self.assertFalse(self.errors, self.errors)
