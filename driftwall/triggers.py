"""Trigger system: derives FilterCriteria from real-time context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import TriggerConfig


@dataclass
class FilterCriteria:
    # Hard filters — become SQL WHERE clauses
    require_time_of_day: list[str] = field(default_factory=list)
    require_season: list[str] = field(default_factory=list)
    require_genre: list[str] = field(default_factory=list)
    exclude_genre: list[str] = field(default_factory=list)
    require_orientation: list[str] = field(default_factory=list)
    exclude_faces: bool = False
    min_megapixels: float = 0.0
    require_setting: list[str] = field(default_factory=list)

    # Soft filters — used as scoring bonuses only
    prefer_time_of_day: list[str] = field(default_factory=list)
    prefer_season: list[str] = field(default_factory=list)


# Default time-of-day hour ranges
_DEFAULT_TOD_MAP: list[tuple[range, list[str]]] = [
    (range(0, 5),  ["night"]),
    (range(5, 7),  ["blue_hour", "sunrise"]),
    (range(7, 10), ["morning"]),
    (range(10, 14), ["midday"]),
    (range(14, 17), ["afternoon"]),
    (range(17, 19), ["golden_hour"]),
    (range(19, 21), ["sunset"]),
    (range(21, 24), ["night"]),
]

# Default season map: month -> season
_DEFAULT_SEASON_MAP: dict[int, str] = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring",  4: "spring", 5: "spring",
    6: "summer",  7: "summer", 8: "summer",
    9: "fall",   10: "fall",  11: "fall",
}


class BaseTrigger:
    def get_criteria(self, config: TriggerConfig) -> FilterCriteria:
        return FilterCriteria()


class TimeOfDayTrigger(BaseTrigger):
    """Maps current hour to preferred time_of_day values (soft preference)."""

    def get_criteria(self, config: TriggerConfig) -> FilterCriteria:
        now = datetime.now(timezone.utc).astimezone()
        hour = now.hour
        tod_values: list[str] = []

        if config.time_of_day_map:
            for mapping in config.time_of_day_map:
                if hour in mapping.hours:
                    tod_values = mapping.values
                    break
        else:
            for hour_range, values in _DEFAULT_TOD_MAP:
                if hour in hour_range:
                    tod_values = values
                    break

        return FilterCriteria(prefer_time_of_day=tod_values)


class SeasonTrigger(BaseTrigger):
    """Maps current month to preferred season (soft preference)."""

    def get_criteria(self, config: TriggerConfig) -> FilterCriteria:
        now = datetime.now(timezone.utc).astimezone()
        month = now.month
        season: str | None = None

        if config.season_map:
            # Config season_map keys are season names, values are month lists or ranges
            # Format: {"winter": [12, 1, 2], "spring": [3, 4, 5], ...}
            for season_name, months in config.season_map.items():
                if isinstance(months, list) and month in months:
                    season = season_name
                    break
        else:
            season = _DEFAULT_SEASON_MAP.get(month)

        prefer = [season] if season else []
        return FilterCriteria(prefer_season=prefer)


def get_active_triggers(config: TriggerConfig) -> list[BaseTrigger]:
    """Return all enabled trigger instances."""
    if not config.enabled:
        return []
    return [TimeOfDayTrigger(), SeasonTrigger()]


def merge_criteria(*criteria: FilterCriteria) -> FilterCriteria:
    """Merge multiple FilterCriteria by union of lists, OR logic for booleans."""
    merged = FilterCriteria()
    for c in criteria:
        merged.require_time_of_day = _dedup(merged.require_time_of_day + c.require_time_of_day)
        merged.require_season = _dedup(merged.require_season + c.require_season)
        merged.require_genre = _dedup(merged.require_genre + c.require_genre)
        merged.exclude_genre = _dedup(merged.exclude_genre + c.exclude_genre)
        merged.require_orientation = _dedup(merged.require_orientation + c.require_orientation)
        merged.require_setting = _dedup(merged.require_setting + c.require_setting)
        merged.exclude_faces = merged.exclude_faces or c.exclude_faces
        merged.min_megapixels = max(merged.min_megapixels, c.min_megapixels)
        merged.prefer_time_of_day = _dedup(merged.prefer_time_of_day + c.prefer_time_of_day)
        merged.prefer_season = _dedup(merged.prefer_season + c.prefer_season)
    return merged


def _dedup(lst: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in lst:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
