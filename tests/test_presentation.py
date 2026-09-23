"""content_score/score_breakdown: freshness plus flat bonuses only.

View/like counts, their velocities and AniList metrics were removed from scoring, so
a score depends only on how fresh an item is and a few yes/no bonuses.
"""

import unittest
from datetime import datetime, timedelta, timezone

from subculture.shared.presentation import card_view, content_score, score_breakdown, signal_labels

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class RemovedEngagementSignalTests(unittest.TestCase):
    def test_view_like_and_anilist_fields_no_longer_score(self):
        plain = {"collectedAt": NOW}
        engaged = {
            "collectedAt": NOW, "viewCount": 1_000_000, "likeCount": 50_000,
            "viewCountVelocity": 500.0, "likeCountVelocity": 50.0,
            "trending": 500, "popularity": 50_000, "favourites": 10_000, "averageScore": 90,
        }
        self.assertEqual(content_score(engaged, now=NOW), content_score(plain, now=NOW))
        self.assertEqual([label for label, _ in score_breakdown(engaged, now=NOW)], ["신선도"])

    def test_no_hot_label_even_for_a_top_scoring_item(self):
        item = {
            "collectedAt": NOW, "sourceTier": "OFFICIAL", "region": "KR",
            "entityType": "PRODUCT", "saleStatus": "PREORDER", "title": "한정판 피규어",
        }
        self.assertNotIn("HOT", signal_labels(item))

    def test_no_trend_label_and_no_metric_caption(self):
        item = {"collectedAt": NOW, "viewCountVelocity": 500.0, "viewCount": 10}
        self.assertNotIn("TREND", signal_labels(item))
        self.assertNotIn("metric_caption", card_view(item))


class ScoreTests(unittest.TestCase):
    def test_fresher_items_score_higher(self):
        self.assertGreater(
            content_score({"collectedAt": NOW}, now=NOW),
            content_score({"collectedAt": NOW - timedelta(days=2)}, now=NOW),
        )

    def test_breakdown_points_sum_to_the_total_score(self):
        item = {
            "collectedAt": NOW, "sourceTier": "OFFICIAL", "region": "KR",
            "entityType": "PRODUCT", "saleStatus": "PREORDER", "title": "한정판 피규어",
        }
        breakdown = score_breakdown(item, now=NOW)
        self.assertEqual(round(sum(points for _, points in breakdown), 1), content_score(item, now=NOW))

    def test_breakdown_omits_zero_value_components(self):
        breakdown = score_breakdown({"collectedAt": NOW}, now=NOW)
        self.assertEqual([label for label, _ in breakdown], ["신선도"])

    def test_breakdown_is_sorted_by_contribution_descending(self):
        item = {"collectedAt": NOW, "sourceTier": "OFFICIAL", "region": "KR"}
        points = [pts for _, pts in score_breakdown(item, now=NOW)]
        self.assertEqual(points, sorted(points, reverse=True))


if __name__ == "__main__":
    unittest.main()
