"""Offline checks for the ERD page; it is generated from the ORM models, no DB needed."""

import unittest

from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, Text

from subculture.library.interface.erd import LAYOUT, TABLE_W, build_erd
from subculture.library.infrastructure.models import Base


def overlaps(a, b):
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


class ErdDataTests(unittest.TestCase):
    def test_every_model_table_column_and_foreign_key_is_drawn(self):
        erd = build_erd()
        drawn = {t["name"]: t for t in erd["tables"]}
        self.assertEqual(set(drawn), set(Base.metadata.tables))
        for name, table in Base.metadata.tables.items():
            self.assertEqual([c["name"] for c in drawn[name]["columns"]], [c.name for c in table.columns])
        expected = {(t.name, fk.parent.name, fk.column.table.name, fk.column.name)
                    for t in Base.metadata.tables.values() for fk in t.foreign_keys}
        found = {(r["child"], r["child_column"], r["parent"], r["parent_column"]) for r in erd["relations"]}
        self.assertEqual(found, expected)
        self.assertTrue(all(r["ondelete"] == "CASCADE" for r in erd["relations"]))

    def test_keys_and_nullability_come_from_the_models(self):
        columns = {t["name"]: {c["name"]: c for c in t["columns"]} for t in build_erd()["tables"]}
        self.assertTrue(columns["works"]["id"]["pk"])
        self.assertTrue(columns["works"]["normalized"]["unique"])
        self.assertTrue(columns["item_works"]["item_id"]["pk"] and columns["item_works"]["item_id"]["fk"])
        self.assertTrue(columns["items"]["deadline"]["nullable"])
        self.assertFalse(columns["items"]["title"]["nullable"])

    def test_boxes_do_not_overlap_and_relations_touch_their_boxes(self):
        erd = build_erd()
        tables = erd["tables"]
        for i, first in enumerate(tables):
            for second in tables[i + 1:]:
                self.assertFalse(overlaps(first, second), (first["name"], second["name"]))
        by_name = {t["name"]: t for t in tables}
        for relation in erd["relations"]:
            for end in ("child", "parent"):
                box = by_name[relation[end]]
                mark = relation[f"{end}_mark"]
                self.assertGreaterEqual(mark["y"] + 7, box["y"])
                self.assertLessEqual(mark["y"] + 7, box["y"] + box["h"])
                self.assertTrue(box["x"] - 20 <= mark["x"] <= box["x"] + TABLE_W + 20)
        self.assertLessEqual(max(t["x"] + t["w"] for t in tables), erd["width"])
        self.assertLessEqual(max(t["y"] + t["h"] for t in tables), erd["height"])

    def test_table_missing_from_layout_is_still_drawn(self):
        metadata = MetaData()
        Table("items", metadata, Column("id", Text, primary_key=True))
        Table("brand_new", metadata, Column("id", Integer, primary_key=True),
              Column("item_id", ForeignKey("items.id", ondelete="CASCADE")))
        self.assertNotIn("brand_new", LAYOUT)
        erd = build_erd(metadata)
        names = {t["name"] for t in erd["tables"]}
        self.assertEqual(names, {"items", "brand_new"})
        self.assertEqual(len(erd["relations"]), 1)
        first, second = erd["tables"]
        self.assertFalse(overlaps(first, second))
        self.assertEqual(next(t for t in erd["tables"] if t["name"] == "brand_new")["kind"], "other")


class ErdPageTests(unittest.TestCase):
    def setUp(self):
        from subculture.web.app import app
        self.client = app.test_client()

    def test_page_lists_every_table_and_is_linked_next_to_sources(self):
        response = self.client.get("/erd")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for name in Base.metadata.tables:
            self.assertIn(f'data-table="{name}"', html)
        self.assertIn("erd.js", html)
        self.assertIn('href="/erd" class="topnav-link active"', html)
        nav = self.client.get("/sources").get_data(as_text=True)
        self.assertLess(nav.index('href="/sources"'), nav.index('href="/erd"'))


if __name__ == "__main__":
    unittest.main()
