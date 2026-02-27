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


_WRAPPER_LINE_RE = re.compile(
    r"^(?:"
    r"here(?:'s| is)?\b|"
    r"sure\b|certainly\b|of course\b|"
    r"note\b[:\-]?|explanation\b[:\-]?|"
    r"output\b[:\-]?|response\b[:\-]?|text\b[:\-]?|"
    r"haiku\b[:\-]?|poem\b[:\-]?|caption\b[:\-]?"
    r")",
    flags=re.IGNORECASE,
)


def _resolve_font(font_path: str) -> str | None:
    """Return the first usable font path, or None to fall back to Pillow default."""
    if font_path and Path(font_path).exists():
        return font_path
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _sanitize_overlay_text(text: str) -> str:
    """Remove common model wrappers and keep only renderable overlay text."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    # Prefer fenced block content when present.
    fence_blocks = re.findall(r"```(?:\w+)?\s*([\s\S]*?)\s*```", cleaned, flags=re.MULTILINE)
    if fence_blocks:
        cleaned = fence_blocks[0].strip()

    # Remove residual fence markers and markdown emphasis markers.
    cleaned = cleaned.replace("```", "").strip()
    cleaned = re.sub(r"^[*_`]+|[*_`]+$", "", cleaned).strip()

    # Unwrap a single surrounding quote pair.
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()

    lines = [line.strip() for line in cleaned.split("\n")]

    # Trim wrapper/preamble lines at edges only.
    while lines and (not lines[0] or _WRAPPER_LINE_RE.match(lines[0])):
        lines.pop(0)
    while lines and (not lines[-1] or _WRAPPER_LINE_RE.match(lines[-1])):
        lines.pop()

    # Remove simple "Label: value" on first line.
    if lines and re.match(r"^[A-Za-z ]{2,20}:\s+", lines[0]):
        lines[0] = re.sub(r"^[A-Za-z ]{2,20}:\s+", "", lines[0]).strip()

    return "\n".join(line for line in lines if line).strip()


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
        "Output only the text itself. Do not include markdown, quotes, labels, "
        "headers, notes, explanations, or any prefix/suffix text.\n\n"
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
    text = _sanitize_overlay_text(text)
    if text != raw_text.strip():
        logger.debug("Overlay response sanitized. raw_len=%d clean_len=%d", len(raw_text), len(text))
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

    # ── wrap target width ────────────────────────────────────────────────────
    pad = int(min(w, h) * 0.045)
    max_text_w = max(220, int(w * 0.42))

    # ── word-wrap ─────────────────────────────────────────────────────────────
    # Estimate character width from the font; getlength is more accurate than bbox.
    try:
        char_w = font.getlength("m")
    except AttributeError:
        char_w = font_size * 0.55
    chars_per_line = max(8, int(max_text_w / char_w))

    lines: list[str] = []
    for para in text.split("\n"):
        wrapped = textwrap.wrap(para, width=chars_per_line)
        lines.extend(wrapped if wrapped else [""])

    line_h = int(font_size * 1.45)
    total_text_h = len(lines) * line_h

    # Measure block width so the scrim hugs text instead of spanning the quadrant.
    line_widths: list[float] = []
    for line in lines:
        if not line:
            line_widths.append(char_w * 2)
            continue
        try:
            line_widths.append(font.getlength(line))
        except AttributeError:
            line_widths.append(len(line) * char_w)
    text_block_w = int(max(line_widths)) if line_widths else int(char_w * 2)
    text_block_h = total_text_h

    # Place block near selected corner.
    corner_margin = pad
    if quadrant == "top-left":
        text_x = corner_margin
        text_y = corner_margin
    elif quadrant == "top-right":
        text_x = w - corner_margin - text_block_w
        text_y = corner_margin
    elif quadrant == "bottom-left":
        text_x = corner_margin
        text_y = h - corner_margin - text_block_h
    else:  # bottom-right (default)
        text_x = w - corner_margin - text_block_w
        text_y = h - corner_margin - text_block_h

    text_x = max(corner_margin, text_x)
    text_y = max(corner_margin, text_y)

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
            text_x - bg_pad,
            text_y - bg_pad,
            text_x + text_block_w + bg_pad,
            text_y + text_block_h + bg_pad,
        )
        scrim_box = (
            max(0, scrim_box[0]),
            max(0, scrim_box[1]),
            min(w, scrim_box[2]),
            min(h, scrim_box[3]),
        )
        scrim = Image.new("RGBA", orig.size, (0, 0, 0, 0))
        ImageDraw.Draw(scrim).rounded_rectangle(scrim_box, radius=font_size // 3, fill=(0, 0, 0, 130))
        result = Image.alpha_composite(orig.convert("RGBA"), scrim).convert("RGB")

        draw = ImageDraw.Draw(result)
        shadow_off = max(2, font_size // 14)
        draw_y = text_y
        for line in lines:
            draw.text((text_x + shadow_off, draw_y + shadow_off), line, font=font, fill=(0, 0, 0))
            draw.text((text_x, draw_y), line, font=font, fill=(255, 255, 255))
            draw_y += line_h

        result.save(output_path, format="JPEG", quality=95)

    return output_path
