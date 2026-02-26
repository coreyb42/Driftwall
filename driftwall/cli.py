"""Driftwall CLI — argparse entry point with all subcommands."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .config import load_config
from .db import get_stats, init_db
from .scanner import scan_directory
from .selector import select_image
from .triggers import FilterCriteria, get_active_triggers, merge_criteria
from .wallpaper import WallpaperError, set_wallpaper


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

    try:
        set_wallpaper(path)
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

    return 0


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

    # daemon
    p_daemon = sub.add_parser("daemon", help="Rotate wallpaper on a timer")
    p_daemon.add_argument("--interval", type=int, metavar="N", help="Interval in minutes")

    # status
    sub.add_parser("status", help="Show DB stats and recent history")

    # config
    p_config = sub.add_parser("config", help="Print resolved configuration")
    p_config.add_argument("--show-path", action="store_true", help="Print config file path only")

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
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args) or 0)


if __name__ == "__main__":
    main()
