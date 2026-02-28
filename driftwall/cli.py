"""Driftwall CLI — argparse entry point with all subcommands."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .config import load_config
from .db import get_stats, init_db
from .overlay import apply_overlay, generate_overlay_text, pick_overlay_font, scan_font_dir
from .scanner import scan_directory
from .selector import select_image
from .triggers import FilterCriteria, get_active_triggers, merge_criteria
from .wallpaper import WallpaperError, get_display_aspect_ratio, set_wallpaper


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


def cmd_scan(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    db_path = config.resolved_db_path

    print(f"Scanning: {config.image_dir}")
    if args.dry_run:
        print("(dry run — no writes)")

    def progress(done: int, total: int) -> None:
        print(f"\r  {done}/{total}", end="", flush=True)

    result = scan_directory(
        image_dir=config.image_dir,
        db_path=db_path,
        config=config,
        force_reclassify=args.force,
        dry_run=args.dry_run,
        progress_callback=progress,
    )
    print()  # newline after progress
    print(
        f"Done in {result.duration_seconds:.1f}s — "
        f"found={result.total_found} "
        f"new={result.newly_classified} "
        f"cached={result.already_classified} "
        f"errors={result.skipped_errors}"
    )
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    db_path = config.resolved_db_path

    if not db_path.exists():
        print(f"Database not found at {db_path}. Run 'driftwall scan' first.", file=sys.stderr)
        return 1

    # Build criteria from triggers (unless suppressed)
    all_criteria: list[FilterCriteria] = []

    if not args.no_triggers:
        triggers = get_active_triggers(config.triggers)
        for trigger in triggers:
            all_criteria.append(trigger.get_criteria(config.triggers))

    # CLI overrides
    override = FilterCriteria()
    if args.genre:
        override.require_genre = args.genre
    if args.mood:
        # mood is stored pipe-delimited; handled via soft preference
        override.prefer_time_of_day = []  # placeholder — mood not a hard filter currently
    if args.orientation:
        override.require_orientation = args.orientation
    all_criteria.append(override)

    criteria = merge_criteria(*all_criteria)

    image = select_image(db_path, criteria, config)
    if image is None:
        print("No matching image found.", file=sys.stderr)
        return 1

    path = Path(image.path)
    if not path.exists():
        print(f"Image file missing: {path}", file=sys.stderr)
        return 1

    # Optional text overlay
    wallpaper_path = path
    use_overlay = config.overlay.enabled and not getattr(args, "no_overlay", False)
    if use_overlay:
        description = image.one_paragraph or image.one_sentence
        if description:
            overlay_model = config.overlay.model or config.ollama.model
            logging.info("Generating overlay text via %s…", overlay_model)
            text = generate_overlay_text(
                description=description,
                prompt=config.overlay.prompt,
                model=overlay_model,
                host=config.ollama.host,
                timeout=config.ollama.timeout,
                num_predict=config.ollama.num_predict,
            )
            if text:
                font_file = config.overlay.font_file
                if config.overlay.font_dir:
                    font_paths = scan_font_dir(config.overlay.font_dir)
                    if font_paths:
                        chosen = pick_overlay_font(
                            font_paths=font_paths,
                            context=text,
                            model=overlay_model,
                            host=config.ollama.host,
                        )
                        font_file = str(chosen)
                        logging.info("Overlay font chosen: %s", chosen.name)
                cache_path = Path.home() / ".cache" / "driftwall" / "overlay.jpg"
                wallpaper_path = apply_overlay(
                    image_path=path,
                    text=text,
                    quadrant=config.overlay.quadrant,
                    font_file=font_file,
                    output_path=cache_path,
                    target_aspect_ratio=get_display_aspect_ratio(),
                )
                logging.info("Overlay applied: %s", text.replace("\n", " / "))

    try:
        set_wallpaper(wallpaper_path)
        print(f"Wallpaper set: {path.name}")
        if args.verbose:
            print(f"  genre={image.genre} time_of_day={image.time_of_day} season={image.season}")
    except WallpaperError as e:
        print(f"Failed to set wallpaper: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    interval = args.interval or config.rotation.interval_minutes
    print(f"Starting daemon (interval={interval}min). Ctrl+C to stop.")

    rotate_args = argparse.Namespace(
        config=args.config,
        no_triggers=False,
        no_overlay=False,
        genre=None,
        mood=None,
        orientation=None,
        verbose=args.verbose,
    )

    while True:
        try:
            cmd_rotate(rotate_args)
        except Exception as e:
            logging.warning("Rotate failed: %s", e)
        time.sleep(interval * 60)


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    db_path = config.resolved_db_path

    if not db_path.exists():
        print(f"No database at {db_path}. Run 'driftwall scan' first.")
        return 0

    stats = get_stats(db_path)
    print(f"Database: {db_path}")
    print(f"Total images: {stats['total_images']}")
    print(f"Total shown:  {stats['total_shown']}")
    print()
    print("Genre breakdown:")
    for genre, count in stats["genre_counts"].items():
        print(f"  {genre:<20} {count}")
    print()
    print("Last 5 shown:")
    for entry in stats["last_shown"]:
        print(f"  {entry['shown_at'][:19]}  {Path(entry['path']).name}")

    return 0


def cmd_config(args: argparse.Namespace) -> int:
    config_path = args.config or None
    if args.show_path:
        from .config import DEFAULT_CONFIG_PATH
        path = config_path or DEFAULT_CONFIG_PATH
        print(path)
        return 0

    config = load_config(config_path)
    print(f"image_dir:     {config.image_dir}")
    print(f"db_path:       {config.resolved_db_path}")
    print(f"prompt_path:   {config.prompt_path}")
    print()
    print("[ollama]")
    print(f"  model:       {config.ollama.model}")
    print(f"  timeout:     {config.ollama.timeout}s")
    print(f"  concurrency: {config.ollama.concurrency}")
    print(f"  host:        {config.ollama.host}")
    print(f"  num_predict: {config.ollama.num_predict}")
    print()
    print("[rotation]")
    print(f"  interval:    {config.rotation.interval_minutes}min")
    print(f"  avoid_repeat_window: {config.rotation.avoid_repeat_window}")
    print()
    print("[filters]")
    print(f"  exclude_genre:    {config.filters.exclude_genre}")
    print(f"  exclude_faces:    {config.filters.exclude_faces}")
    print(f"  min_megapixels:   {config.filters.min_megapixels}")
    print(f"  require_setting:  {config.filters.require_setting}")
    print(f"  require_orientation: {config.filters.require_orientation}")
    print()
    print("[triggers]")
    print(f"  enabled:     {config.triggers.enabled}")
    print()
    print("[overlay]")
    print(f"  enabled:     {config.overlay.enabled}")
    print(f"  prompt:      {config.overlay.prompt}")
    print(f"  model:       {config.overlay.model or '(same as ollama.model)'}")
    print(f"  quadrant:    {config.overlay.quadrant}")
    print(f"  font_file:   {config.overlay.font_file or '(auto)'}")
    print(f"  font_dir:    {config.overlay.font_dir or '(none)'}")

    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    import os
    import sys
    import driftwall as _dw
    from pathlib import Path

    # The editable install uses a path-hook finder that system python3 won't load
    # via PYTHONPATH, so we add the project root explicitly alongside the venv's
    # site-packages (for ollama, PIL, tomli_w, etc.).
    project_root = str(Path(_dw.__file__).parent.parent)
    site_pkgs = [p for p in sys.path if "site-packages" in p]
    python_path = os.pathsep.join([project_root] + site_pkgs)
    env = {**os.environ, "PYTHONPATH": python_path}

    cmd = ["/usr/bin/python3", "-m", "driftwall.ui"]
    if args.config:
        cmd += ["--config", str(args.config)]

    os.execve("/usr/bin/python3", cmd, env)
    return 0  # unreachable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="driftwall",
        description="Dynamic wallpaper rotator with LLM classification",
    )
    parser.add_argument(
        "--config", metavar="PATH", type=Path, default=None,
        help="Path to config.toml (default: ~/.config/driftwall/config.toml)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")

    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Classify new images in image_dir")
    p_scan.add_argument("--force", action="store_true", help="Re-classify all images")
    p_scan.add_argument("--dry-run", action="store_true", help="List images without writing")

    # rotate
    p_rotate = sub.add_parser("rotate", help="Select and set wallpaper once")
    p_rotate.add_argument("--genre", nargs="+", metavar="GENRE", help="Require specific genre(s)")
    p_rotate.add_argument("--mood", nargs="+", metavar="MOOD", help="Prefer specific mood(s)")
    p_rotate.add_argument("--orientation", nargs="+", metavar="ORI", help="Require orientation(s)")
    p_rotate.add_argument("--no-triggers", action="store_true", help="Disable automatic triggers")
    p_rotate.add_argument("--no-overlay", action="store_true", help="Skip text overlay even if enabled in config")

    # daemon
    p_daemon = sub.add_parser("daemon", help="Rotate wallpaper on a timer")
    p_daemon.add_argument("--interval", type=int, metavar="N", help="Interval in minutes")

    # status
    sub.add_parser("status", help="Show DB stats and recent history")

    # config
    p_config = sub.add_parser("config", help="Print resolved configuration")
    p_config.add_argument("--show-path", action="store_true", help="Print config file path only")

    # ui
    sub.add_parser("ui", help="Launch system tray UI (GTK3)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _setup_logging(getattr(args, "verbose", False))

    handlers = {
        "scan": cmd_scan,
        "rotate": cmd_rotate,
        "daemon": cmd_daemon,
        "status": cmd_status,
        "config": cmd_config,
        "ui": cmd_ui,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args) or 0)


if __name__ == "__main__":
    main()
