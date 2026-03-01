from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from driftwall.config import TimeOfDayMapping, TriggerConfig
from driftwall.triggers import (
    FilterCriteria,
    SeasonTrigger,
    TimeOfDayTrigger,
    get_active_triggers,
    merge_criteria,
)


class _MockDateTime:
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)

    @classmethod
    def now(cls, _tz):
        return cls.fixed_now


class TriggerTests(unittest.TestCase):
    def test_get_active_triggers_respects_enabled_flag(self) -> None:
        self.assertEqual(get_active_triggers(TriggerConfig(enabled=False)), [])
        self.assertEqual(len(get_active_triggers(TriggerConfig(enabled=True))), 2)

    def test_time_of_day_trigger_uses_custom_mapping(self) -> None:
        _MockDateTime.fixed_now = datetime(2025, 3, 1, 9, 30, 0)
        cfg = TriggerConfig(
            enabled=True,
            time_of_day_map=[
                TimeOfDayMapping(hours=[9, 10], values=["morning", "blue_hour"])
            ],
        )

        with patch("driftwall.triggers.datetime", _MockDateTime):
            criteria = TimeOfDayTrigger().get_criteria(cfg)

        self.assertEqual(criteria.prefer_time_of_day, ["morning", "blue_hour"])

    def test_season_trigger_uses_custom_map(self) -> None:
        _MockDateTime.fixed_now = datetime(2025, 7, 4, 12, 0, 0)
        cfg = TriggerConfig(enabled=True, season_map={"dry": [6, 7, 8]})

        with patch("driftwall.triggers.datetime", _MockDateTime):
            criteria = SeasonTrigger().get_criteria(cfg)

        self.assertEqual(criteria.prefer_season, ["dry"])

    def test_merge_criteria_unions_lists_and_uses_maximums(self) -> None:
        first = FilterCriteria(
            require_genre=["landscape"],
            exclude_genre=["portrait"],
            require_setting=["outdoor"],
            prefer_time_of_day=["morning"],
            exclude_faces=True,
            min_megapixels=2.0,
        )
        second = FilterCriteria(
            require_genre=["landscape", "cityscape"],
            exclude_genre=["screenshot"],
            require_setting=["indoor", "outdoor"],
            prefer_time_of_day=["golden_hour", "morning"],
            min_megapixels=3.5,
        )

        merged = merge_criteria(first, second)

        self.assertEqual(merged.require_genre, ["landscape", "cityscape"])
        self.assertEqual(merged.exclude_genre, ["portrait", "screenshot"])
        self.assertEqual(merged.require_setting, ["outdoor", "indoor"])
        self.assertEqual(merged.prefer_time_of_day, ["morning", "golden_hour"])
        self.assertTrue(merged.exclude_faces)
        self.assertEqual(merged.min_megapixels, 3.5)


if __name__ == "__main__":
    unittest.main()
