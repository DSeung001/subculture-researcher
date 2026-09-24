"""Offline checks for polite HTTP pacing between collector requests."""

import unittest
from unittest.mock import Mock, patch

from subculture.collection.infrastructure.collectors import http as http_mod


class RequestPacingTests(unittest.TestCase):
    def setUp(self):
        http_mod._last_fetch_at = 0.0

    def test_headers_identify_collector_and_look_like_a_browser_accept(self):
        headers = http_mod.request_headers()
        self.assertIn("SubcultureResearcher", headers["User-Agent"])
        self.assertIn("text/html", headers["Accept"])
        self.assertIn("ko", headers["Accept-Language"])

    def test_pause_respects_source_delay_range(self):
        http_mod._last_fetch_at = 10.0
        with patch.object(http_mod.random, "uniform", return_value=2.0) as uniform, \
             patch.object(http_mod.time, "sleep") as sleep, \
             patch.object(http_mod.time, "monotonic", side_effect=[10.0, 12.0]):
            waited = http_mod.pause_between_requests({
                "request_delay_min_seconds": 1.5,
                "request_delay_max_seconds": 3.0,
            })
        uniform.assert_called_once_with(1.5, 3.0)
        sleep.assert_called_once_with(2.0)
        self.assertEqual(waited, 2.0)

    def test_zero_delay_skips_sleep(self):
        with patch.object(http_mod.time, "sleep") as sleep:
            waited = http_mod.pause_between_requests({
                "request_delay_min_seconds": 0,
                "request_delay_max_seconds": 0,
            })
        sleep.assert_not_called()
        self.assertEqual(waited, 0.0)

    def test_get_html_pauses_before_each_page_fetch(self):
        response = Mock()
        response.is_redirect = False
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.text = "<html></html>"
        response.url = "https://example.com/item"
        response.raise_for_status = Mock()
        policy = http_mod.RobotsPolicy(
            enabled=False,
            source={"request_delay_min_seconds": 1, "request_delay_max_seconds": 1},
        )
        with patch.object(http_mod, "pause_between_requests", return_value=1.0) as pause, \
             patch.object(http_mod.requests, "get", return_value=response) as get:
            html, url = http_mod.get_html(
                "https://example.com/item", policy, source=policy.source,
            )
        pause.assert_called()
        get.assert_called_once()
        self.assertEqual((html, url), ("<html></html>", "https://example.com/item"))
        self.assertEqual(get.call_args.kwargs["headers"]["User-Agent"], http_mod.USER_AGENT)


class ResponseEncodingTests(unittest.TestCase):
    @staticmethod
    def response(body: bytes, content_type: str):
        import requests
        response = requests.Response()
        response._content = body
        response.headers["Content-Type"] = content_type
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
        return response

    def test_meta_charset_decodes_euc_kr_page_without_header_charset(self):
        # gundamboom.com: "Content-Type: text/html" only, page declares euc-kr in <meta>.
        body = '<META http-equiv="Content-Type" content="text/html; charset=euc-kr"><a>[예약] 건담 똠</a>'.encode("cp949")
        text = http_mod.response_text(self.response(body, "text/html"))
        self.assertIn("[예약] 건담 똠", text)

    def test_header_charset_is_kept(self):
        body = "<meta charset=euc-kr><p>예약</p>".encode("utf-8")
        text = http_mod.response_text(self.response(body, "text/html; charset=utf-8"))
        self.assertIn("예약", text)

    def test_unknown_meta_charset_falls_back_to_detection(self):
        body = "<meta charset=not-a-codec><p>예약 상품 안내 페이지입니다</p>".encode("utf-8")
        text = http_mod.response_text(self.response(body, "text/html"))
        self.assertIn("예약", text)


if __name__ == "__main__":
    unittest.main()
