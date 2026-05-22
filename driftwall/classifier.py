"""Image classification (Grok or Ollama) and JSON flattening."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from .config import GrokConfig, OllamaConfig
from .db import ImageRecord

logger = logging.getLogger(__name__)


class ClassificationError(Exception):
    pass


class ClassificationParseError(ClassificationError):
    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


def hash_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_prompt(path: Path) -> str:
    """Load the classification prompt text."""
    return path.read_text(encoding="utf-8")


def prepare_image(path: Path, max_pixels: int) -> bytes:
    """
    Load an image, downscale so the longest edge <= max_pixels, return JPEG bytes.
    The original file is never modified.
    """
    try:
        from PIL import Image  # type: ignore[import]
    except ImportError as e:
        raise ClassificationError("Pillow not installed (pip install Pillow)") from e

    import io

    with Image.open(path) as img:
        # Preserve EXIF orientation
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        w, h = img.size
        if max_pixels > 0 and max(w, h) > max_pixels:
            scale = max_pixels / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)
            logger.debug("Resized %s from %dx%d to %dx%d", path.name, w, h, *new_size)

        # Convert to RGB (handles RGBA, palette, etc.)
        if img.mode != "RGB":
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()


def classify_image(
    path: Path,
    prompt: str,
    ollama_config: OllamaConfig,
    image_bytes: bytes | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """
    Send the image to Ollama and return the parsed JSON classification.
    Raises ClassificationError on any failure.

    If *context* is provided it is appended to the message so the model can
    use verified external metadata (e.g. titles/descriptions from an image
    archive) to improve field accuracy.
    """
    try:
        import ollama  # type: ignore[import]
    except ImportError as e:
        raise ClassificationError("ollama package not installed") from e

    client = ollama.Client(host=ollama_config.host)
    if image_bytes is None:
        image_bytes = prepare_image(path, ollama_config.max_image_pixels)

    logger.info("Classifying %s  →  %s @ %s", path.name, ollama_config.model, ollama_config.host)

    message_content = prompt
    if context:
        message_content = (
            f"{prompt}\n\n"
            f"Additional verified metadata about this image "
            f"(use it to improve accuracy of your classification):\n{context}"
        )

    try:
        response = client.chat(
            model=ollama_config.model,
            messages=[
                {
                    "role": "user",
                    "content": message_content,
                    "images": [image_bytes],
                }
            ],
            think=True,
            options={"num_predict": ollama_config.num_predict},
        )
    except Exception as e:
        raise ClassificationError(f"Ollama request failed for {path}: {e}") from e

    if isinstance(response, dict):
        msg = response.get("message", {})
        content = msg.get("content", "") or ""
        thinking = msg.get("thinking", "") or ""
    else:
        content = response.message.content or ""
        thinking = getattr(response.message, "thinking", "") or ""

    # qwen3 thinking models route final output through message.thinking when
    # the content field ends up empty; fall back to the thinking block.
    if not content.strip() and thinking.strip():
        logger.debug("Content empty — falling back to thinking block for %s", path.name)
        content = thinking

    logger.debug("Raw LLM response for %s:\n%s", path.name, content)

    if not content.strip():
        raise ClassificationError(f"Empty response from model for {path.name}.")

    try:
        return extract_json_from_response(content, path.name)
    except ClassificationError as e:
        if content.strip():
            raise ClassificationParseError(str(e), raw_text=content) from e
        raise


def classify_image_grok(
    path: Path,
    prompt: str,
    grok_config: GrokConfig,
    image_bytes: bytes | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """
    Send the image to xAI Grok and return the parsed JSON classification.
    API key is read from grok_config.api_key, falling back to XAI_API_KEY env var.
    Raises ClassificationError on any failure.
    """
    import base64
    import os

    try:
        from openai import OpenAI  # type: ignore[import]
    except ImportError as e:
        raise ClassificationError("openai package not installed (pip install openai)") from e

    api_key = grok_config.api_key or os.environ.get("XAI_API_KEY", "")
    if not api_key:
        raise ClassificationError(
            "No Grok API key configured. Set grok.api_key in config.toml or XAI_API_KEY env var."
        )

    if image_bytes is None:
        image_bytes = prepare_image(path, grok_config.max_image_pixels)

    message_text = prompt
    if context:
        message_text = (
            f"{prompt}\n\n"
            f"Additional verified metadata about this image "
            f"(use it to improve accuracy of your classification):\n{context}"
        )

    import urllib.parse
    host = urllib.parse.urlparse(grok_config.base_url).netloc or grok_config.base_url
    logger.info("Classifying %s  →  %s @ %s", path.name, grok_config.model, host)

    b64_image = base64.b64encode(image_bytes).decode("ascii")
    client = OpenAI(api_key=api_key, base_url=grok_config.base_url, timeout=grok_config.timeout)

    try:
        response = client.chat.completions.create(
            model=grok_config.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                        },
                        {"type": "text", "text": message_text},
                    ],
                }
            ],
        )
    except Exception as e:
        raise ClassificationError(f"Grok API request failed for {path}: {e}") from e

    content = response.choices[0].message.content or ""
    logger.debug("Raw Grok response for %s:\n%s", path.name, content)

    if not content.strip():
        raise ClassificationError(f"Empty response from Grok for {path.name}.")

    try:
        return extract_json_from_response(content, path.name)
    except ClassificationError as e:
        if content.strip():
            raise ClassificationParseError(str(e), raw_text=content) from e
        raise


def extract_json_from_response(text: str, label: str = "") -> dict[str, Any]:
    """
    Extract JSON from a model response. Tries in order:
      1. Strict parse of markdown-fenced block
      2. Strict parse of raw {...} extraction
      3. json-repair on the fenced block
      4. json-repair on the full text
    Raises ClassificationError if all attempts fail.
    """
    # Strip <think>...</think> blocks produced by reasoning models (e.g. qwen3).
    # Also handle unclosed <think> tags in case of truncation.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()

    # Candidates to try: fenced block first, then full text
    candidates: list[str] = []

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1))

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        candidates.append(brace_match.group(0))

    # 1 & 2: strict parse
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 3 & 4: json-repair fallback
    try:
        from json_repair import repair_json  # type: ignore[import]

        for candidate in candidates:
            try:
                repaired = repair_json(candidate, return_objects=True)
                if isinstance(repaired, dict):
                    logger.debug("json-repair recovered JSON for %s", label)
                    return repaired
            except Exception:
                pass

        # Last resort: repair the entire response text
        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, dict):
            logger.debug("json-repair recovered JSON from full response for %s", label)
            return repaired

    except ImportError:
        pass

    raise ClassificationError(
        f"No valid JSON found in response for {label!r}. "
        f"Full response ({len(text)} chars):\n{text}"
    )


def _pipe(values: Any) -> str | None:
    """Convert a list to a pipe-delimited string, or return None."""
    if values is None:
        return None
    if isinstance(values, list):
        cleaned = [str(v).strip() for v in values if v is not None and str(v).strip()]
        return "|".join(cleaned) if cleaned else None
    return str(values) if values else None


def _str(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(bool(value)) if isinstance(value, bool) else int(value)
    except (TypeError, ValueError):
        return 0


def flatten_classification(
    raw: dict[str, Any],
    path: Path,
    file_hash: str,
    file_size: int,
    classified_at: str,
    last_seen_at: str,
) -> ImageRecord:
    """Map nested classification JSON to a flat ImageRecord."""
    derived = raw.get("derived", {})
    geom = derived.get("geometry", {})
    time_ = derived.get("time", {})
    content = raw.get("content", {})
    desc = content.get("descriptions", {})
    subjects = content.get("subjects", {})
    scene = content.get("scene", {})
    entities = content.get("entities", {})
    aesthetics = content.get("aesthetics", {})
    composition = aesthetics.get("composition", {})
    color = aesthetics.get("color", {})
    quality = content.get("quality", {})
    privacy = content.get("privacy", {})

    return ImageRecord(
        path=str(path),
        file_hash=file_hash,
        file_size=file_size,
        classified_at=classified_at,
        last_seen_at=last_seen_at,
        # geometry
        orientation=_str(geom.get("orientation"), "unknown"),
        aspect_ratio=_float(geom.get("aspect_ratio")),
        aspect_class=_str(geom.get("aspect_class")),
        megapixels=_float(geom.get("megapixels")),
        crop_detected=_int(geom.get("crop_detected", False)),
        # time
        season=_str(time_.get("season"), "unknown"),
        time_of_day=_str(time_.get("time_of_day"), "unknown"),
        # descriptions
        one_sentence=_str(desc.get("one_sentence")),
        one_paragraph=_str(desc.get("one_paragraph")),
        alt_text=_str(desc.get("alt_text")),
        keywords=_pipe(desc.get("keywords")),
        # subjects
        primary_subject=_str(subjects.get("primary_subject")),
        secondary_subjects=_pipe(subjects.get("secondary_subjects")),
        genre=_str(subjects.get("genre"), "unknown"),
        subject_distance=_str(subjects.get("subject_distance")),
        # scene
        setting=_str(scene.get("setting"), "unknown"),
        environment=_str(scene.get("environment")),
        weather=_str(scene.get("weather")),
        lighting=_str(scene.get("lighting")),
        event_context=_str(scene.get("event_context")),
        # entities
        people=_pipe(entities.get("people")),
        animals=_pipe(entities.get("animals")),
        objects=_pipe(entities.get("objects")),
        buildings=_pipe(entities.get("buildings")),
        visible_text=_pipe(
            entities.get("text", {}).get("visible_text")
            if isinstance(entities.get("text"), dict)
            else entities.get("visible_text")
        ),
        # aesthetics
        dominant_lines=_pipe(composition.get("dominant_lines")),
        framing=_str(composition.get("framing")),
        depth=_str(composition.get("depth")),
        color_palette=_str(color.get("palette")),
        saturation=_str(color.get("saturation")),
        dominant_colors=_pipe(color.get("dominant_colors")),
        mood=_pipe(aesthetics.get("mood")),
        style=_str(aesthetics.get("style")),
        # quality
        sharpness=_str(quality.get("sharpness")),
        noise=_str(quality.get("noise")),
        exposure=_str(quality.get("exposure")),
        motion_blur=_str(quality.get("motion_blur")),
        focus_issues=_pipe(quality.get("focus_issues")),
        artifacts=_pipe(quality.get("artifacts")),
        # privacy
        faces_present=_int(privacy.get("faces_present", False)),
        sensitive=_pipe(privacy.get("sensitive")),
        release_needed=_int(privacy.get("release_needed", False)),
    )
