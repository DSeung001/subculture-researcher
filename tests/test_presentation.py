"""content_score/score_breakdown: cross-category normalization and the trend signal.

These pin the two behavior changes explicitly asked for - see AGENTS.md and the plan this
was implemented from: (1) a score no longer depends on how many metric *fields* a source
happens to expose (the old bias toward AniList-backed anime items), and (2) rate-of-change
("trend") is a first-class signal, not just cumulative magnitude.
"""

import unittest
from datetime import datetime, timezone

from subculture.shared.presentation import content_score, score_breakdown

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class CrossCategoryComparabilityTests(unittest.TestCase):
    """An item's score should reflect its single best signal, not how many metric
    fields its source happens to populate."""

    def test_a_view_count_only_item_and_a_full_anilist_item_score_comparably(self):
        figure_item = {"collectedAt": NOW, "viewCount": 50_000}
        anime_item = {
            "collectedAt": NOW,
            "trending": 250, "popularity": 25_000, "favourites": 5_000, "averageScore": 50,
        }
        figure_score = content_score(figure_item, now=NOW)
        anime_score = content_score(anime_item, now=NOW)
        self.assertLess(abs(figure_score - anime_score), 2.0)

    def test_stacking_every_anilist_field_does_not_multiply_the_score(self):
        """The old sum-of-every-populated-field bug: one strong AniList field and four
        equally strong AniList fields on the same underlying item must score alike,
        since they describe the same "how popular is this" fact, not four different ones."""
        one_field = {"collectedAt": NOW, "trending": 500}
        four_fields = {"collectedAt": NOW, "trending": 500, "popularity": 500, "favourites": 500, "averageScore": 50}
        self.assertLess(abs(content_score(one_field, now=NOW) - content_score(four_fields, now=NOW)), 5.0)


class TrendVelocityTests(unittest.TestCase):
    def test_no_velocity_data_contributes_nothing(self):
        item = {"collectedAt": NOW}
        self.assertNotIn("트렌드 상승", dict(score_breakdown(item, now=NOW)))

    def test_a_fast_rising_item_outranks_a_large_but_flat_one(self):
        large_and_flat = {"collectedAt": NOW, "viewCount": 1_000_000}
        modest_but_rising = {"collectedAt": NOW, "viewCount": 1_000, "viewCountVelocity": 500.0}
        self.assertGreater(
            content_score(modest_but_rising, now=NOW), content_score(large_and_flat, now=NOW),
        )

    def test_a_provider_correction_never_produces_a_negative_contribution(self):
        # ContentStore.save() clamps drops to 0.0 before this is ever stored; the scorer
        # only ever needs to treat a velocity value as an upper-bounded positive signal.
        item = {"collectedAt": NOW, "viewCountVelocity": 0.0}
        self.assertNotIn("트렌드 상승", dict(score_breakdown(item, now=NOW)))


class ScoreBreakdownTests(unittest.TestCase):
    def test_breakdown_points_sum_to_the_total_score(self):
        item = {
            "collectedAt": NOW, "sourceTier": "OFFICIAL", "region": "KR",
            "entityType": "PRODUCT", "saleStatus": "PREORDER", "title": "한정판 피규어",
            "viewCount": 20_000, "viewCountVelocity": 40.0,
        }
        breakdown = score_breakdown(item, now=NOW)
        self.assertEqual(round(sum(points for _, points in breakdown), 1), content_score(item, now=NOW))

    def test_breakdown_omits_zero_value_components(self):
        item = {"collectedAt": NOW}
        breakdown = score_breakdown(item, now=NOW)
        self.assertEqual([label for label, _ in breakdown], ["신선도"])

    def test_breakdown_is_sorted_by_contribution_descending(self):
        item = {
            "collectedAt": NOW, "sourceTier": "OFFICIAL", "region": "KR",
            "trending": 500, "viewCountVelocity": 500.0,
        }
        breakdown = score_breakdown(item, now=NOW)
        points = [pts for _, pts in breakdown]
        self.assertEqual(points, sorted(points, reverse=True))


if __name__ == "__main__":
    unittest.main()
