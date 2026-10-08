"""Static site build and catalog keyword matching, offline (no Firestore, no network)."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

import yaml

from subculture.library.application.catalog import load_catalog
from subculture.library.domain.keywords import compile_works, match_works
from subculture.web import site_builder

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)
WORKS = [
    {"name": "Re:제로부터 시작하는 이세계 생활", "aliases": ["Re:제로", "리제로"]},
    {"name": "ONE PIECE", "aliases": ["원피스"]},
    {"name": "사이버펑크 엣지러너", "aliases": ["Cyberpunk Edgerunners"]},
    {"name": "사이버펑크 엣지러너", "aliases": "사이버펑크, X"},
]


class MatchWorksTests(unittest.TestCase):
    def setUp(self):
        self.compiled = compile_works(WORKS)

    def match(self, **data):
        return match_works(data, self.compiled)

    def test_colon_is_a_word_break(self):
        self.assertEqual(self.match(title="Re: 제로 렘 피규어"), ["Re:제로부터 시작하는 이세계 생활"])

    def test_translated_title_is_matched_too(self):
        self.assertEqual(self.match(title="ワンピース フィギュア", titleKo="원피스 루피 피규어"), ["ONE PIECE"])

    def test_ascii_keyword_does_not_match_inside_another_word(self):
        self.assertEqual(self.match(title="ONE PIECES set"), [])
        self.assertEqual(self.match(title="ONE PIECE 루피"), ["ONE PIECE"])

    def test_entries_repeating_a_name_are_merged_and_short_aliases_ignored(self):
        self.assertEqual(self.match(title="사이버펑크 루시 X"), ["사이버펑크 엣지러너"])
        self.assertEqual(self.match(title="루시 X"), [])

    def test_several_works_keep_catalog_order(self):
        self.assertEqual(
            self.match(title="원피스 × 리제로 콜라보"),
            ["Re:제로부터 시작하는 이세계 생활", "ONE PIECE"],
        )

    def test_shipped_catalog_loads_and_compiles(self):
        self.assertTrue(compile_works(load_catalog()))


class SiteBuildTests(unittest.TestCase):
    def build(self, docs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "site"
        count = site_builder.build(docs, WORKS, out, now=NOW)
        return out, count, json.loads((out / "data.json").read_text(encoding="utf-8"))

    def test_items_carry_card_view_works_and_storage_id(self):
        out, count, data = self.build([
            ("FIGURE:a", {
                "title": "ワンピース", "titleKo": "원피스 루피 피규어", "category": "GOODS", "source": "샵",
                "url": "https://example.com/a", "status": "NEW", "collectedAt": NOW, "postedAt": NOW,
            }),
            ("GOODS:b", {"title": "이름 없는 굿즈", "status": "KEEP"}),
        ])
        self.assertEqual(count, 2)
        self.assertEqual(data["builtAt"], NOW.isoformat())
        first, second = data["items"]
        # The id is the storage path, not the editable category.
        self.assertEqual((first["id"], first["category"]), ("FIGURE:a", "GOODS"))
        self.assertEqual(first["works"], ["ONE PIECE"])
        self.assertEqual(first["view"]["title_text"], "원피스 루피 피규어")
        self.assertEqual(first["view"]["url"], "https://example.com/a")
        self.assertEqual(first["collected"], NOW.isoformat())
        # Publish state is a local review concern, not a visitor filter.
        self.assertNotIn("posted", first)
        # Unmatched items stay, unclassified.
        self.assertEqual((second["works"], second["collected"]), ([], ""))

    def test_search_catalog_merges_aliases_and_only_includes_visible_works(self):
        _, _, data = self.build([
            ("GOODS:a", {"title": "사이버펑크 루시"}),
            ("GOODS:b", {"title": "원피스", "status": "IGNORE"}),
        ])
        self.assertEqual(data["works"], [{"name": "사이버펑크 엣지러너", "aliases": ["사이버펑크 엣지러너", "Cyberpunk Edgerunners", "사이버펑크", "X"]}])

    def test_ignored_items_are_left_out(self):
        _, count, data = self.build([
            ("GOODS:keep", {"title": "보이는 항목", "status": "NEW"}),
            ("GOODS:gone", {"title": "무시한 항목", "status": "IGNORE"}),
        ])
        self.assertEqual(count, 1)
        self.assertEqual([item["id"] for item in data["items"]], ["GOODS:keep"])

    def test_page_uses_relative_assets_and_holds_no_credentials(self):
        out, _, _ = self.build([])
        # Pages serves the site under /<repo>/, so absolute paths would break.
        html = (out / "index.html").read_text(encoding="utf-8")
        page = BeautifulSoup(html, "html.parser")
        assets = [node[attr] for selector, attr in (("script[src]", "src"), ("link[rel=stylesheet]", "href"))
                  for node in page.select(selector)]
        self.assertTrue(assets)
        for asset in assets:
            self.assertFalse(asset.startswith(("/", "http:", "https:")), asset)
            self.assertTrue((out / asset).is_file(), asset)
        self.assertEqual(page.select_one('meta[name="robots"]')["content"], "noindex")
        self.assertTrue((out / ".nojekyll").is_file())
        self.assertFalse(any("firebase" in path.name.lower() for path in out.iterdir()))


class PagesWorkflowTests(unittest.TestCase):
    def setUp(self):
        text = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.workflow = yaml.safe_load(text)
        # YAML 1.1 reads the bare key `on` as True.
        self.triggers = self.workflow.get("on") or self.workflow[True]

    def test_runs_after_collection_and_on_demand(self):
        collect = yaml.safe_load((ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8"))
        self.assertEqual(self.triggers["workflow_run"]["workflows"], [collect["name"]])
        self.assertIn("workflow_dispatch", self.triggers)

    def test_builds_then_deploys_with_pages_permissions(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read", "pages": "write", "id-token": "write"})
        steps = self.workflow["jobs"]["build"]["steps"]
        self.assertTrue(any(step.get("run") == "python build_site.py --out site" for step in steps))
        upload = next(step for step in steps if str(step.get("uses", "")).startswith("actions/upload-pages-artifact"))
        self.assertEqual(upload["with"]["path"], "site")
        self.assertEqual(self.workflow["jobs"]["deploy"]["needs"], "build")


if __name__ == "__main__":
    unittest.main()
