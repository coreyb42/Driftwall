from __future__ import annotations

import unittest
from unittest.mock import patch

from driftwall.config import Config, FilterConfig, RotationConfig
from driftwall.db import ImageRecord
from driftwall.selector import build_query, score_image, select_image
from driftwall.triggers import FilterCriteria


class SelectorTests(unittest.TestCase):
    def test_build_query_includes_hard_filters_and_global_fallbacks(self) -> None:
        criteria = FilterCriteria(
            require_time_of_day=["morning"],
            require_season=["spring"],
            require_genre=["landscape"],
            exclude_genre=["portrait"],
            require_setting=["outdoor"],
            exclude_faces=True,
            min_megapixels=3.0,
        )
        filter_cfg = FilterConfig(
            exclude_genre=["screenshot"],
            require_orientation=["landscape"],
            require_setting=["nature"],
            min_megapixels=2.0,
        )

        clauses, params = build_query(criteria, filter_cfg)

        self.assertIn("time_of_day IN (?)", clauses)
        self.assertIn("season IN (?)", clauses)
        self.assertIn("genre IN (?)", clauses)
        self.assertIn("faces_present = 0", clauses)
        self.assertIn("megapixels >= ?", clauses)
        self.assertIn("orientation IN (?)", clauses)
        self.assertIn("(genre IS NULL OR genre NOT IN (?, ?))", clauses)
        self.assertIn("setting IN (?, ?)", clauses)

        self.assertIn("morning", params)
        self.assertIn("spring", params)
        self.assertIn("landscape", params)
        self.assertIn(3.0, params)
        self.assertTrue({"portrait", "screenshot"}.issubset(set(params)))
        self.assertTrue({"outdoor", "nature"}.issubset(set(params)))

    def test_score_image_adds_soft_preference_bonuses(self) -> None:
        record = ImageRecord(time_of_day="morning", season="winter")
        criteria = FilterCriteria(prefer_time_of_day=["morning"], prefer_season=["winter"])

        self.assertEqual(score_image(record, criteria), 2.0)

    def test_select_image_relaxes_recency_and_records_selected_id(self) -> None:
        chosen = ImageRecord(id=7, path="/tmp/one.jpg", time_of_day="morning", season="spring")
        calls = {"query": 0, "recorded": []}

        def fake_recent_ids(_db_path, _window):
            return [7]

        def fake_query_images(_db_path, _clauses, _params, exclude_ids=None):
            calls["query"] += 1
            if exclude_ids:
                return []
            return [chosen]

        def fake_record_shown(_db_path, image_id):
            calls["recorded"].append(image_id)

        def fake_choices(seq, weights, k):
            self.assertEqual(k, 1)
            self.assertEqual(seq, [chosen])
            self.assertEqual(weights, [1.0])
            return [seq[0]]

        with patch("driftwall.selector.get_recent_image_ids", fake_recent_ids), patch(
            "driftwall.selector.query_images", fake_query_images
        ), patch("driftwall.selector.record_shown", fake_record_shown), patch(
            "driftwall.selector.random.choices", fake_choices
        ):
            config = Config(filters=FilterConfig(), rotation=RotationConfig(avoid_repeat_window=10))
            selected = select_image("unused.db", FilterCriteria(), config)

        self.assertEqual(selected, chosen)
        self.assertEqual(calls["query"], 2)
        self.assertEqual(calls["recorded"], [7])


if __name__ == "__main__":
    unittest.main()
