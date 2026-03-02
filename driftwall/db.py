"""SQLite schema, connection, and all query functions for Driftwall."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT    NOT NULL UNIQUE,
    file_hash     TEXT    NOT NULL UNIQUE,
    file_size     INTEGER NOT NULL,
    classified_at TEXT    NOT NULL,
    last_seen_at  TEXT    NOT NULL,

    orientation   TEXT,
    aspect_ratio  REAL,
    aspect_class  TEXT,
    megapixels    REAL,
    crop_detected INTEGER DEFAULT 0,

    season        TEXT,
    time_of_day   TEXT,

    one_sentence  TEXT,
    one_paragraph TEXT,
    alt_text      TEXT,
    keywords      TEXT,

    primary_subject    TEXT,
    secondary_subjects TEXT,
    genre              TEXT,
    subject_distance   TEXT,

    setting       TEXT,
    environment   TEXT,
    weather       TEXT,
    lighting      TEXT,
    event_context TEXT,

    people       TEXT,
    animals      TEXT,
    objects      TEXT,
    buildings    TEXT,
    visible_text TEXT,

    dominant_lines  TEXT,
    framing         TEXT,
    depth           TEXT,
    color_palette   TEXT,
    saturation      TEXT,
    dominant_colors TEXT,
    mood            TEXT,
    style           TEXT,

    sharpness    TEXT,
    noise        TEXT,
    exposure     TEXT,
    motion_blur  TEXT,
    focus_issues TEXT,
    artifacts    TEXT,

    faces_present  INTEGER DEFAULT 0,
    sensitive      TEXT,
    release_needed INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_genre       ON images(genre);
CREATE INDEX IF NOT EXISTS idx_orientation ON images(orientation);
CREATE INDEX IF NOT EXISTS idx_season      ON images(season);
CREATE INDEX IF NOT EXISTS idx_time_of_day ON images(time_of_day);
CREATE INDEX IF NOT EXISTS idx_setting     ON images(setting);
CREATE INDEX IF NOT EXISTS idx_hash        ON images(file_hash);

CREATE TABLE IF NOT EXISTS wallpaper_history (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL REFERENCES images(id),
    shown_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_shown ON wallpaper_history(shown_at DESC);

CREATE TABLE IF NOT EXISTS content_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL UNIQUE,
    file_hash   TEXT NOT NULL,
    indexed_at  TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class ImageRecord:
    path: str = ""
    file_hash: str = ""
    file_size: int = 0
    classified_at: str = ""
    last_seen_at: str = ""

    orientation: str | None = None
    aspect_ratio: float | None = None
    aspect_class: str | None = None
    megapixels: float | None = None
    crop_detected: int = 0

    season: str | None = None
    time_of_day: str | None = None

    one_sentence: str | None = None
    one_paragraph: str | None = None
    alt_text: str | None = None
    keywords: str | None = None

    primary_subject: str | None = None
    secondary_subjects: str | None = None
    genre: str | None = None
    subject_distance: str | None = None

    setting: str | None = None
    environment: str | None = None
    weather: str | None = None
    lighting: str | None = None
    event_context: str | None = None

    people: str | None = None
    animals: str | None = None
    objects: str | None = None
    buildings: str | None = None
    visible_text: str | None = None

    dominant_lines: str | None = None
    framing: str | None = None
    depth: str | None = None
    color_palette: str | None = None
    saturation: str | None = None
    dominant_colors: str | None = None
    mood: str | None = None
    style: str | None = None

    sharpness: str | None = None
    noise: str | None = None
    exposure: str | None = None
    motion_blur: str | None = None
    focus_issues: str | None = None
    artifacts: str | None = None

    faces_present: int = 0
    sensitive: str | None = None
    release_needed: int = 0

    # Not stored in DB — populated after query
    id: int | None = field(default=None, compare=False)


_IMAGE_COLUMNS = [
    f.name for f in fields(ImageRecord) if f.name != "id"
]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass  # WAL unsupported on network/FUSE filesystems; default journal mode is fine
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create tables and indexes if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        # executescript() issues an implicit COMMIT which fails on some network filesystems;
        # run each statement individually inside the context-manager transaction instead.
        for statement in SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(stmt)


def _row_to_record(row: sqlite3.Row) -> ImageRecord:
    d = dict(row)
    return ImageRecord(
        id=d.get("id"),
        path=d.get("path", ""),
        file_hash=d.get("file_hash", ""),
        file_size=d.get("file_size", 0),
        classified_at=d.get("classified_at", ""),
        last_seen_at=d.get("last_seen_at", ""),
        orientation=d.get("orientation"),
        aspect_ratio=d.get("aspect_ratio"),
        aspect_class=d.get("aspect_class"),
        megapixels=d.get("megapixels"),
        crop_detected=d.get("crop_detected", 0),
        season=d.get("season"),
        time_of_day=d.get("time_of_day"),
        one_sentence=d.get("one_sentence"),
        one_paragraph=d.get("one_paragraph"),
        alt_text=d.get("alt_text"),
        keywords=d.get("keywords"),
        primary_subject=d.get("primary_subject"),
        secondary_subjects=d.get("secondary_subjects"),
        genre=d.get("genre"),
        subject_distance=d.get("subject_distance"),
        setting=d.get("setting"),
        environment=d.get("environment"),
        weather=d.get("weather"),
        lighting=d.get("lighting"),
        event_context=d.get("event_context"),
        people=d.get("people"),
        animals=d.get("animals"),
        objects=d.get("objects"),
        buildings=d.get("buildings"),
        visible_text=d.get("visible_text"),
        dominant_lines=d.get("dominant_lines"),
        framing=d.get("framing"),
        depth=d.get("depth"),
        color_palette=d.get("color_palette"),
        saturation=d.get("saturation"),
        dominant_colors=d.get("dominant_colors"),
        mood=d.get("mood"),
        style=d.get("style"),
        sharpness=d.get("sharpness"),
        noise=d.get("noise"),
        exposure=d.get("exposure"),
        motion_blur=d.get("motion_blur"),
        focus_issues=d.get("focus_issues"),
        artifacts=d.get("artifacts"),
        faces_present=d.get("faces_present", 0),
        sensitive=d.get("sensitive"),
        release_needed=d.get("release_needed", 0),
    )


def upsert_image(db_path: Path, record: ImageRecord) -> int:
    """Insert or update an image record. Returns the row id."""
    cols = _IMAGE_COLUMNS
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in ("path", "file_hash"))
    sql = (
        f"INSERT INTO images ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(file_hash) DO UPDATE SET {updates} "
        f"RETURNING id"
    )
    values = [getattr(record, c) for c in cols]
    with _connect(db_path) as conn:
        row = conn.execute(sql, values).fetchone()
        return row[0]


def get_image_by_hash(db_path: Path, file_hash: str) -> ImageRecord | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM images WHERE file_hash = ?", (file_hash,)
        ).fetchone()
    return _row_to_record(row) if row else None


def mark_last_seen(db_path: Path, file_hash: str, timestamp: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE images SET last_seen_at = ? WHERE file_hash = ?",
            (timestamp, file_hash),
        )


def update_path(db_path: Path, file_hash: str, new_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE images SET path = ? WHERE file_hash = ?",
            (new_path, file_hash),
        )


def query_images(
    db_path: Path,
    where_clauses: list[str],
    params: list[Any],
    exclude_ids: list[int] | None = None,
) -> list[ImageRecord]:
    """Run a parameterized SELECT with optional WHERE clauses and ID exclusion."""
    clauses = list(where_clauses)
    all_params: list[Any] = list(params)

    if exclude_ids:
        placeholders = ", ".join("?" for _ in exclude_ids)
        clauses.append(f"id NOT IN ({placeholders})")
        all_params.extend(exclude_ids)

    sql = "SELECT * FROM images"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    with _connect(db_path) as conn:
        rows = conn.execute(sql, all_params).fetchall()
    return [_row_to_record(r) for r in rows]


def record_shown(db_path: Path, image_id: int) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO wallpaper_history (image_id, shown_at) VALUES (?, ?)",
            (image_id, now),
        )


def get_recent_image_ids(db_path: Path, window: int) -> list[int]:
    """Return image IDs shown in the last `window` rotations."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT image_id FROM wallpaper_history "
            "ORDER BY shown_at DESC LIMIT ?",
            (window,),
        ).fetchall()
    return [r[0] for r in rows]


def get_content_source(db_path: Path, source_path: str) -> sqlite3.Row | None:
    """Return the content_sources row for source_path, or None if not found."""
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM content_sources WHERE source_path = ?", (source_path,)
        ).fetchone()


def list_content_source_paths(db_path: Path) -> list[str]:
    """Return all indexed content source paths from content_sources."""
    with _connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT source_path FROM content_sources ORDER BY source_path"
            ).fetchall()
        except sqlite3.OperationalError:
            # Table may not exist yet (DB predates this feature)
            return []
    return [r["source_path"] for r in rows]


def upsert_content_source(
    db_path: Path, source_path: str, file_hash: str, chunk_count: int
) -> None:
    """Insert or update a content_sources row."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO content_sources (source_path, file_hash, indexed_at, chunk_count)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(source_path) DO UPDATE SET
                   file_hash = excluded.file_hash,
                   indexed_at = excluded.indexed_at,
                   chunk_count = excluded.chunk_count""",
            (source_path, file_hash, now, chunk_count),
        )


def get_latest_shown_image(db_path: Path) -> ImageRecord | None:
    """Return the most recently shown image, or None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT i.* FROM wallpaper_history h "
            "JOIN images i ON i.id = h.image_id "
            "ORDER BY h.shown_at DESC LIMIT 1"
        ).fetchone()
    return _row_to_record(row) if row else None


def get_content_stats(db_path: Path) -> dict[str, Any]:
    """Return summary statistics from the content_sources table."""
    with _connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT source_path, file_hash, indexed_at, chunk_count "
                "FROM content_sources ORDER BY indexed_at DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            # Table may not exist yet (DB predates this feature)
            return {"total_sources": 0, "total_chunks": 0, "sources": []}

    sources = [
        {
            "source_path": r["source_path"],
            "chunk_count": r["chunk_count"],
            "indexed_at": r["indexed_at"],
        }
        for r in rows
    ]
    return {
        "total_sources": len(sources),
        "total_chunks": sum(s["chunk_count"] for s in sources),
        "sources": sources,
    }


def get_stats(db_path: Path) -> dict[str, Any]:
    """Return summary statistics from the database."""
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        genre_rows = conn.execute(
            "SELECT genre, COUNT(*) as cnt FROM images GROUP BY genre ORDER BY cnt DESC"
        ).fetchall()
        history_total = conn.execute(
            "SELECT COUNT(*) FROM wallpaper_history"
        ).fetchone()[0]
        last_shown = conn.execute(
            "SELECT i.path, h.shown_at FROM wallpaper_history h "
            "JOIN images i ON i.id = h.image_id "
            "ORDER BY h.shown_at DESC LIMIT 5"
        ).fetchall()

    return {
        "total_images": total,
        "genre_counts": {r["genre"] or "unknown": r["cnt"] for r in genre_rows},
        "total_shown": history_total,
        "last_shown": [{"path": r["path"], "shown_at": r["shown_at"]} for r in last_shown],
    }
