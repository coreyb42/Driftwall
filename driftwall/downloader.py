"""External art source downloader — Met Museum Open Access API."""

from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_MET_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"


def met_output_subdir(
    base_dir: Path,
    *,
    department_id: int | None = None,
    search_query: str | None = None,
) -> Path:
    """Return the target directory for Met downloads, with implicit subfolders.

    Structure: ``base_dir/met[/dept-{id}][/{sanitized_query}]``
    """
    path = base_dir / "met"
    if department_id is not None:
        path = path / f"dept-{department_id}"
    if search_query:
        safe = re.sub(r"[^\w\-]", "-", search_query).strip("-")[:40]
        path = path / safe
    return path


@dataclass
class DownloadResult:
    downloaded: int = 0
    skipped_not_landscape: int = 0
    skipped_existing: int = 0
    skipped_no_image: int = 0
    errors: int = 0


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",  # prevent gzip so resp.read() returns plain text
}


def _get_json(url: str) -> dict:
    """Fetch JSON from *url*, retrying on 403 (Imperva rate-limit) with backoff."""
    last_exc: Exception | None = None
    for wait in (0, 10, 30):  # immediate, then 10 s, then 30 s
        if wait:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                last_exc = e
                continue
            raise
    assert last_exc is not None
    raise last_exc


def met_list_departments() -> list[dict]:
    """Return [{departmentId, displayName}, …] from the Met API."""
    data = _get_json(f"{_MET_BASE}/departments")
    return data.get("departments", [])


def met_get_object_ids(
    *,
    department_id: int | None = None,
    search_query: str | None = None,
    request_delay: float = 0.2,
) -> list[int]:
    """Return a list of object IDs matching the given filters."""
    if search_query:
        url = f"{_MET_BASE}/search?hasImages=true&q={urllib.request.quote(search_query)}"
        if department_id is not None:
            url += f"&departmentId={department_id}"
        data = _get_json(url)
        ids = data.get("objectIDs") or []
    else:
        url = f"{_MET_BASE}/objects"
        if department_id is not None:
            url += f"?departmentIds={department_id}"
        time.sleep(request_delay)
        data = _get_json(url)
        ids = data.get("objectIDs") or []
    return ids


def download_met_artworks(
    *,
    output_dir: Path,
    department_id: int | None = None,
    search_query: str | None = None,
    limit: int = 50,
    dry_run: bool = False,
    request_delay: float = 1.0,
    progress_callback: Callable[[str], None] | None = None,
) -> DownloadResult:
    """Download up to *limit* landscape-oriented artworks from the Met Museum."""
    result = DownloadResult()

    # Count existing images before any network calls so we know how many more to fetch.
    existing_count = sum(1 for _ in output_dir.glob("met_*.jpg")) if output_dir.exists() else 0
    target_new = limit - existing_count
    if target_new <= 0:
        print(f"Already have {existing_count} images (≥ limit {limit}). Nothing to do.", flush=True)
        return result
    if existing_count > 0:
        print(f"Found {existing_count} existing images; targeting {target_new} more.", flush=True)

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching object IDs from Met Museum…", flush=True)
    ids = met_get_object_ids(
        department_id=department_id,
        search_query=search_query,
        request_delay=request_delay,
    )
    if not ids:
        print("No objects found.", flush=True)
        return result

    random.shuffle(ids)
    print(f"Found {len(ids):,} objects, targeting up to {target_new} landscape images.", flush=True)

    for idx, obj_id in enumerate(ids, 1):
        if result.downloaded >= target_new:
            break

        if idx % 100 == 0:
            print(
                f"  Checked {idx:,}/{len(ids):,}… ({result.downloaded}/{target_new} downloaded)",
                flush=True,
            )

        dest = output_dir / f"met_{obj_id}.jpg"
        if dest.exists():
            result.skipped_existing += 1
            continue

        time.sleep(request_delay)
        try:
            obj = _get_json(f"{_MET_BASE}/objects/{obj_id}")
        except Exception as e:
            result.errors += 1
            if progress_callback:
                progress_callback(f"  Error fetching object {obj_id} [{type(e).__name__}]: {e}")
            continue

        if not obj.get("isPublicDomain") or not obj.get("primaryImage"):
            result.skipped_no_image += 1
            continue

        title = obj.get("title", "Untitled")
        artist = obj.get("artistDisplayName", "Unknown")
        image_url = obj["primaryImage"]

        if dry_run:
            msg = f"  [dry-run] Would download: {title} by {artist}"
            print(msg, flush=True)
            if progress_callback:
                progress_callback(msg)
            result.downloaded += 1
            continue

        try:
            time.sleep(request_delay)
            req = urllib.request.Request(image_url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
        except Exception as e:
            result.errors += 1
            if progress_callback:
                progress_callback(
                    f"  Error downloading '{title}' by {artist} [{type(e).__name__}]: {e}"
                )
            continue

        dest.write_bytes(data)

        # Landscape check via PIL
        try:
            from PIL import Image as _Image
            with _Image.open(dest) as img:
                w, h = img.size
            if w <= h:
                dest.unlink()
                result.skipped_not_landscape += 1
                if progress_callback:
                    progress_callback(f"  Skipped (portrait): {title} by {artist}")
                continue
        except Exception as e:
            # If PIL can't open it, discard
            dest.unlink()
            result.errors += 1
            if progress_callback:
                progress_callback(
                    f"  Error reading image '{title}' by {artist} [{type(e).__name__}]: {e}"
                )
            continue

        msg = f"  Downloaded: {title} by {artist}"
        print(msg, flush=True)
        if progress_callback:
            progress_callback(msg)
        result.downloaded += 1

    return result
