import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from local_library import Library


def snapshot(doc_id="legacy", title="Frieren 피규어 예약", category="FIGURE", **fields):
    return SimpleNamespace(
        id=doc_id,
        reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id=category))),
        to_dict=lambda: {"title": title, "url": f"https://example.com/{doc_id}", "source": "Shop",
                         "category": "GOODS", "preorderEndAt": "2026-10-01", **fields},
    )


def cloud(*snapshots):
    db = Mock()
    db.collection_group.return_value.stream.return_value = iter(snapshots)
    return db


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.lib = Library(self.path)

    def test_sync_preserves_relations_and_path_identity(self):
        self.lib.sync(cloud(snapshot(price=100)))
        work = self.lib.save_term("works", "프리렌", aliases="Frieren, フリーレン")
        self.lib.assign(["FIGURE:legacy"], "works", work)
        tag = self.lib.save_term("tags", "관심")
        self.lib.assign(["FIGURE:legacy"], "tags", tag)
        group = self.lib.save_collection("예약상품 소개", "기획 메모")
        self.lib.add_to_collection(group, ["FIGURE:legacy"])
        self.lib.edit_member(group, "FIGURE:legacy", "소개 메모", 3)
        self.lib.sync(cloud(snapshot(title="갱신 제목", price=200)))
        rows, total = self.lib.items({"works": work}, collection_id=group)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["id"], "FIGURE:legacy")
        self.assertEqual(rows[0]["data"]["price"], 200)
        self.assertEqual(rows[0]["collection_note"], "소개 메모")
        self.assertEqual(rows[0]["position"], 3)
        self.assertEqual(rows[0]["terms"]["tags"][0]["name"], "관심")

    def test_failed_stream_keeps_previous_snapshot(self):
        self.lib.sync(cloud(snapshot()))
        previous = self.lib.overview()["sync"]
        def failing():
            yield snapshot(title="부분 갱신")
            raise RuntimeError("network interrupted")
        db = Mock()
        db.collection_group.return_value.stream.return_value = failing()
        with self.assertRaises(RuntimeError):
            self.lib.sync(db)
        self.assertEqual(self.lib.items({})[0][0]["title"], "Frieren 피규어 예약")
        self.assertEqual(self.lib.overview()["sync"], previous)

    def test_multiple_works_and_rename(self):
        self.lib.sync(cloud(snapshot()))
        first = self.lib.save_term("works", "작품 A")
        second = self.lib.save_term("works", "작품 B")
        for work in (first, second):
            self.lib.assign(["FIGURE:legacy"], "works", work)
        self.lib.save_term("works", "작품 A 수정", first, "별칭")
        row = self.lib.items({"works": first})[0][0]
        self.assertEqual(len(row["terms"]["works"]), 2)
        self.assertEqual(row["terms"]["works"][0]["name"], "작품 A 수정")
        self.lib.delete_term("works", first)
        self.assertEqual(self.lib.items({"works": second})[1], 1)

    def test_aliases_suggest_but_never_auto_assign(self):
        self.lib.sync(cloud(snapshot(), snapshot("2", title="artwork"), snapshot("3", title="ＦＲＩＥＲＥＮ 굿즈")))
        # Clear links created by sync-time auto_assign so suggestions stay visible.
        work = self.lib.save_term("works", "장송의 프리렌", aliases="Frieren")
        self.lib.save_term("works", "짧은 이름", aliases="art")
        self.lib.assign(["FIGURE:legacy", "FIGURE:3"], "works", work, remove=True)
        rows, total = self.lib.items({"unclassified": "1"})
        suggestions = self.lib.suggestions(rows, self.lib.terms()["works"])
        self.assertEqual(total, 3)
        self.assertEqual(suggestions["FIGURE:legacy"][0]["id"], work)
        self.assertEqual(suggestions["FIGURE:3"][0]["id"], work)
        self.assertEqual(suggestions["FIGURE:2"], [])
        self.assertEqual(self.lib.items({"works": work})[1], 0)

    def test_auto_assign_works_is_additive_and_safe(self):
        self.lib.sync(cloud(
            snapshot("a", title="Frieren figure"),
            snapshot("b", title="artwork print"),
            snapshot("c", title="프리렌 × 슬라임 콜라보"),
            snapshot("d", title="무관한 상품"),
        ))
        frieren = self.lib.save_term("works", "장송의 프리렌", aliases="Frieren\n프리렌")
        slime = self.lib.save_term("works", "슬라임", aliases="슬라임")
        self.lib.save_term("works", "짧은", aliases="art")
        # Unlink anything sync already matched, then run explicit auto-assign.
        for work_id in (frieren, slime):
            rows, _ = self.lib.items({"works": work_id})
            if rows:
                self.lib.assign([r["id"] for r in rows], "works", work_id, remove=True)
        linked = self.lib.auto_assign_works()
        self.assertGreaterEqual(linked, 3)
        self.assertEqual(self.lib.items({"works": frieren})[1], 2)  # a, c
        self.assertEqual(self.lib.items({"works": str(frieren)})[1], 2)  # query-string style
        self.assertEqual(self.lib.items({"works": slime})[1], 1)  # c collab
        self.assertEqual(self.lib.items({"unclassified": "1"})[1], 2)  # b, d
        collab = self.lib.items({})[0]
        collab = next(r for r in collab if r["id"] == "FIGURE:c")
        self.assertEqual({t["id"] for t in collab["terms"]["works"]}, {frieren, slime})
        # Second run adds nothing; existing links stay.
        self.assertEqual(self.lib.auto_assign_works(), 0)
        self.lib.save_term("works", "장송의 프리렌", frieren, "Frieren\n프리렌\n葬送のフリーレン")
        self.lib.sync(cloud(snapshot("e", title="葬送のフリーレン 굿즈")))
        self.assertEqual(self.lib.items({"works": frieren})[1], 3)

    def test_filters_members_and_saved_filter(self):
        self.lib.sync(cloud(snapshot(), snapshot("2", preorderEndAt=None)))
        self.assertEqual(self.lib.items({"deadline_from": "2026-10-01", "deadline_to": "2026-10-01"})[1], 1)
        group = self.lib.save_collection("기획")
        self.lib.add_to_collection(group, ["FIGURE:legacy", "FIGURE:2"])
        self.lib.edit_member(group, "FIGURE:2", "먼저 소개", -1)
        self.lib.add_to_collection(group, ["FIGURE:2"])
        rows, total = self.lib.items({}, collection_id=group)
        self.assertEqual(total, 2)
        self.assertEqual(rows[0]["id"], "FIGURE:2")
        self.assertEqual(rows[0]["collection_note"], "먼저 소개")
        self.lib.save_filter("검색", {"q": "피규어", "arbitrary": "ignore"})
        saved = self.lib.overview()["saved_filters"][0]
        self.assertEqual(json.loads(saved["filters"]), {"q": "피규어"})

    def test_invalid_bulk_assignment_rolls_back(self):
        self.lib.sync(cloud(snapshot()))
        work = self.lib.save_term("works", "작품")
        with self.assertRaises(ValueError):
            self.lib.assign(["FIGURE:legacy", "missing"], "works", work)
        self.assertEqual(self.lib.items({"works": work})[1], 0)

    def test_pagination_and_missing_remote_documents_retained(self):
        self.lib.sync(cloud(*(snapshot(str(i)) for i in range(55))))
        self.assertEqual(len(self.lib.items({}, page=1)[0]), 50)
        self.assertEqual(len(self.lib.items({}, page=2)[0]), 5)
        self.lib.sync(cloud())
        self.assertEqual(self.lib.items({})[1], 55)

    def test_linked_work_items_uses_storage_prefix_and_skips_unlinked(self):
        from ai_drafts import pick_work_source_ids

        self.lib.sync(cloud(
            snapshot("fig1", title="피규어 A", category="FIGURE"),
            snapshot("fig2", title="피규어 B", category="FIGURE"),
            snapshot("anime1", title="방영 소식", category="ANIME"),
            snapshot("goods1", title="굿즈", category="GOODS"),
            snapshot("orphan", title="미연결", category="FIGURE"),
        ))
        work = self.lib.save_term("works", "프리렌")
        self.lib.assign(
            ["FIGURE:fig1", "FIGURE:fig2", "ANIME:anime1", "GOODS:goods1"], "works", work
        )
        groups = self.lib.linked_work_items()
        self.assertEqual(len(groups), 1)
        ids = {item["id"] for item in groups[0]["items"]}
        self.assertEqual(ids, {"FIGURE:fig1", "FIGURE:fig2", "ANIME:anime1", "GOODS:goods1"})
        self.assertNotIn("FIGURE:orphan", ids)

        figure_ids = pick_work_source_ids(groups, "FIGURE", size=3)
        self.assertTrue(all(item_id.startswith("FIGURE:") for item_id in figure_ids))
        self.assertNotIn("ANIME:anime1", figure_ids)

        anime_ids = pick_work_source_ids(groups, "ANIME", size=3)
        self.assertEqual(anime_ids, ["ANIME:anime1"])

        mixed_ids = pick_work_source_ids(groups, "MIXED", size=3)
        cats = {item_id.partition(":")[0] for item_id in mixed_ids}
        self.assertGreaterEqual(len(cats), 2)

        remaining_figure = pick_work_source_ids(groups, "FIGURE", exclude_ids=set(figure_ids))
        self.assertEqual(remaining_figure, [])



class LibraryRouteTests(unittest.TestCase):
    def setUp(self):
        from app import app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.old_config = {k: app.config.get(k) for k in ("LIBRARY_PATH", "LIBRARY_CLOUD_DB", "TESTING")}
        self.addCleanup(lambda: app.config.update(self.old_config))
        self.provider = Mock(side_effect=AssertionError("offline page attempted cloud access"))
        app.config.update(TESTING=True, LIBRARY_PATH=self.path, LIBRARY_CLOUD_DB=self.provider)
        self.app = app
        self.client = app.test_client()

    def test_offline_pages_and_edit_flow(self):
        self.assertEqual(self.client.get("/library").status_code, 200)
        response = self.client.post("/library/terms/works", data={"name": "프리렌", "aliases": "Frieren"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Frieren", response.get_data(as_text=True))
        local = Library(self.path)
        local.sync(cloud(snapshot()))
        work = local.terms()["works"][0]["id"]
        self.client.post("/library/assign", data={"item_ids": "FIGURE:legacy", "table": "works", "term_id": work})
        response = self.client.get(f"/library?works={work}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("1개 소재", response.get_data(as_text=True))
        response = self.client.get(f"/library/works/{work}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("작품 편집", response.get_data(as_text=True))
        response = self.client.post(f"/library/works/{work}", data={
            "name": "장송의 프리렌", "aliases": "Frieren\n프리렌"}, follow_redirects=True)
        self.assertIn("장송의 프리렌", response.get_data(as_text=True))
        response = self.client.post(f"/library/works/{work}", data={"action": "auto_assign"}, follow_redirects=True)
        self.assertIn("연결을 추가", response.get_data(as_text=True))
        self.provider.assert_not_called()

    def test_sync_is_explicit_and_failed_sync_is_reported(self):
        self.app.config["LIBRARY_CLOUD_DB"] = lambda: cloud(snapshot())
        response = self.client.post("/library/sync", follow_redirects=True)
        self.assertIn("1개 항목을 동기화", response.get_data(as_text=True))
        self.app.config["LIBRARY_CLOUD_DB"] = self.provider
        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.post("/library/sync", follow_redirects=True)
        self.assertIn("동기화에 실패", response.get_data(as_text=True))
        self.assertEqual(Library(self.path).items({})[1], 1)

    def test_invalid_input_and_unsafe_source_link(self):
        Library(self.path).sync(cloud(snapshot(url="javascript:alert(1)")))
        response = self.client.get("/library")
        self.assertNotIn('href="javascript:', response.get_data(as_text=True))
        response = self.client.post("/library/terms/works", data={"name": " "}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post("/library/assign", data={"next": "//evil.example", "table": "unknown"})
        self.assertEqual(response.location, "/library")


if __name__ == "__main__":
    unittest.main()
