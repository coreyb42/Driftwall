"""Image selection: builds SQL queries from FilterCriteria and does weighted random picks."""

from __future__ import annotations

import logging
import random
from typing import Any

from .config import Config, FilterConfig
from .db import ImageRecord, get_recent_image_ids, query_images, record_shown
from .triggers import FilterCriteria

logger = logging.getLogger(__name__)


def build_query(criteria: FilterCriteria, filter_config: FilterConfig) -> tuple[list[str], list[Any]]:
    """
    Translate hard filter criteria + global filter config into
    (where_clauses, params) for query_images().
    """
    clauses: list[str] = []
    params: list[Any] = []

    # Hard: require specific time_of_day
    if criteria.require_time_of_day:
        placeholders = ", ".join("?" for _ in criteria.require_time_of_day)
        clauses.append(f"time_of_day IN ({placeholders})")
        params.extend(criteria.require_time_of_day)

    # Hard: require specific season
    if criteria.require_season:
        placeholders = ", ".join("?" for _ in criteria.require_season)
        clauses.append(f"season IN ({placeholders})")
        params.extend(criteria.require_season)

    # Hard: require specific genre
    if criteria.require_genre:
        placeholders = ", ".join("?" for _ in criteria.require_genre)
        clauses.append(f"genre IN ({placeholders})")
        params.extend(criteria.require_genre)

    # Hard: exclude genre (from criteria + global config)
    all_excluded_genres = list({*criteria.exclude_genre, *filter_config.exclude_genre})
    if all_excluded_genres:
        placeholders = ", ".join("?" for _ in all_excluded_genres)
        clauses.append(f"(genre IS NULL OR genre NOT IN ({placeholders}))")
        params.extend(all_excluded_genres)

    # Hard: require orientation
    if criteria.require_orientation:
        placeholders = ", ".join("?" for _ in criteria.require_orientation)
        clauses.append(f"orientation IN ({placeholders})")
        params.extend(criteria.require_orientation)

    # Hard: require setting
    combined_setting = list({*criteria.require_setting, *filter_config.require_setting})
    if combined_setting:
        placeholders = ", ".join("?" for _ in combined_setting)
        clauses.append(f"setting IN ({placeholders})")
        params.extend(combined_setting)

    # Hard: exclude faces
    if criteria.exclude_faces or filter_config.exclude_faces:
        clauses.append("faces_present = 0")

    # Hard: minimum megapixels
    min_mp = max(criteria.min_megapixels, filter_config.min_megapixels)
    if min_mp > 0.0:
        clauses.append("megapixels >= ?")
        params.append(min_mp)

    # Hard: require orientation from global config
    if filter_config.require_orientation and not criteria.require_orientation:
        placeholders = ", ".join("?" for _ in filter_config.require_orientation)
        clauses.append(f"orientation IN ({placeholders})")
        params.extend(filter_config.require_orientation)

    return clauses, params


def score_image(record: ImageRecord, criteria: FilterCriteria) -> float:
    """
    Score an image. Base = 1.0. Soft matches add bonuses.
    """
    score = 1.0

    if criteria.prefer_time_of_day and record.time_of_day in criteria.prefer_time_of_day:
        score += 0.5

    if criteria.prefer_season and record.season in criteria.prefer_season:
        score += 0.5

    return score


def select_image(
    db_path: Any,
    criteria: FilterCriteria,
    config: Config,
) -> ImageRecord | None:
    """
    Select a wallpaper image using hard filters, recency exclusion, and soft scoring.

    Returns the selected ImageRecord, or None if no candidates available.
    """
    where_clauses, params = build_query(criteria, config.filters)

    # Step 1: Get recent image IDs for exclusion
    recent_ids = get_recent_image_ids(db_path, config.rotation.avoid_repeat_window)

    # Step 2: Query with recency exclusion
    candidates = query_images(db_path, where_clauses, params, exclude_ids=recent_ids)
    logger.debug(
        "Candidates after hard filter + recency exclusion: %d (excluded %d recent)",
        len(candidates), len(recent_ids),
    )

    # Step 3: Relax recency if no results
    if not candidates and recent_ids:
        logger.debug("Relaxing recency window — retrying without exclusion")
        candidates = query_images(db_path, where_clauses, params, exclude_ids=None)
        logger.debug("Candidates after relaxing recency: %d", len(candidates))

    if not candidates:
        logger.warning("No candidates found matching filter criteria")
        return None

    # Step 4: Score and weighted random select
    scores = [score_image(r, criteria) for r in candidates]
    selected = random.choices(candidates, weights=scores, k=1)[0]

    logger.info(
        "Selected: %s [genre=%s time_of_day=%s season=%s score=%.1f]",
        selected.path,
        selected.genre,
        selected.time_of_day,
        selected.season,
        score_image(selected, criteria),
    )

    # Step 5: Record in history
    if selected.id is not None:
        record_shown(db_path, selected.id)

    return selected
