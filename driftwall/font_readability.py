"""Filter fonts down to ones that are actually readable as body text on a wallpaper.

Used by both static and dynamic overlays. The filter is intentionally conservative:
it rejects fonts that look bad at ~18px on a busy photographic background. False
negatives are preferable to having unreadable quotes on the user's screen.

Strategy (cheap and offline):

1. Pattern-match on the font's filename and parent directory segments. Catches
   the bulk of decorative families (Stencil, Display, Brush, Dingbat, etc.).
2. Reject extreme weights (Thin, ExtraLight, Hairline) — they vanish over
   detailed images.

OS/2 sFamilyClass parsing is intentionally NOT done here to avoid a fontTools
dependency. The name-based filter has been sufficient on the user's library;
upgrade to OS/2 metadata only if that stops being true.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Tokens that almost always indicate a font is unsuitable for body text.
# Matched case-insensitively against any path segment AND the file stem.
NAME_REJECT_PATTERNS: tuple[str, ...] = (
    # Decorative / display
    "stencil",
    "decorative",
    "display",
    "ornament",
    "ornamental",
    "novelty",
    "outline",
    "shadow",
    "shaded",
    "engraved",
    "inline",
    "3d",
    # Hand / brush / casual
    "brush",
    "marker",
    "graffiti",
    "scribble",
    "handwriting",
    "hand-drawn",
    "handdrawn",
    # Symbol / pictogram
    "dingbat",
    "dingbats",
    "symbol",
    "symbols",
    "icon",
    "icons",
    "emoji",
    "wingdings",
    "webdings",
    # Themed categories the user has on disk that don't read well at small sizes
    "medieval",
    "blackletter",
    "gothic-script",
    "fraktur",
    "calligraphic-display",
    "pixel",
    "retro-display",
    # User-organized "Fancy" / "Techno" folders are decorative by category
    "fancy",
    "techno",
    # Pure script faces (italic-only, calligraphic) are hard to read at body size
    "script",
)

# Weight tokens that produce strokes too thin for legibility on photo backgrounds.
WEIGHT_REJECT_PATTERNS: tuple[str, ...] = (
    "hairline",
    "thin",
    "extralight",
    "extra-light",
    "ultralight",
    "ultra-light",
)


@dataclass(frozen=True)
class ReadabilityVerdict:
    readable: bool
    reason: str


def _normalize(text: str) -> str:
    """Lowercase + strip separators so 'Big_Shoulders-Stencil' → 'bigshouldersstencil'."""
    return re.sub(r"[\s_\-]+", "", text).lower()


def _segments(path: Path) -> list[str]:
    """All path segments + the file stem, lowercased and dash-split."""
    parts = [p.lower() for p in path.parts if p not in ("/", "")]
    parts.append(path.stem.lower())
    return parts


def _matches_any(text: str, patterns: tuple[str, ...]) -> str | None:
    """Return the first matching pattern, or None."""
    norm = _normalize(text)
    for pat in patterns:
        if _normalize(pat) in norm:
            return pat
    return None


def classify_font(path: Path) -> ReadabilityVerdict:
    """Return a verdict for the font at `path` (path may not exist — pure on the name)."""
    for seg in _segments(path):
        hit = _matches_any(seg, NAME_REJECT_PATTERNS)
        if hit:
            return ReadabilityVerdict(False, f"rejected by name pattern: {hit!r} (in {seg!r})")
    for seg in _segments(path):
        hit = _matches_any(seg, WEIGHT_REJECT_PATTERNS)
        if hit:
            return ReadabilityVerdict(False, f"rejected by weight: {hit!r} (in {seg!r})")
    return ReadabilityVerdict(True, "passes name and weight filters")


def is_readable_body_font(path: Path) -> bool:
    return classify_font(path).readable
