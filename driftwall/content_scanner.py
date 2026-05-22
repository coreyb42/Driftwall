"""Ingest text and ebook content files into ChromaDB for dynamic overlays.

Supported formats (plain text, always available):
    .txt  .md  .rst  .csv

Supported formats (require optional dependencies):
    .epub  — pip install ebooklib beautifulsoup4
    .pdf   — pip install pypdf
    .html  .htm  — pip install beautifulsoup4
    .docx  — pip install python-docx
    .mobi  — pip install mobi
"""

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

# Minimum characters a chunk must have to be included in output.
_MIN_CHUNK_CHARS = 50


@dataclass
class ContentScanResult:
    total_found: int
    newly_indexed: int
    already_indexed: int
    skipped_errors: int
    duration_seconds: float


# ── text chunking ─────────────────────────────────────────────────────────────

# Project Gutenberg start/end markers
_PG_START = re.compile(
    r"\*{3}\s*START OF (?:THE |THIS )?PROJECT GUTENBERG[^\n]*\*{3}",
    re.IGNORECASE,
)
_PG_END = re.compile(
    r"\*{3}\s*END OF (?:THE |THIS )?PROJECT GUTENBERG[^\n]*\*{3}",
    re.IGNORECASE,
)

# Table-of-contents entry pattern: "CHAPTER I.", "Book Third.", "ACT 2.", etc.
_TOC_ENTRY_RE = re.compile(
    r"^\s*(?:chapter|part|book|act|scene|volume|section)\s+"
    r"(?:[ivxlcdmIVXLCDM]+|\d+)\b",
    re.IGNORECASE,
)


def _strip_gutenberg_boilerplate(text: str) -> str:
    """Remove Project Gutenberg header/footer boilerplate."""
    m = _PG_START.search(text)
    if m:
        text = text[m.end():]
    m = _PG_END.search(text)
    if m:
        text = text[:m.start()]
    return text


def _looks_like_poetry(paragraph: str) -> bool:
    """Heuristic: short lines with consistent line breaks look like poetry."""
    lines = paragraph.splitlines()
    if len(lines) < 2:
        return False
    avg_len = sum(len(l) for l in lines) / len(lines)
    return avg_len < 60


def _looks_like_list_block(paragraph: str) -> bool:
    """True for multi-line blocks with very short lines (character rosters, indexes).

    These are NOT poetry — they're structural lists that should be skipped.
    """
    lines = paragraph.splitlines()
    if len(lines) <= 4:
        return False
    avg_len = sum(len(l) for l in lines) / len(lines)
    return avg_len < 25


def _is_chapter_header(paragraph: str) -> bool:
    """Return True for single-line all-caps headings (chapter titles, part headers, etc.).

    A paragraph is treated as a header if:
    - it contains no internal newlines (single line after stripping), and
    - at least 60% of its alphabetic characters are uppercase.
    """
    if "\n" in paragraph:
        return False
    alpha = [c for c in paragraph if c.isalpha()]
    if not alpha:
        return False
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    return upper_ratio >= 0.60


def _is_section_title(text: str) -> bool:
    """True for short single-line paragraphs that look like section/poem titles.

    These lack terminal sentence punctuation and are short enough to be labels.
    """
    if "\n" in text:
        return False
    t = text.strip()
    if not t or len(t) > 80:
        return False
    return t[-1] not in ".?!:"


def chunk_text(text: str, source_path: str) -> list:
    """Split text into coherent prose chunks of 300–600 characters.

    Returns list of ContentChunk objects.
    """
    from .content_store import ContentChunk

    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip Project Gutenberg header/footer
    text = _strip_gutenberg_boilerplate(text)
    # Split on blank lines (paragraph breaks)
    paragraphs = re.split(r"\n{2,}", text)

    chunks: list[str] = []
    pending = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Skip chapter/part headers (single-line, mostly uppercase).
        # Also discard any accumulated section title from pending.
        if _is_chapter_header(para):
            if pending and _is_section_title(pending):
                pending = ""
            continue

        # Skip table-of-contents blocks: single or multi-line paragraphs where
        # every line matches the TOC pattern (CHAPTER I., ACT 2., BOOK THIRD., etc.)
        _para_lines = [l.strip() for l in para.splitlines() if l.strip()]
        if _para_lines and all(_TOC_ENTRY_RE.match(l) for l in _para_lines):
            continue

        # Skip list blocks (character rosters, indexes) — multi-line, very short lines.
        if _looks_like_list_block(para):
            continue

        # Poetry: keep short-line blocks verbatim.
        # If pending is a section title (poem name), attach it to the poem.
        if _looks_like_poetry(para):
            if pending:
                if _is_section_title(pending):
                    chunks.append(pending + "\n\n" + para)
                else:
                    chunks.append(pending)
                    chunks.append(para)
                pending = ""
            else:
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

    # Filter out chunks that are too short to be meaningful overlays.
    result = []
    idx = 0
    for chunk in chunks:
        if chunk.strip() and len(chunk.strip()) >= _MIN_CHUNK_CHARS:
            result.append(
                ContentChunk(
                    id=f"{source_path}::{idx}",
                    text=chunk,
                    source_path=source_path,
                    source_type="text",
                    chunk_index=idx,
                    metadata={"source_title": Path(source_path).stem},
                )
            )
            idx += 1
    return result


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


# ── binary / rich-format extractors ──────────────────────────────────────────

def _soup_to_text(soup) -> str:
    """Extract text from a BeautifulSoup tree with proper paragraph breaks.

    Appends \\n\\n after each block-level element so that chunk_text() can split
    on paragraph boundaries.  Without this, get_text() produces a wall of
    single-newline-separated lines and the entire document becomes one paragraph.
    """
    for tag in soup.find_all(
        ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
         "li", "blockquote", "pre", "tr"]
    ):
        tag.append("\n\n")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_epub(path: Path) -> str:
    """Extract plain text from an EPUB. Requires ebooklib + beautifulsoup4."""
    try:
        import ebooklib  # type: ignore[import]
        from ebooklib import epub
        from bs4 import BeautifulSoup  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "EPUB support requires: pip install ebooklib beautifulsoup4"
        ) from exc

    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    parts: list[str] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = _soup_to_text(soup)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _extract_pdf(path: Path) -> str:
    """Extract plain text from a PDF. Requires pypdf."""
    try:
        from pypdf import PdfReader  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("PDF support requires: pip install pypdf") from exc

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    return "\n\n".join(pages)


def _extract_html(path: Path) -> str:
    """Extract plain text from an HTML file. Requires beautifulsoup4."""
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "HTML support requires: pip install beautifulsoup4"
        ) from exc

    soup = BeautifulSoup(path.read_bytes(), "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return _soup_to_text(soup)


def _extract_docx(path: Path) -> str:
    """Extract plain text from a DOCX file. Requires python-docx."""
    try:
        from docx import Document  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("DOCX support requires: pip install python-docx") from exc

    doc = Document(str(path))
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paras)


def _extract_mobi(path: Path) -> str:
    """Extract plain text from a MOBI file. Requires mobi."""
    try:
        import mobi as _mobi  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("MOBI support requires: pip install mobi") from exc

    import shutil

    tmpdir, content_path = _mobi.extract(str(path))
    try:
        content = Path(content_path)
        raw = content.read_bytes()
        if content.suffix.lower() in (".html", ".htm"):
            try:
                from bs4 import BeautifulSoup  # type: ignore[import]
                soup = BeautifulSoup(raw, "html.parser")
                for tag in soup(["script", "style"]):
                    tag.decompose()
                return _soup_to_text(soup)
            except ImportError:
                pass  # fall through to raw decode
        return raw.decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# Suffix → text extractor.  .csv is dispatched separately (different return type).
_EXTRACTORS: dict[str, Callable[[Path], str]] = {
    ".txt": _read_text,
    ".md": _read_text,
    ".rst": _read_text,
    ".epub": _extract_epub,
    ".pdf": _extract_pdf,
    ".html": _extract_html,
    ".htm": _extract_html,
    ".docx": _extract_docx,
    ".mobi": _extract_mobi,
}

SUPPORTED_SUFFIXES: frozenset[str] = frozenset(_EXTRACTORS) | {".csv"}


# ── embedding ─────────────────────────────────────────────────────────────────

def embed_chunks(
    chunks: list,
    embed_model: str,
    host: str,
    source_name: str = "",
) -> list[list[float]]:
    """Embed a list of ContentChunk objects using Ollama. Returns list of embeddings."""
    import ollama  # type: ignore[import]
    client = ollama.Client(host=host)
    total = len(chunks)
    label = source_name or "chunks"
    log.info("Embedding %s — %d chunk%s", label, total, "s" if total != 1 else "")
    all_embeddings: list[list[float]] = []
    for i in range(0, total, _BATCH_SIZE):
        batch = chunks[i : i + _BATCH_SIZE]
        texts = [c.text for c in batch]
        resp = client.embed(model=embed_model, input=texts)
        all_embeddings.extend(resp.embeddings)
        if total > _BATCH_SIZE:
            done = min(i + _BATCH_SIZE, total)
            log.info("  %s: %d / %d chunks embedded", label, done, total)
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
    """Scan content_dir for supported text/ebook files, embed, and store in ChromaDB."""
    from .content_store import get_chroma_client, get_collection, add_chunks, delete_by_source
    from .db import get_content_source, upsert_content_source, init_db

    t_start = time.monotonic()
    init_db(db_path)

    client = get_chroma_client(chroma_path)
    collection = get_collection(client)

    files = sorted(
        f for f in content_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES
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
            suffix = file_path.suffix.lower()
            if suffix == ".csv":
                chunks = parse_csv_quotes(file_path)
            else:
                text = _EXTRACTORS[suffix](file_path)
                chunks = chunk_text(text, source_path)
        except ImportError as e:
            log.warning("Skipping %s — install missing dependency: %s", file_path.name, e)
            skipped_errors += 1
            continue
        except Exception as e:
            log.warning("Failed to parse %s: %s", file_path, e)
            skipped_errors += 1
            continue

        if not chunks:
            log.debug("No chunks extracted from %s", file_path.name)
            upsert_content_source(db_path, source_path, file_hash, 0)
            newly_indexed += 1
            continue

        try:
            embeddings = embed_chunks(
                chunks, config.content.embed_model, config.ollama.host,
                source_name=file_path.name,
            )
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
