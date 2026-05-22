"""Unified font option discovery and LLM-based font selection."""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

from .font_readability import classify_font

log = logging.getLogger(__name__)

_FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}


@dataclass(frozen=True)
class FontOption:
    path: Path
    rationale: str


def _name_from_path(path: Path) -> str:
    stem = path.stem
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem)
    stem = re.sub(
        r"\b(?:Regular|Italic|Oblique|Bold|SemiBold|DemiBold|Medium|Light|ExtraBold|Black|Thin)\b",
        "",
        stem,
        flags=re.IGNORECASE,
    )
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or path.stem


def scan_font_dir(font_dir: str) -> list[Path]:
    """Recursively find font files under font_dir."""
    if not font_dir:
        return []
    d = Path(font_dir).expanduser()
    if not d.is_dir():
        log.warning("fonts.directory does not exist or is not a directory: %s", font_dir)
        return []
    fonts = sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in _FONT_EXTS)
    log.debug("Found %d font files in %s", len(fonts), d)
    return fonts


def build_font_options(config) -> list[FontOption]:
    """Build font options from unified config (folder mode or list mode).

    When ``config.fonts.filter_unreadable`` is true (default), fonts whose
    filename or path segments look decorative (Stencil, Display, Brush,
    ExtraLight, Thin, …) are dropped — see ``font_readability.classify_font``.
    """
    filter_unreadable = bool(getattr(config.fonts, "filter_unreadable", True))

    def _filter(options: list[FontOption]) -> list[FontOption]:
        if not filter_unreadable:
            return options
        kept: list[FontOption] = []
        rejected = 0
        for opt in options:
            verdict = classify_font(opt.path)
            if verdict.readable:
                kept.append(opt)
            else:
                rejected += 1
                log.debug("Filtered font %s: %s", opt.path, verdict.reason)
        if rejected:
            log.info("Font filter dropped %d/%d unreadable fonts", rejected, len(options))
        return kept

    source = getattr(config.fonts, "source", "folder")
    if source == "list":
        options: list[FontOption] = []
        for entry in getattr(config.fonts, "entries", []):
            path_raw = str(entry.get("path", "")).strip()
            if not path_raw:
                continue
            path = Path(path_raw).expanduser()
            if not path.is_file():
                log.warning("Skipping missing font file in fonts.entries: %s", path)
                continue
            desc = str(entry.get("description", "")).strip()
            options.append(FontOption(path=path, rationale=desc or _name_from_path(path)))
        return _filter(options)

    # default: folder
    folder_options = [
        FontOption(path=p, rationale=_name_from_path(p))
        for p in scan_font_dir(config.fonts.directory)
    ]
    return _filter(folder_options)


def pick_font_for_context(
    options: list[FontOption],
    context: str,
    purpose: str,
    model: str,
    host: str,
) -> Path:
    """Ask local LLM to pick best font option for the given context."""
    if len(options) == 1:
        return options[0].path
    if not options:
        raise ValueError("pick_font_for_context called with no options")

    try:
        import ollama  # type: ignore[import]
    except ImportError:
        log.warning("ollama not available; choosing font randomly")
        return random.choice(options).path

    lines = [f"{i + 1}. {opt.path.stem} — {opt.rationale}" for i, opt in enumerate(options)]
    prompt = (
        f"Choose the best font option for this {purpose}.\n\n"
        f"Content:\n{context}\n\n"
        f"Font options:\n" + "\n".join(lines) + "\n\n"
        "Respond with ONLY the option number."
    )

    try:
        client = ollama.Client(host=host)
        resp = client.generate(
            model=model,
            prompt=prompt,
            think=False,
            options={"num_predict": 24},
        )
        text = (resp.response if not isinstance(resp, dict) else resp.get("response", "")) or ""
        m = re.search(r"\d+", text)
        if m:
            idx = int(m.group(0)) - 1
            if 0 <= idx < len(options):
                return options[idx].path
        log.warning("Font selection returned invalid response %r; choosing randomly", text.strip())
    except Exception as e:
        log.warning("Font selection LLM call failed: %s", e)

    return random.choice(options).path
