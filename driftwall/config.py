"""Configuration loading and dataclasses for Driftwall."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "driftwall" / "config.toml"
DEFAULT_PROMPT_PATH = Path(__file__).parent.parent / "photo_class_prompt.txt"


@dataclass
class OllamaConfig:
    model: str = "qwen3-vl:30b"
    timeout: int = 120
    concurrency: int = 1
    host: str = "http://localhost:11434"
    max_image_pixels: int = 1344  # longest edge before sending to model; 0 = no resize
    num_predict: int = 48000  # max tokens to predict (Ollama num_predict)


@dataclass
class RotationConfig:
    interval_minutes: int = 30
    avoid_repeat_window: int = 50


@dataclass
class FilterConfig:
    exclude_genre: list[str] = field(default_factory=list)
    exclude_faces: bool = False
    min_megapixels: float = 0.0
    require_setting: list[str] = field(default_factory=list)
    require_orientation: list[str] = field(default_factory=list)


@dataclass
class TimeOfDayMapping:
    hours: list[int]  # list of hours (0-23) this applies to
    values: list[str]  # time_of_day values to prefer


@dataclass
class TriggerConfig:
    enabled: bool = True
    time_of_day_map: list[TimeOfDayMapping] = field(default_factory=list)
    season_map: dict[str, list[str]] = field(default_factory=dict)  # month_range -> seasons


@dataclass
class OverlayConfig:
    enabled: bool = False
    prompts: list[str] = field(default_factory=lambda: ["a haiku"])
    model: str = "lfm2.5-thinking"
    font_file: str = ""   # path to a specific font file; empty = auto-detect from system candidates
    font_dir: str = ""    # directory to scan recursively for .ttf fonts; LLM picks one
    quadrants: list[str] = field(default_factory=lambda: ["bottom-right"])  # top-left, top-right, bottom-left, bottom-right


@dataclass
class DownloadConfig:
    output_dir: Path = field(default_factory=lambda: Path.home() / "Pictures" / "driftwall-downloads")


@dataclass
class ContentConfig:
    enabled: bool = False
    content_dir: Path = field(default_factory=lambda: Path.home() / "Documents" / "driftwall-content")
    chroma_path: Path | None = None  # default: ~/.local/share/driftwall/chromadb
    embed_model: str = "nomic-embed-text"


@dataclass
class DynamicOverlayConfig:
    enabled: bool = False
    max_simultaneous: int = 3
    min_lifetime_seconds: int = 30
    max_lifetime_seconds: int = 90
    spawn_interval_seconds: int = 20
    font_size: int = 18          # px
    max_screen_fraction: float = 0.10
    font_file: str = ""          # empty = auto-detect


@dataclass
class Config:
    image_dirs: list[Path] = field(default_factory=lambda: [Path.home() / "Pictures"])
    db_path: Path | None = None
    prompt_path: Path = field(default_factory=lambda: DEFAULT_PROMPT_PATH)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    rotation: RotationConfig = field(default_factory=RotationConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    content: ContentConfig = field(default_factory=ContentConfig)
    dynamic_overlay: DynamicOverlayConfig = field(default_factory=DynamicOverlayConfig)

    @property
    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path
        # Central location — SQLite file locking doesn't work on
        # network/FUSE filesystems (Samba, NFS, etc.).
        return Path.home() / ".local" / "share" / "driftwall" / "driftwall.db"

    @property
    def resolved_chroma_path(self) -> Path:
        if self.content.chroma_path is not None:
            return self.content.chroma_path
        return Path.home() / ".local" / "share" / "driftwall" / "chromadb"


def _parse_time_of_day_map(raw: list[dict[str, Any]]) -> list[TimeOfDayMapping]:
    result = []
    for entry in raw:
        hours = entry.get("hours", [])
        values = entry.get("values", [])
        if isinstance(values, str):
            values = [values]
        result.append(TimeOfDayMapping(hours=hours, values=values))
    return result


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML file, merging with defaults."""
    config_path = path or DEFAULT_CONFIG_PATH

    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)

    # Accept image_dirs (list) or legacy image_dir (single path).
    if "image_dirs" in raw:
        image_dirs = [Path(d) for d in raw["image_dirs"]]
    elif "image_dir" in raw:
        image_dirs = [Path(raw["image_dir"])]
    else:
        image_dirs = [Path.home() / "Pictures"]
    db_path_raw = raw.get("db_path")
    db_path = Path(db_path_raw) if db_path_raw else None
    prompt_path = Path(raw.get("prompt_path", str(DEFAULT_PROMPT_PATH)))

    ollama_raw = raw.get("ollama", {})
    ollama = OllamaConfig(
        model=ollama_raw.get("model", "qwen3-vl:30b"),
        timeout=ollama_raw.get("timeout", 120),
        concurrency=ollama_raw.get("concurrency", 1),
        host=ollama_raw.get("host", "http://localhost:11434"),
        max_image_pixels=ollama_raw.get("max_image_pixels", 1344),
        num_predict=ollama_raw.get("num_predict", 48000),
    )

    rotation_raw = raw.get("rotation", {})
    rotation = RotationConfig(
        interval_minutes=rotation_raw.get("interval_minutes", 30),
        avoid_repeat_window=rotation_raw.get("avoid_repeat_window", 50),
    )

    filters_raw = raw.get("filters", {})
    filters = FilterConfig(
        exclude_genre=filters_raw.get("exclude_genre", []),
        exclude_faces=filters_raw.get("exclude_faces", False),
        min_megapixels=float(filters_raw.get("min_megapixels", 0.0)),
        require_setting=filters_raw.get("require_setting", []),
        require_orientation=filters_raw.get("require_orientation", []),
    )

    triggers_raw = raw.get("triggers", {})
    tod_map_raw = triggers_raw.get("time_of_day_map", [])
    triggers = TriggerConfig(
        enabled=triggers_raw.get("enabled", True),
        time_of_day_map=_parse_time_of_day_map(tod_map_raw),
        season_map=triggers_raw.get("season_map", {}),
    )

    overlay_raw = raw.get("overlay", {})

    def _as_list(val: Any, default: list[str]) -> list[str]:
        if val is None:
            return default
        if isinstance(val, list):
            return [str(v) for v in val if v]
        return [str(val)] if val else default

    overlay_prompts = _as_list(overlay_raw.get("prompt"), ["a haiku"])
    overlay_quadrants = _as_list(overlay_raw.get("quadrant"), ["bottom-right"])

    overlay = OverlayConfig(
        enabled=overlay_raw.get("enabled", False),
        prompts=overlay_prompts,
        model=overlay_raw.get("model", "lfm2.5-thinking"),
        font_file=overlay_raw.get("font_file", ""),
        font_dir=overlay_raw.get("font_dir", ""),
        quadrants=overlay_quadrants,
    )

    download_raw = raw.get("download", {})
    download = DownloadConfig(
        output_dir=Path(download_raw.get("output_dir", str(Path.home() / "Pictures" / "driftwall-downloads"))).expanduser(),
    )

    content_raw = raw.get("content", {})
    chroma_path_raw = content_raw.get("chroma_path")
    content = ContentConfig(
        enabled=content_raw.get("enabled", False),
        content_dir=Path(content_raw.get("content_dir", str(Path.home() / "Documents" / "driftwall-content"))).expanduser(),
        chroma_path=Path(chroma_path_raw).expanduser() if chroma_path_raw else None,
        embed_model=content_raw.get("embed_model", "nomic-embed-text"),
    )

    dyn_raw = raw.get("dynamic_overlay", {})
    dynamic_overlay = DynamicOverlayConfig(
        enabled=dyn_raw.get("enabled", False),
        max_simultaneous=dyn_raw.get("max_simultaneous", 3),
        min_lifetime_seconds=dyn_raw.get("min_lifetime_seconds", 30),
        max_lifetime_seconds=dyn_raw.get("max_lifetime_seconds", 90),
        spawn_interval_seconds=dyn_raw.get("spawn_interval_seconds", 20),
        font_size=dyn_raw.get("font_size", 18),
        max_screen_fraction=float(dyn_raw.get("max_screen_fraction", 0.10)),
        font_file=dyn_raw.get("font_file", ""),
    )

    return Config(
        image_dirs=image_dirs,
        db_path=db_path,
        prompt_path=prompt_path,
        ollama=ollama,
        rotation=rotation,
        filters=filters,
        triggers=triggers,
        overlay=overlay,
        download=download,
        content=content,
        dynamic_overlay=dynamic_overlay,
    )
