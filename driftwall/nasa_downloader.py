"""NASA Image and Video Library downloader with LLM classification and people filtering."""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .config import Config
    from .db import ImageRecord

_NASA_BASE = "https://images-api.nasa.gov"

# (substring_to_match, canonical_subdir_name) — checked in order, first match wins
_MISSION_PATTERNS: list[tuple[str, str]] = [
    ("apollo", "apollo"),
    ("artemis", "artemis"),
    ("gemini", "gemini"),
    ("mercury", "mercury"),
    ("james webb", "jwst"),
    ("jwst", "jwst"),
    ("hubble", "hubble"),
    ("international space station", "iss"),
    (" iss ", "iss"),
    ("space shuttle", "shuttle"),
    ("sts-", "shuttle"),
    ("voyager", "voyager"),
    ("cassini", "cassini"),
    ("perseverance", "perseverance"),
    ("curiosity", "curiosity"),
    ("opportunity", "opportunity"),
    ("spirit rover", "spirit"),
    ("new horizons", "new-horizons"),
    ("juno", "juno"),
    ("dawn", "dawn"),
    ("mars", "mars"),
    ("lunar", "moon"),
    ("moon", "moon"),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
    ),
    "Accept": "application/json, */*",
    "Accept-Encoding": "identity",
}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def nasa_infer_mission(keywords: list[str], title: str) -> str:
    """Return a sanitized subdirectory name inferred from keywords and title."""
    haystack = " " + " ".join([kw.lower() for kw in keywords] + [title.lower()]) + " "
    for pattern, name in _MISSION_PATTERNS:
        if pattern in haystack:
            return name
    if keywords:
        safe = re.sub(r"[^\w-]", "-", keywords[0]).strip("-")[:30].lower()
        return safe or "misc"
    return "misc"


def nasa_output_subdir(base_dir: Path, mission: str) -> Path:
    return base_dir / mission


def fetch_nasa_metadata(nasa_id: str, request_delay: float = 0.5) -> dict | None:
    """Fetch title/description/keywords for an existing image by its nasa_id.

    Returns the first ``data`` dict from the search result, or None if not found.
    """
    time.sleep(request_delay)
    url = (
        f"{_NASA_BASE}/search"
        f"?nasa_id={urllib.request.quote(nasa_id, safe='')}"
        f"&media_type=image"
    )
    try:
        data = _get_json(url)
    except Exception:
        return None
    items = data.get("collection", {}).get("items", [])
    if not items:
        return None
    return items[0].get("data", [{}])[0] or None


def _get_asset_url(nasa_id: str, request_delay: float) -> str | None:
    """Fetch the NASA asset manifest and return the best available image URL."""
    time.sleep(request_delay)
    try:
        data = _get_json(
            f"{_NASA_BASE}/asset/{urllib.request.quote(nasa_id, safe='')}"
        )
    except Exception:
        return None
    items = data.get("collection", {}).get("items", [])
    hrefs = [item.get("href", "") for item in items if item.get("href")]
    for suffix in ("~orig.jpg", "~large.jpg", "~medium.jpg"):
        for href in hrefs:
            if href.lower().endswith(suffix):
                return href
    for href in hrefs:
        if href.lower().endswith((".jpg", ".jpeg", ".png")):
            return href
    return hrefs[0] if hrefs else None


def _clean_description(text: str, max_chars: int = 600) -> str:
    """Strip HTML tags, decode entities, and truncate NASA description text."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        # Truncate at a word boundary so we don't cut mid-sentence
        text = text[:max_chars].rsplit(" ", 1)[0].rstrip(" .,;") + "…"
    return text


def build_nasa_context(
    title: str,
    description: str,
    keywords: list[str],
    photographer: str = "",
    date_created: str = "",
) -> str:
    """Build a context string from NASA image metadata for LLM classification."""
    parts: list[str] = []
    if title:
        parts.append(f"Title: {title}")
    if date_created:
        parts.append(f"Date: {date_created[:10]}")  # YYYY-MM-DD
    if photographer:
        parts.append(f"Credit: {photographer}")
    clean_kw = [k for k in keywords if k and not k.lower().startswith("http")]
    if clean_kw:
        parts.append(f"Keywords: {', '.join(clean_kw)}")
    if description:
        cleaned = _clean_description(description)
        if cleaned:
            parts.append(f"Description: {cleaned}")
    return "\n".join(parts)


def _has_people(record: ImageRecord) -> bool:
    if record.faces_present:
        return True
    if record.people:
        stripped = record.people.strip().strip("|")
        if stripped and stripped.lower() not in ("none", ""):
            return True
    return False


@dataclass
class NasaDownloadResult:
    downloaded: int = 0
    skipped_existing: int = 0
    skipped_not_landscape: int = 0
    skipped_has_people: int = 0
    skipped_no_image: int = 0
    errors: int = 0


@dataclass
class NasaReclassifyResult:
    reclassified: int = 0
    skipped_no_metadata: int = 0
    flagged_has_people: int = 0
    errors: int = 0


def reclassify_nasa_images(
    *,
    output_dir: Path,
    config: Config,
    db_path: Path,
    dry_run: bool = False,
    request_delay: float = 0.5,
    progress_callback: Callable[[str], None] | None = None,
    show_output: bool = False,
) -> NasaReclassifyResult:
    """Re-classify NASA images already on disk, enriching them with API metadata.

    Each file's nasa_id is derived from its filename stem.  The NASA API is
    queried for the original title/description/keywords, which are then fed
    into the LLM classifier as context.  DB records and image sidecars are
    updated in place.  Nothing is deleted — people-containing images are
    flagged in the output but kept.
    """
    from .classifier import load_prompt

    result = NasaReclassifyResult()
    prompt = load_prompt(config.prompt_path)

    image_paths = sorted(output_dir.rglob("*.jpg"))
    total = len(image_paths)
    print(f"Found {total} image(s) to re-classify in {output_dir}", flush=True)

    for idx, img_path in enumerate(image_paths, 1):
        nasa_id = img_path.stem
        print(f"  [{idx}/{total}] {img_path.relative_to(output_dir)}", flush=True)

        if dry_run:
            print(f"    [dry-run] Would re-classify {nasa_id}", flush=True)
            result.reclassified += 1
            continue

        meta = fetch_nasa_metadata(nasa_id, request_delay)
        if meta is None:
            msg = f"    No metadata found for {nasa_id} — skipping"
            print(msg, flush=True)
            if progress_callback:
                progress_callback(msg)
            result.skipped_no_metadata += 1
            continue

        title = meta.get("title", "") or ""
        keywords = meta.get("keywords", []) or []
        if isinstance(keywords, str):
            keywords = [keywords]
        description = meta.get("description", "") or ""
        photographer = meta.get("photographer", "") or ""
        date_created = meta.get("date_created", "") or ""

        nasa_context = build_nasa_context(
            title=title,
            description=description,
            keywords=keywords,
            photographer=photographer,
            date_created=date_created,
        )

        kept = _reclassify_file(
            img_path=img_path,
            nasa_id=nasa_id,
            title=title,
            config=config,
            db_path=db_path,
            prompt=prompt,
            nasa_context=nasa_context,
            result=result,
            progress_callback=progress_callback,
            show_output=show_output,
        )
        if kept:
            result.reclassified += 1

    return result


def _classify_with_config(
    path: Path,
    prompt: str,
    config: Config,
    context: str | None = None,
) -> tuple[dict, str]:
    """Dispatch classification to the configured backend. Returns (raw, model_name)."""
    from .classifier import classify_image, classify_image_grok

    if config.classifier_backend == "grok":
        raw = classify_image_grok(path, prompt, config.grok, context=context)
        return raw, config.grok.model
    raw = classify_image(path, prompt, config.ollama, context=context)
    return raw, config.ollama.model


def _reclassify_file(
    *,
    img_path: Path,
    nasa_id: str,
    title: str,
    config: Config,
    db_path: Path,
    prompt: str,
    nasa_context: str,
    result: NasaReclassifyResult,
    progress_callback: Callable[[str], None] | None,
    show_output: bool = False,
) -> bool:
    import json as _json
    from datetime import datetime, timezone

    from image_sidecar import load_sidecar, write_sidecar
    from image_sidecar.driftwall import (
        upsert_driftwall_classification,
        upsert_driftwall_image_record,
    )

    from .classifier import ClassificationError, flatten_classification, hash_file
    from .db import init_db, upsert_image

    now = datetime.now(timezone.utc).isoformat()
    try:
        file_hash = hash_file(img_path)
        file_size = img_path.stat().st_size
        raw, model_name = _classify_with_config(img_path, prompt, config, context=nasa_context or None)
        if show_output:
            print(f"\n--- {img_path.name} ---")
            print(_json.dumps(raw, indent=2))
        record = flatten_classification(raw, img_path, file_hash, file_size, now, now)

        if _has_people(record):
            msg = f"    WARNING: people detected in {nasa_id} — kept on disk, flagged"
            print(msg, flush=True)
            if progress_callback:
                progress_callback(msg)
            result.flagged_has_people += 1
            # Still store the updated classification so the DB is accurate.

        init_db(db_path)
        upsert_image(db_path, record)
        document = upsert_driftwall_classification(
            load_sidecar(img_path),
            image_path=img_path,
            file_hash=file_hash,
            file_size=file_size,
            raw=raw,
            classified_at=now,
            prompt_text=prompt,
            model=model_name,
        )
        document = upsert_driftwall_image_record(document, image_path=img_path, record=record)
        write_sidecar(img_path, document)
        return True

    except ClassificationError as e:
        msg = f"    Classification failed for {nasa_id}: {e}"
        print(msg, flush=True)
        if progress_callback:
            progress_callback(msg)
        result.errors += 1
        return False
    except Exception as e:
        msg = f"    Error processing {nasa_id}: {e}"
        print(msg, flush=True)
        if progress_callback:
            progress_callback(msg)
        result.errors += 1
        return False


def download_nasa_images(
    *,
    output_dir: Path,
    query: str,
    limit: int = 50,
    dry_run: bool = False,
    request_delay: float = 0.5,
    classify: bool = True,
    config: Config | None = None,
    db_path: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
    show_output: bool = False,
) -> NasaDownloadResult:
    """Download up to *limit* landscape NASA images, filtering out any with people.

    When *classify* is True (default), each image is run through the configured
    classifier backend (grok or ollama) before saving.  Images where the LLM
    detects people are discarded.  Classification results are written to the
    Driftwall DB and image sidecar so they are immediately usable for rotation.
    """
    result = NasaDownloadResult()

    prompt: str | None = None
    if classify and config is not None:
        from .classifier import load_prompt
        prompt = load_prompt(config.prompt_path)

    page = 1
    print(f"Searching NASA Image Library: {query!r}", flush=True)

    while result.downloaded < limit:
        url = (
            f"{_NASA_BASE}/search"
            f"?q={urllib.request.quote(query)}"
            f"&media_type=image"
            f"&page={page}"
            f"&page_size=100"
        )
        time.sleep(request_delay)
        try:
            data = _get_json(url)
        except Exception as e:
            msg = f"Search request failed (page {page}): {e}"
            print(msg, flush=True)
            if progress_callback:
                progress_callback(msg)
            break

        collection = data.get("collection", {})
        items = collection.get("items", [])
        if not items:
            print("No more results.", flush=True)
            break

        print(f"  Page {page}: {len(items)} items", flush=True)

        for item in items:
            if result.downloaded >= limit:
                break

            item_data = item.get("data", [{}])[0]
            nasa_id = item_data.get("nasa_id", "")
            title = item_data.get("title", "Untitled")
            keywords = item_data.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]
            description = item_data.get("description", "") or ""
            photographer = item_data.get("photographer", "") or ""
            date_created = item_data.get("date_created", "") or ""

            if not nasa_id:
                result.skipped_no_image += 1
                continue

            mission = nasa_infer_mission(keywords, title)
            dest_dir = nasa_output_subdir(output_dir, mission)
            dest = dest_dir / f"{nasa_id}.jpg"

            if dest.exists():
                result.skipped_existing += 1
                continue

            if dry_run:
                msg = f"  [dry-run] Would download: {title!r}  →  {mission}/{nasa_id}.jpg"
                print(msg, flush=True)
                if progress_callback:
                    progress_callback(msg)
                result.downloaded += 1
                continue

            image_url = _get_asset_url(nasa_id, request_delay)
            if not image_url:
                result.skipped_no_image += 1
                continue

            try:
                time.sleep(request_delay)
                req = urllib.request.Request(image_url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    image_data = resp.read()
            except Exception as e:
                result.errors += 1
                msg = f"  Error downloading {nasa_id}: {e}"
                if progress_callback:
                    progress_callback(msg)
                continue

            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(image_data)

            try:
                from PIL import Image as _Image
                with _Image.open(tmp_path) as img:
                    w, h = img.size
                if w <= h:
                    tmp_path.unlink()
                    result.skipped_not_landscape += 1
                    if progress_callback:
                        progress_callback(f"  Skipped (portrait/square): {title!r}")
                    continue
            except Exception as e:
                tmp_path.unlink(missing_ok=True)
                result.errors += 1
                if progress_callback:
                    progress_callback(f"  Error reading image {nasa_id}: {e}")
                continue

            if classify and config is not None and db_path is not None and prompt is not None:
                nasa_context = build_nasa_context(
                    title=title,
                    description=description,
                    keywords=keywords,
                    photographer=photographer,
                    date_created=date_created,
                )
                kept = _classify_and_store(
                    tmp_path=tmp_path,
                    dest=dest,
                    title=title,
                    nasa_id=nasa_id,
                    config=config,
                    db_path=db_path,
                    prompt=prompt,
                    nasa_context=nasa_context,
                    result=result,
                    progress_callback=progress_callback,
                    show_output=show_output,
                )
                if not kept:
                    continue
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(tmp_path), str(dest))

            msg = f"  Downloaded: {title!r}  →  {mission}/{nasa_id}.jpg"
            print(msg, flush=True)
            if progress_callback:
                progress_callback(msg)
            result.downloaded += 1

        links = collection.get("links", [])
        if not any(link.get("rel") == "next" for link in links):
            print("Reached last page of results.", flush=True)
            break
        page += 1

    return result


def _classify_and_store(
    *,
    tmp_path: Path,
    dest: Path,
    title: str,
    nasa_id: str,
    config: Config,
    db_path: Path,
    prompt: str,
    nasa_context: str = "",
    result: NasaDownloadResult,
    progress_callback: Callable[[str], None] | None,
    show_output: bool = False,
) -> bool:
    """Classify *tmp_path*, check for people, move to *dest* and persist if clean.

    Returns True if the image was kept, False if discarded (updates *result* counters).
    """
    from datetime import datetime, timezone

    from image_sidecar import load_sidecar, write_sidecar
    from image_sidecar.driftwall import (
        upsert_driftwall_classification,
        upsert_driftwall_image_record,
    )

    from .classifier import ClassificationError, flatten_classification, hash_file
    from .db import init_db, upsert_image

    now = datetime.now(timezone.utc).isoformat()
    try:
        file_hash = hash_file(tmp_path)
        file_size = tmp_path.stat().st_size
        raw, model_name = _classify_with_config(tmp_path, prompt, config, context=nasa_context or None)
        if show_output:
            import json as _json
            print(f"\n--- {dest.name} ---")
            print(_json.dumps(raw, indent=2))
        # Record path points at dest (where the file will live), not the temp path.
        record = flatten_classification(raw, dest, file_hash, file_size, now, now)

        if _has_people(record):
            tmp_path.unlink(missing_ok=True)
            result.skipped_has_people += 1
            if progress_callback:
                progress_callback(f"  Skipped (has people): {title!r}")
            return False

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_path), str(dest))

        init_db(db_path)
        upsert_image(db_path, record)
        document = upsert_driftwall_classification(
            load_sidecar(dest),
            image_path=dest,
            file_hash=file_hash,
            file_size=file_size,
            raw=raw,
            classified_at=now,
            prompt_text=prompt,
            model=model_name,
        )
        document = upsert_driftwall_image_record(document, image_path=dest, record=record)
        write_sidecar(dest, document)
        return True

    except ClassificationError as e:
        tmp_path.unlink(missing_ok=True)
        result.errors += 1
        if progress_callback:
            progress_callback(f"  Classification failed for {nasa_id}: {e}")
        return False
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        result.errors += 1
        if progress_callback:
            progress_callback(f"  Error processing {nasa_id}: {e}")
        return False
