"""Pre-compute and cache image embeddings for content search."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .content_search import build_image_query
from .db import ImageRecord, get_images_missing_embeddings, query_images, upsert_image_embedding

log = logging.getLogger(__name__)


def compute_embedding(text: str, embed_model: str, host: str) -> list[float]:
    """Return an embedding vector for text using Ollama."""
    import ollama  # type: ignore[import]
    client = ollama.Client(host=host)
    resp = client.embed(model=embed_model, input=[text])
    return resp.embeddings[0]


@dataclass
class EmbedResult:
    total: int
    embedded: int
    skipped_no_text: int
    errors: int


def embed_all_images(
    db_path: Path,
    embed_model: str,
    host: str,
    force: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> EmbedResult:
    """Compute and store embeddings for images that are missing them.

    If *force* is True, re-embeds all images regardless of existing embeddings.
    """
    if force:
        images = query_images(db_path, [], [])
    else:
        images = get_images_missing_embeddings(db_path, embed_model)

    total = len(images)
    embedded = skipped = errors = 0

    for i, image in enumerate(images):
        if progress_callback:
            progress_callback(i, total)

        query_text = build_image_query(image)
        if not query_text.strip():
            skipped += 1
            continue

        try:
            embedding = compute_embedding(query_text, embed_model, host)
            upsert_image_embedding(db_path, image.file_hash, embed_model, embedding)
            embedded += 1
        except Exception as exc:
            log.warning("Failed to embed %s: %s", image.path, exc)
            errors += 1

    if progress_callback:
        progress_callback(total, total)

    return EmbedResult(total=total, embedded=embedded, skipped_no_text=skipped, errors=errors)
