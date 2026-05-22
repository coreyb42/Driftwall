"""Driftwall-specific sidecar integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any

from driftwall.classifier import classify_image, flatten_classification, hash_file, load_prompt, prepare_image
from driftwall.config import OllamaConfig
from driftwall.db import ImageRecord

from . import coerce_document, load_sidecar, write_sidecar


DRIFTWALL_CLASSIFICATION_ENTRY = "driftwall.classification"
DRIFTWALL_IMAGE_RECORD_ENTRY = "driftwall.image_record"


@dataclass
class DriftwallSidecarScanResult:
    status: str
    record: ImageRecord
    document: dict[str, Any]


def upsert_driftwall_classification(
    document: dict[str, Any] | None,
    *,
    image_path: Path,
    file_hash: str,
    file_size: int,
    raw: dict[str, Any],
    classified_at: str,
    prompt_text: str,
    model: str,
) -> dict[str, Any]:
    document = coerce_document(
        document,
        image_path=image_path,
        file_hash=file_hash,
        file_size=file_size,
    )
    document["entries"][DRIFTWALL_CLASSIFICATION_ENTRY] = {
        "entry_version": 1,
        "classified_at": classified_at,
        "model": model,
        "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "raw": raw,
    }
    return document


def upsert_driftwall_image_record(
    document: dict[str, Any] | None,
    *,
    image_path: Path,
    record: ImageRecord,
) -> dict[str, Any]:
    document = coerce_document(
        document,
        image_path=image_path,
        file_hash=record.file_hash,
        file_size=record.file_size,
    )
    payload = asdict(record)
    payload.pop("id", None)
    document["entries"][DRIFTWALL_IMAGE_RECORD_ENTRY] = {
        "entry_version": 1,
        "record": payload,
    }
    return document


def extract_current_driftwall_image_record(
    image_path: Path,
    *,
    file_hash: str,
    last_seen_at: str,
) -> ImageRecord | None:
    document = load_sidecar(image_path)
    if document is None:
        return None

    image = document.get("image", {})
    if image.get("file_hash") != file_hash:
        return None

    file_size = int(image.get("file_size") or image_path.stat().st_size)
    entries = document.get("entries", {})

    classification = entries.get(DRIFTWALL_CLASSIFICATION_ENTRY)
    if isinstance(classification, dict) and isinstance(classification.get("raw"), dict):
        return flatten_classification(
            classification["raw"],
            image_path,
            file_hash,
            file_size,
            str(classification.get("classified_at", "")),
            last_seen_at,
        )

    exported = entries.get(DRIFTWALL_IMAGE_RECORD_ENTRY)
    if isinstance(exported, dict) and isinstance(exported.get("record"), dict):
        record = ImageRecord(**exported["record"])
        record.path = str(image_path)
        record.file_hash = file_hash
        record.file_size = file_size
        record.last_seen_at = last_seen_at
        return record

    return None


def scan_image_with_driftwall(
    image_path: Path,
    *,
    prompt_path: Path,
    model: str,
    host: str = "http://localhost:11434",
    max_image_pixels: int = 1344,
    num_predict: int = 48000,
    classified_at: str | None = None,
) -> DriftwallSidecarScanResult:
    file_hash = hash_file(image_path)
    file_size = image_path.stat().st_size

    from datetime import datetime, timezone

    now = classified_at or datetime.now(timezone.utc).isoformat()
    cached = extract_current_driftwall_image_record(
        image_path,
        file_hash=file_hash,
        last_seen_at=now,
    )
    if cached is not None:
        document = load_sidecar(image_path)
        assert document is not None
        return DriftwallSidecarScanResult(status="cached", record=cached, document=document)

    prompt_text = load_prompt(prompt_path)
    image_bytes = prepare_image(image_path, max_image_pixels)
    raw = classify_image(
        image_path,
        prompt_text,
        OllamaConfig(
            model=model,
            host=host,
            max_image_pixels=max_image_pixels,
            num_predict=num_predict,
        ),
        image_bytes=image_bytes,
    )
    record = flatten_classification(raw, image_path, file_hash, file_size, now, now)
    document = upsert_driftwall_classification(
        load_sidecar(image_path),
        image_path=image_path,
        file_hash=file_hash,
        file_size=file_size,
        raw=raw,
        classified_at=now,
        prompt_text=prompt_text,
        model=model,
    )
    document = upsert_driftwall_image_record(document, image_path=image_path, record=record)
    write_sidecar(image_path, document)
    return DriftwallSidecarScanResult(status="classified", record=record, document=document)
