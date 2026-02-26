"""Directory scanner: walks image_dir, classifies new images, updates DB."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .classifier import ClassificationError, classify_image, flatten_classification, hash_file, load_prompt
from .config import Config
from .db import ImageRecord, get_image_by_hash, init_db, mark_last_seen, update_path, upsert_image

logger = logging.getLogger(__name__)

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp"}


@dataclass
class ScanResult:
    total_found: int = 0
    newly_classified: int = 0
    already_classified: int = 0
    skipped_errors: int = 0
    duration_seconds: float = 0.0


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scan_file(
    path: Path,
    db_path: Path,
    prompt: str,
    config: Config,
    force_reclassify: bool,
    dry_run: bool,
) -> tuple[str, str | None]:
    """
    Process a single image file.
    Returns (status, error_message) where status is 'new'|'known'|'error'.
    """
    now = _now_utc()
    try:
        file_hash = hash_file(path)
        file_size = path.stat().st_size
    except OSError as e:
        return "error", str(e)

    existing = get_image_by_hash(db_path, file_hash)

    if existing and not force_reclassify:
        if not dry_run:
            if existing.path != str(path):
                logger.info("Moved:    %s  (was %s)", path.name, Path(existing.path).name)
                update_path(db_path, file_hash, str(path))
            else:
                logger.info("Skipping: %s  (already classified)", path.name)
            mark_last_seen(db_path, file_hash, now)
        return "known", None

    if dry_run:
        logger.info("[dry-run] Would classify: %s", path)
        return "new", None

    try:
        raw = classify_image(path, prompt, config.ollama)
        record = flatten_classification(raw, path, file_hash, file_size, now, now)
        upsert_image(db_path, record)
        desc = f" — {record.one_paragraph}" if record.one_paragraph else ""
        logger.info("Classified: %s [%s]%s", path.name, record.genre, desc)
        return "new", None
    except ClassificationError as e:
        logger.warning("Classification failed for %s: %s", path, e)
        return "error", str(e)


def scan_directory(
    image_dir: Path,
    db_path: Path,
    config: Config,
    force_reclassify: bool = False,
    dry_run: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """
    Walk image_dir, classify new images, update existing records.
    """
    if not image_dir.exists():
        raise FileNotFoundError(f"Image directory not found: {image_dir}")

    if not dry_run:
        init_db(db_path)

    prompt = load_prompt(config.prompt_path)

    image_paths = [
        p for p in image_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in VALID_EXTENSIONS
    ]

    result = ScanResult(total_found=len(image_paths))
    start = time.monotonic()

    concurrency = max(1, config.ollama.concurrency)

    def process(path: Path) -> tuple[str, str | None]:
        return _scan_file(path, db_path, prompt, config, force_reclassify, dry_run)

    completed = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(process, p): p for p in image_paths}
        for future in as_completed(futures):
            completed += 1
            status, error = future.result()
            if status == "new":
                result.newly_classified += 1
            elif status == "known":
                result.already_classified += 1
            else:
                result.skipped_errors += 1

            if progress_callback:
                progress_callback(completed, result.total_found)

    result.duration_seconds = time.monotonic() - start
    return result
