"""Ingest .txt/.md/.csv content files into ChromaDB for dynamic overlays."""

from __future__ import annotations

import csv
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

_BATCH_SIZE = 32


@dataclass
class ContentScanResult:
    total_found: int
    newly_indexed: int
    already_indexed: int
    skipped_errors: int
    duration_seconds: float


# ── text chunking ─────────────────────────────────────────────────────────────

def _looks_like_poetry(paragraph: str) -> bool:
    """Heuristic: short lines with consistent line breaks look like poetry."""
    lines = paragraph.splitlines()
    if len(lines) < 2:
        return False
    avg_len = sum(len(l) for l in lines) / len(lines)
    return avg_len < 60


def chunk_text(text: str, source_path: str) -> list:
    """Split text into coherent prose chunks of 300–600 characters.

    Returns list of ContentChunk objects.
    """
    from .content_store import ContentChunk

    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Split on blank lines (paragraph breaks)
    paragraphs = re.split(r"\n{2,}", text)

    chunks: list[str] = []
    pending = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Poetry: keep short-line blocks as-is regardless of length
        if _looks_like_poetry(para):
            if pending:
                chunks.append(pending)
                pending = ""
            chunks.append(para)
            continue

        # Normalize hard line-wrapping (single newlines) to spaces.
        # Project Gutenberg and similar sources wrap prose at ~70 chars.
        para = re.sub(r"\n", " ", para)
        para = re.sub(r" {2,}", " ", para).strip()

        # Long paragraph: split on sentence boundaries
        if len(para) > 600:
            sentences = re.split(r"(?<=[.?!])\s+", para)
            buf = ""
            for sent in sentences:
                if len(buf) + len(sent) + 1 > 600 and buf:
                    chunks.append(buf.strip())
                    buf = sent
                else:
                    buf = (buf + " " + sent).strip() if buf else sent
            if buf:
                if pending:
                    combined = pending + " " + buf
                    if len(combined) <= 600:
                        pending = combined
                        continue
                    else:
                        chunks.append(pending)
                        pending = buf
                else:
                    pending = buf
            continue

        # Short paragraph: try to merge with pending
        if len(para) < 100:
            candidate = (pending + "\n" + para).strip() if pending else para
            if len(candidate) <= 600:
                pending = candidate
                continue
            else:
                if pending:
                    chunks.append(pending)
                pending = para
            continue

        # Normal paragraph
        if pending:
            chunks.append(pending)
            pending = ""
        chunks.append(para)

    if pending:
        chunks.append(pending)

    return [
        ContentChunk(
            id=f"{source_path}::{i}",
            text=chunk,
            source_path=source_path,
            source_type="text",
            chunk_index=i,
            metadata={"source_title": Path(source_path).stem},
        )
        for i, chunk in enumerate(chunks)
        if chunk.strip()
    ]


def parse_csv_quotes(csv_path: Path) -> list:
    """Parse a CSV file with columns: text (required), author, date, source.

    Returns list of ContentChunk objects (one per row).
    """
    from .content_store import ContentChunk

    chunks = []
    source_path = str(csv_path)
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            text = (row.get("text") or "").strip()
            if not text:
                continue
            metadata: dict = {}
            for col in ("author", "date", "source"):
                val = (row.get(col) or "").strip()
                if val:
                    metadata[col] = val
            chunks.append(
                ContentChunk(
                    id=f"{source_path}::{i}",
                    text=text,
                    source_path=source_path,
                    source_type="quote",
                    chunk_index=i,
                    metadata=metadata,
                )
            )
    return chunks


# ── hashing ───────────────────────────────────────────────────────────────────

def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ── embedding ─────────────────────────────────────────────────────────────────

def embed_chunks(chunks: list, embed_model: str, host: str) -> list[list[float]]:
    """Embed a list of ContentChunk objects using Ollama. Returns list of embeddings."""
    import ollama  # type: ignore[import]
    client = ollama.Client(host=host)
    all_embeddings: list[list[float]] = []
    for i in range(0, len(chunks), _BATCH_SIZE):
        batch = chunks[i : i + _BATCH_SIZE]
        texts = [c.text for c in batch]
        resp = client.embed(model=embed_model, input=texts)
        all_embeddings.extend(resp.embeddings)
    return all_embeddings


# ── main entry point ──────────────────────────────────────────────────────────

def scan_content_dir(
    content_dir: Path,
    db_path: Path,
    chroma_path: Path,
    config,  # Config
    force_reindex: bool = False,
    progress_callback: Callable | None = None,
) -> ContentScanResult:
    """Scan content_dir for .txt/.md/.csv files, embed, and store in ChromaDB."""
    from .content_store import get_chroma_client, get_collection, add_chunks, delete_by_source
    from .db import get_content_source, upsert_content_source, init_db

    t_start = time.monotonic()
    init_db(db_path)

    client = get_chroma_client(chroma_path)
    collection = get_collection(client)

    files = sorted(
        f for f in content_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in (".txt", ".md", ".csv")
    )

    total_found = len(files)
    newly_indexed = 0
    already_indexed = 0
    skipped_errors = 0

    for idx, file_path in enumerate(files):
        if progress_callback:
            progress_callback(idx, total_found)

        source_path = str(file_path)
        try:
            file_hash = hash_file(file_path)
        except OSError as e:
            log.warning("Cannot read %s: %s", file_path, e)
            skipped_errors += 1
            continue

        # Dedup check
        if not force_reindex:
            existing = get_content_source(db_path, source_path)
            if existing and existing["file_hash"] == file_hash:
                log.debug("Already indexed (unchanged): %s", file_path.name)
                already_indexed += 1
                continue

        # Parse chunks
        try:
            if file_path.suffix.lower() == ".csv":
                chunks = parse_csv_quotes(file_path)
            else:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                chunks = chunk_text(text, source_path)
        except Exception as e:
            log.warning("Failed to parse %s: %s", file_path, e)
            skipped_errors += 1
            continue

        if not chunks:
            log.debug("No chunks extracted from %s", file_path.name)
            upsert_content_source(db_path, source_path, file_hash, 0)
            newly_indexed += 1
            continue

        # Embed
        try:
            embeddings = embed_chunks(chunks, config.content.embed_model, config.ollama.host)
        except Exception as e:
            log.warning("Embedding failed for %s: %s", file_path.name, e)
            skipped_errors += 1
            continue

        # Remove old entries for this source, then add fresh
        delete_by_source(collection, source_path)
        add_chunks(collection, chunks, embeddings)
        upsert_content_source(db_path, source_path, file_hash, len(chunks))
        log.info("Indexed %d chunks from %s", len(chunks), file_path.name)
        newly_indexed += 1

    if progress_callback:
        progress_callback(total_found, total_found)

    return ContentScanResult(
        total_found=total_found,
        newly_indexed=newly_indexed,
        already_indexed=already_indexed,
        skipped_errors=skipped_errors,
        duration_seconds=time.monotonic() - t_start,
    )
