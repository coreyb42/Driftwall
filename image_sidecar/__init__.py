"""Portable adjacent metadata for image files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_NAME = "image-sidecar"
SCHEMA_VERSION = 1


def sidecar_path_for_image(image_path: Path) -> Path:
    return image_path.with_name(f".{image_path.name}.imgmeta.json")


def upgrade_document(document: dict[str, Any]) -> dict[str, Any]:
    version = int(document.get("schema_version", 0))
    if version == SCHEMA_VERSION:
        return document
    raise ValueError(f"Unsupported sidecar schema version: {version}")


def base_document(image_path: Path, *, file_hash: str, file_size: int) -> dict[str, Any]:
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "image": {
            "file_name": image_path.name,
            "file_hash": file_hash,
            "file_size": file_size,
        },
        "entries": {},
    }


def coerce_document(
    document: dict[str, Any] | None,
    *,
    image_path: Path,
    file_hash: str,
    file_size: int,
) -> dict[str, Any]:
    if document is None:
        document = base_document(image_path, file_hash=file_hash, file_size=file_size)
    else:
        document = upgrade_document(document)
        document.setdefault("schema_name", SCHEMA_NAME)
        document.setdefault("schema_version", SCHEMA_VERSION)
        document.setdefault("image", {})
        document.setdefault("entries", {})

    image = document["image"]
    image["file_name"] = image_path.name
    image["file_hash"] = file_hash
    image["file_size"] = file_size
    return document


def load_sidecar(image_path: Path) -> dict[str, Any] | None:
    path = sidecar_path_for_image(image_path)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return upgrade_document(json.load(handle))


def write_sidecar(image_path: Path, document: dict[str, Any]) -> None:
    path = sidecar_path_for_image(image_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)
