"""Runtime text overlay for wallpaper images."""

from __future__ import annotations

import logging
import re
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)

# Ordered by preference: script/calligraphic fonts first, then italic serifs.
_FONT_CANDIDATES = [
    # URW Chancery (calligraphic script) — via fonts-urw-base35
    "/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf",
    # Google Fonts (if user installed them)
    "/usr/share/fonts/truetype/dancing-script/DancingScript-Regular.ttf",
    "/usr/share/fonts/truetype/caveat/Caveat-Regular.ttf",
    "/usr/share/fonts/truetype/kalam/Kalam-Regular.ttf",
    # Italic serifs as fallback
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
]


def _resolve_font(font_path: str) -> str | None:
    """Return the first usable font path, or None to fall back to Pillow default."""
    if font_path and Path(font_path).exists():
        return font_path
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def generate_overlay_text(
    description: str,
    prompt: str,
    model: str,
    host: str,
    timeout: int,
    num_predict: int,
) -> str | None:
    """
    Ask Ollama to generate overlay text (e.g. a haiku) based on the image description.
    Returns the text string, or None if generation fails or description is empty.
    Thinking is explicitly disabled.
    """
    if not description or not description.strip():
        return None

    try:
        import ollama  # type: ignore[import]
    except ImportError:
        logger.warning("ollama package not available; skipping overlay text generation")
        return None

    full_prompt = (
        f"Based on this image description, write {prompt}. "
        "Output only the text itself — no preamble, no title, no explanation, "
        "and no punctuation beyond what naturally belongs in the text.\n\n"
        f"Image description: {description}"
    )

    client = ollama.Client(host=host)
    try:
        response = client.generate(
            model=model,
            prompt=full_prompt,
            think=False,
            options={"num_predict": num_predict},
        )
    except Exception as e:
        logger.warning("Overlay text generation failed: %s", e)
        return None

    text = (response.response if not isinstance(response, dict) else response.get("response", "")) or ""
    raw_text = text
    # Strip <think>...</think> blocks produced by reasoning models.
    # Also handle unclosed <think> tags in case of truncation.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()
    if not text:
        raw_preview = raw_text[:240].replace("\n", "\\n")
        logger.warning(
            "Overlay response empty after filtering. model=%s num_predict=%d raw_len=%d has_think_tag=%s raw_preview=%r",
            model,
            num_predict,
            len(raw_text),
            "<think>" in raw_text,
            raw_preview,
        )
    return text if text else None


def apply_overlay(
    image_path: Path,
    text: str,
    quadrant: str,
    font_path: str,
    output_path: Path,
) -> Path:
    """
    Render *text* over a copy of *image_path* in the chosen quadrant.
    The original file is never touched. The result is written to *output_path*.
    Returns *output_path*.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(image_path) as orig:
        try:
            orig = ImageOps.exif_transpose(orig)
        except Exception:
            pass
        if orig.mode != "RGB":
            orig = orig.convert("RGB")
        w, h = orig.size

    # ── font ─────────────────────────────────────────────────────────────────
    font_size = max(28, int(min(w, h) * 0.042))
    resolved = _resolve_font(font_path)
    if resolved:
        try:
            font = ImageFont.truetype(resolved, font_size)
            logger.debug("Overlay font: %s @ %dpx", resolved, font_size)
        except Exception:
            logger.warning("Could not load font %s; using Pillow default", resolved)
            font = ImageFont.load_default(size=font_size)
    else:
        font = ImageFont.load_default(size=font_size)

    # ── quadrant box ─────────────────────────────────────────────────────────
    pad = int(min(w, h) * 0.045)
    hw, hh = w // 2, h // 2
    boxes = {
        "top-left":     (pad,      pad,      hw - pad, hh - pad),
        "top-right":    (hw + pad, pad,      w  - pad, hh - pad),
        "bottom-left":  (pad,      hh + pad, hw - pad, h  - pad),
        "bottom-right": (hw + pad, hh + pad, w  - pad, h  - pad),
    }
    x0, y0, x1, y1 = boxes.get(quadrant, boxes["bottom-right"])
    box_w = x1 - x0
    box_h = y1 - y0

    # ── word-wrap ─────────────────────────────────────────────────────────────
    # Estimate character width from the font; getlength is more accurate than bbox.
    try:
        char_w = font.getlength("m")
    except AttributeError:
        char_w = font_size * 0.55
    chars_per_line = max(8, int(box_w / char_w))

    lines: list[str] = []
    for para in text.split("\n"):
        wrapped = textwrap.wrap(para, width=chars_per_line)
        lines.extend(wrapped if wrapped else [""])

    line_h = int(font_size * 1.45)
    total_text_h = len(lines) * line_h

    # Vertically centre the block in the quadrant.
    text_y = y0 + max(0, (box_h - total_text_h) // 2)

    # ── compositing ──────────────────────────────────────────────────────────
    # Re-open to avoid mutating the cached object inside the context manager.
    with Image.open(image_path) as orig:
        try:
            orig = ImageOps.exif_transpose(orig)
        except Exception:
            pass
        if orig.mode != "RGB":
            orig = orig.convert("RGB")

        # Semi-transparent dark scrim behind the text block for readability.
        bg_pad = int(font_size * 0.5)
        scrim_box = (
            x0 - bg_pad,
            text_y - bg_pad,
            x1,
            text_y + total_text_h + bg_pad,
        )
        scrim = Image.new("RGBA", orig.size, (0, 0, 0, 0))
        ImageDraw.Draw(scrim).rounded_rectangle(scrim_box, radius=font_size // 3, fill=(0, 0, 0, 130))
        result = Image.alpha_composite(orig.convert("RGBA"), scrim).convert("RGB")

        draw = ImageDraw.Draw(result)
        shadow_off = max(2, font_size // 14)
        for line in lines:
            draw.text((x0 + shadow_off, text_y + shadow_off), line, font=font, fill=(0, 0, 0))
            draw.text((x0, text_y), line, font=font, fill=(255, 255, 255))
            text_y += line_h

        result.save(output_path, format="JPEG", quality=95)

    return output_path
