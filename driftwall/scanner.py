"""Directory scanner: walks image_dir, classifies new images, updates DB."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from image_sidecar import load_sidecar, write_sidecar
from image_sidecar.driftwall import (
    extract_current_driftwall_image_record,
    upsert_driftwall_classification,
    upsert_driftwall_image_record,
)

from .classifier import (
    ClassificationError,
    ClassificationParseError,
    classify_image,
    classify_image_grok,
    flatten_classification,
    hash_file,
    load_prompt,
    prepare_image,
)
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


class ImagePrepQueue:
    """Background, bounded image preparation queue."""

    def __init__(self, max_queue: int, max_pixels: int) -> None:
        self._sema = threading.BoundedSemaphore(max_queue)
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._max_pixels = max_pixels

    def submit(self, path: Path) -> Future[bytes]:
        self._sema.acquire()

        def task() -> bytes:
            try:
                return prepare_image(path, self._max_pixels)
            finally:
                self._sema.release()

        return self._executor.submit(task)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._")
    return cleaned or "unknown"


def _write_llm_failure(path: Path, text: str) -> Path | None:
    base_dir = Path(__file__).resolve().parent / "llm_failures"
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = _sanitize_filename(path.stem)
    suffix = _sanitize_filename(path.suffix.lstrip(".")) if path.suffix else "img"
    filename = f"{stem}__{timestamp}__{time.time_ns()}.{suffix}.txt"
    out_path = base_dir / filename
    out_path.write_text(text, encoding="utf-8")
    return out_path


def _scan_file(
    path: Path,
    db_path: Path,
    prompt: str,
    config: Config,
    force_reclassify: bool,
    dry_run: bool,
    prep_queue: ImagePrepQueue | None,
    show_output: bool = False,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """
    Process a single image file.
    Returns (status, error_message, raw_output) where status is 'new'|'known'|'error'.
    raw_output is populated only when show_output=True and status=='new'.
    """
    now = _now_utc()
    try:
        file_hash = hash_file(path)
        file_size = path.stat().st_size
    except OSError as e:
        return "error", str(e), None

    existing = get_image_by_hash(db_path, file_hash)

    if not force_reclassify:
        sidecar_record = extract_current_driftwall_image_record(
            path,
            file_hash=file_hash,
            last_seen_at=now,
        )
        if sidecar_record is not None:
            if not dry_run:
                upsert_image(db_path, sidecar_record)
                if sidecar_record.path != str(path):
                    update_path(db_path, file_hash, str(path))
                logger.info("Skipping: %s  (loaded adjacent metadata)", path.name)
            return "known", None, None

    if existing and not force_reclassify:
        if not dry_run:
            if existing.path != str(path):
                logger.info("Moved:    %s  (was %s)", path, existing.path)
                update_path(db_path, file_hash, str(path))
            else:
                logger.info("Skipping: %s  (already classified)", path.name)
            mark_last_seen(db_path, file_hash, now)
            exported = replace(existing, path=str(path), file_size=file_size, last_seen_at=now)
            document = upsert_driftwall_image_record(load_sidecar(path), image_path=path, record=exported)
            write_sidecar(path, document)
        return "known", None, None

    if dry_run:
        logger.info("[dry-run] Would classify: %s", path)
        return "new", None, None

    try:
        image_bytes = None
        if prep_queue is not None:
            image_bytes = prep_queue.submit(path).result()
        if config.classifier_backend == "grok":
            raw = classify_image_grok(path, prompt, config.grok, image_bytes=image_bytes)
            model_name = config.grok.model
        else:
            raw = classify_image(path, prompt, config.ollama, image_bytes=image_bytes)
            model_name = config.ollama.model
        record = flatten_classification(raw, path, file_hash, file_size, now, now)
        upsert_image(db_path, record)
        document = upsert_driftwall_classification(
            load_sidecar(path),
            image_path=path,
            file_hash=file_hash,
            file_size=file_size,
            raw=raw,
            classified_at=now,
            prompt_text=prompt,
            model=model_name,
        )
        document = upsert_driftwall_image_record(document, image_path=path, record=record)
        write_sidecar(path, document)
        desc = f" — {record.one_paragraph}" if record.one_paragraph else ""
        logger.info("Classified: %s [%s]%s", path.name, record.genre, desc)
        return "new", None, raw if show_output else None
    except ClassificationError as e:
        if isinstance(e, ClassificationParseError) and getattr(e, "raw_text", "").strip():
            try:
                saved_path = _write_llm_failure(path, e.raw_text)
                logger.warning("Saved LLM output for %s to %s", path.name, saved_path)
            except Exception as write_error:
                logger.warning("Failed to save LLM output for %s: %s", path.name, write_error)
        logger.warning("Classification failed for %s: %s", path, e)
        return "error", str(e), None


def scan_directory(
    image_dir: Path,
    db_path: Path,
    config: Config,
    force_reclassify: bool = False,
    dry_run: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
    show_output: bool = False,
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

    if config.classifier_backend == "grok":
        concurrency = max(1, config.grok.concurrency)
        max_pixels = config.grok.max_image_pixels
    else:
        concurrency = max(1, config.ollama.concurrency)
        max_pixels = config.ollama.max_image_pixels
    prep_queue = None if dry_run else ImagePrepQueue(max_queue=3, max_pixels=max_pixels)

    def process(path: Path) -> tuple[str, str | None, dict[str, Any] | None]:
        return _scan_file(path, db_path, prompt, config, force_reclassify, dry_run, prep_queue, show_output)

    completed = 0
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(process, p): p for p in image_paths}
            for future in as_completed(futures):
                completed += 1
                status, error, raw_output = future.result()
                if status == "new":
                    result.newly_classified += 1
                elif status == "known":
                    result.already_classified += 1
                else:
                    result.skipped_errors += 1

                if raw_output is not None:
                    path = futures[future]
                    print(f"\n--- {path.name} ---")
                    print(json.dumps(raw_output, indent=2))

                if progress_callback:
                    progress_callback(completed, result.total_found)
    finally:
        if prep_queue is not None:
            prep_queue.shutdown()

    result.duration_seconds = time.monotonic() - start
    return result
