"""Driftwall CLI — argparse entry point with all subcommands."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .config import (
    PAUSE_SENTINEL_PATH,
    clear_pause_sentinel,
    is_paused,
    load_config,
    set_pause_sentinel,
)
from .db import get_stats, init_db
from .font_selection import build_font_options, pick_font_for_context
from .overlay import apply_overlay, generate_overlay_text
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

    # Determine what to scan. Default (no flags) = images only for backward compat.
    do_images = getattr(args, "images", False) or not getattr(args, "content", False)
    do_content = getattr(args, "content", False)

    if args.dry_run:
        print("(dry run — no writes)")

    if do_images:
        total_result = None
        for image_dir in config.image_dirs:
            print(f"Scanning images: {image_dir}")

            def progress(done: int, total: int) -> None:
                print(f"\r  {done}/{total}", end="", flush=True)

            result = scan_directory(
                image_dir=image_dir,
                db_path=db_path,
                config=config,
                force_reclassify=args.force,
                dry_run=args.dry_run,
                progress_callback=progress,
                show_output=getattr(args, "show_output", False),
            )
            print()  # newline after progress
            print(
                f"  Done in {result.duration_seconds:.1f}s — "
                f"found={result.total_found} "
                f"new={result.newly_classified} "
                f"cached={result.already_classified} "
                f"errors={result.skipped_errors}"
            )

            if total_result is None:
                total_result = result
            else:
                from .scanner import ScanResult
                total_result = ScanResult(
                    total_found=total_result.total_found + result.total_found,
                    newly_classified=total_result.newly_classified + result.newly_classified,
                    already_classified=total_result.already_classified + result.already_classified,
                    skipped_errors=total_result.skipped_errors + result.skipped_errors,
                    duration_seconds=total_result.duration_seconds + result.duration_seconds,
                )

        if total_result and len(config.image_dirs) > 1:
            print(
                f"Total: found={total_result.total_found} "
                f"new={total_result.newly_classified} "
                f"cached={total_result.already_classified} "
                f"errors={total_result.skipped_errors}"
            )

    if do_images and getattr(args, "embed", False) and not args.dry_run:
        from .image_embedder import embed_all_images
        embed_model = config.content.embed_model
        print(f"Embedding images (model: {embed_model})...")

        def embed_progress(done: int, total: int) -> None:
            print(f"\r  {done}/{total}", end="", flush=True)

        embed_result = embed_all_images(
            db_path=db_path,
            embed_model=embed_model,
            host=config.ollama.host,
            progress_callback=embed_progress,
        )
        print()
        print(
            f"  Embedded={embed_result.embedded} "
            f"skipped={embed_result.skipped_no_text} "
            f"errors={embed_result.errors}"
        )

    if do_content:
        from .content_scanner import scan_content_dir
        content_dir = config.content.content_dir
        print(f"Scanning content: {content_dir}")

        if not content_dir.exists():
            print(f"  Content directory not found: {content_dir}", file=sys.stderr)
        elif args.dry_run:
            files = sorted(
                f for f in content_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in (".txt", ".md", ".csv")
            )
            print(f"  Would index {len(files)} file(s) (dry run)")
        else:
            def content_progress(done: int, total: int) -> None:
                print(f"\r  {done}/{total}", end="", flush=True)

            result = scan_content_dir(
                content_dir=content_dir,
                db_path=db_path,
                chroma_path=config.resolved_chroma_path,
                config=config,
                force_reindex=args.force,
                progress_callback=content_progress,
            )
            print()
            print(
                f"  Done in {result.duration_seconds:.1f}s — "
                f"found={result.total_found} "
                f"new={result.newly_indexed} "
                f"cached={result.already_indexed} "
                f"errors={result.skipped_errors}"
            )

    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    if is_paused():
        logging.info("Wallpaper rotation paused; skipping rotate.")
        return 0

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
            import random as _random
            overlay_prompt = _random.choice(config.overlay.prompts)
            overlay_quadrant = _random.choice(config.overlay.quadrants)
            overlay_model = config.overlay.model or config.ollama.model
            logging.info("Generating overlay text via %s… (prompt: %s)", overlay_model, overlay_prompt)
            text = generate_overlay_text(
                description=description,
                prompt=overlay_prompt,
                model=overlay_model,
                host=config.ollama.host,
                timeout=config.ollama.timeout,
                num_predict=config.ollama.num_predict,
            )
            if text:
                font_file = ""
                font_options = build_font_options(config)
                if font_options:
                    chosen = pick_font_for_context(
                        options=font_options,
                        context=text,
                        purpose="wallpaper text overlay",
                        model=overlay_model,
                        host=config.ollama.host,
                    )
                    font_file = str(chosen)
                    logging.info("Overlay font chosen: %s", chosen.name)
                cache_path = Path.home() / ".cache" / "driftwall" / "overlay.jpg"
                wallpaper_path = apply_overlay(
                    image_path=path,
                    text=text,
                    quadrant=overlay_quadrant,
                    font_file=font_file,
                    font_size=config.overlay.font_size,
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
    cli_interval = args.interval  # explicit CLI override; None means "read from config"
    config = load_config(args.config)
    interval = cli_interval or config.rotation.interval_minutes
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
        # Re-read interval from config each cycle so UI settings take effect immediately.
        if not cli_interval:
            try:
                interval = load_config(args.config).rotation.interval_minutes
            except Exception:
                pass  # keep previous interval if config is temporarily unreadable
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
    if len(config.image_dirs) == 1:
        print(f"image_dirs:    {config.image_dirs[0]}")
    else:
        print("image_dirs:")
        for d in config.image_dirs:
            print(f"  {d}")
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
    print("[fonts]")
    print(f"  source:      {config.fonts.source}")
    print(f"  directory:   {config.fonts.directory or '(none)'}")
    if config.fonts.entries:
        print("  entries:")
        for entry in config.fonts.entries:
            desc = entry.get("description", "").strip()
            if desc:
                print(f"    - {entry.get('path', '')}  ({desc})")
            else:
                print(f"    - {entry.get('path', '')}")
    else:
        print("  entries:     []")
    print()
    print("[overlay]")
    print(f"  enabled:     {config.overlay.enabled}")
    prompts = config.overlay.prompts
    if len(prompts) == 1:
        print(f"  prompt:      {prompts[0]}")
    else:
        print(f"  prompts:     {prompts}")
    print(f"  model:       {config.overlay.model or '(same as ollama.model)'}")
    print(f"  font_size:   {config.overlay.font_size or 'auto'}")
    quadrants = config.overlay.quadrants
    if len(quadrants) == 1:
        print(f"  quadrant:    {quadrants[0]}")
    else:
        print(f"  quadrants:   {quadrants}")
    print()
    print("[download]")
    print(f"  output_dir:  {config.download.output_dir}")
    print()
    print("[content]")
    print(f"  enabled:     {config.content.enabled}")
    print(f"  content_dir: {config.content.content_dir}")
    print(f"  chroma_path: {config.resolved_chroma_path}")
    print(f"  embed_model: {config.content.embed_model}")
    print()
    print("[dynamic_overlay]")
    print(f"  enabled:             {config.dynamic_overlay.enabled}")
    print(f"  max_simultaneous:    {config.dynamic_overlay.max_simultaneous}")
    print(f"  min_lifetime:        {config.dynamic_overlay.min_lifetime_seconds}s")
    print(f"  max_lifetime:        {config.dynamic_overlay.max_lifetime_seconds}s")
    print(f"  spawn_interval:      {config.dynamic_overlay.spawn_interval_seconds}s")
    print(f"  random_source_subset_size: {config.dynamic_overlay.random_source_subset_size}")
    print(f"  font_size:           {config.dynamic_overlay.font_size}px")
    print(f"  max_screen_fraction: {config.dynamic_overlay.max_screen_fraction}")

    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    if args.source == "nasa":
        return _cmd_fetch_nasa(args)

    from .downloader import download_met_artworks, met_list_departments, met_output_subdir

    if args.source != "met":
        print(f"Unknown source: {args.source}", file=sys.stderr)
        return 1

    if args.list_departments:
        depts = met_list_departments()
        for d in depts:
            print(f"  {d['departmentId']:>4}  {d['displayName']}")
        return 0

    if args.department is None and args.search is None:
        print(
            "Error: specify --department, --search, or --list-departments",
            file=sys.stderr,
        )
        return 1

    config = load_config(args.config)
    base_dir = args.output_dir or config.download.output_dir
    output_dir = met_output_subdir(
        base_dir,
        department_id=args.department,
        search_query=args.search,
    )

    from datetime import datetime
    t_start = time.monotonic()
    started_at = datetime.now().strftime("%H:%M:%S")
    print(f"Started at {started_at}", flush=True)

    result = download_met_artworks(
        output_dir=output_dir,
        department_id=args.department,
        search_query=args.search,
        limit=args.limit,
        dry_run=args.dry_run,
        request_delay=1.0,
        progress_callback=lambda msg: print(msg, flush=True),
    )

    elapsed = time.monotonic() - t_start
    finished_at = datetime.now().strftime("%H:%M:%S")
    mins, secs = divmod(int(elapsed), 60)
    elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    print(flush=True)
    print(f"Started:                   {started_at}", flush=True)
    print(f"Finished:                  {finished_at}  (elapsed: {elapsed_str})", flush=True)
    print(flush=True)
    print(f"Downloaded:                {result.downloaded}", flush=True)
    print(f"Skipped (not landscape):   {result.skipped_not_landscape}", flush=True)
    print(f"Skipped (no image/rights): {result.skipped_no_image}", flush=True)
    print(f"Skipped (already exist):   {result.skipped_existing}", flush=True)
    print(f"Errors:                    {result.errors}", flush=True)

    if result.downloaded > 0 and not args.dry_run:
        print(f"\nImages saved to: {output_dir}", flush=True)
        print("Run 'driftwall scan' to classify the new images.", flush=True)

    return 0


def _cmd_fetch_nasa(args: argparse.Namespace) -> int:
    from datetime import datetime

    config = load_config(args.config)
    output_dir = args.output_dir or Path("/mnt/Central Storage/Wallpapers/Desktop/Downloads/NASA")
    t_start = time.monotonic()
    started_at = datetime.now().strftime("%H:%M:%S")

    if getattr(args, "reclassify", False):
        from .nasa_downloader import reclassify_nasa_images

        print(f"Started at {started_at}", flush=True)
        result = reclassify_nasa_images(
            output_dir=output_dir,
            config=config,
            db_path=config.resolved_db_path,
            dry_run=args.dry_run,
            progress_callback=lambda msg: None,
            show_output=getattr(args, "show_output", False),
        )

        elapsed = time.monotonic() - t_start
        finished_at = datetime.now().strftime("%H:%M:%S")
        mins, secs = divmod(int(elapsed), 60)
        elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        print(flush=True)
        print(f"Started:                   {started_at}", flush=True)
        print(f"Finished:                  {finished_at}  (elapsed: {elapsed_str})", flush=True)
        print(flush=True)
        print(f"Re-classified:             {result.reclassified}", flush=True)
        print(f"Flagged (has people):      {result.flagged_has_people}", flush=True)
        print(f"Skipped (no API metadata): {result.skipped_no_metadata}", flush=True)
        print(f"Errors:                    {result.errors}", flush=True)
        return 0

    from .nasa_downloader import download_nasa_images

    if not args.search:
        print("Error: --search QUERY is required for --source nasa", file=sys.stderr)
        return 1

    classify = not getattr(args, "no_classify", False)

    print(f"Started at {started_at}", flush=True)
    result = download_nasa_images(
        output_dir=output_dir,
        query=args.search,
        limit=args.limit,
        dry_run=args.dry_run,
        classify=classify,
        config=config,
        db_path=config.resolved_db_path,
        progress_callback=lambda msg: None,  # already printed inside
        show_output=getattr(args, "show_output", False),
    )

    elapsed = time.monotonic() - t_start
    finished_at = datetime.now().strftime("%H:%M:%S")
    mins, secs = divmod(int(elapsed), 60)
    elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    print(flush=True)
    print(f"Started:                      {started_at}", flush=True)
    print(f"Finished:                     {finished_at}  (elapsed: {elapsed_str})", flush=True)
    print(flush=True)
    print(f"Downloaded:                   {result.downloaded}", flush=True)
    print(f"Skipped (not landscape):      {result.skipped_not_landscape}", flush=True)
    print(f"Skipped (has people):         {result.skipped_has_people}", flush=True)
    print(f"Skipped (no image/manifest):  {result.skipped_no_image}", flush=True)
    print(f"Skipped (already exist):      {result.skipped_existing}", flush=True)
    print(f"Errors:                       {result.errors}", flush=True)

    if result.downloaded > 0 and not args.dry_run:
        print(f"\nImages saved to: {output_dir}", flush=True)
        if classify:
            print("Images are already classified and in the DB.", flush=True)
        else:
            print("Run 'driftwall scan' to classify the downloaded images.", flush=True)

    return 0


def cmd_embed(args: argparse.Namespace) -> int:
    from .image_embedder import embed_all_images

    config = load_config(args.config)
    db_path = config.resolved_db_path
    embed_model = config.content.embed_model

    if not db_path.exists():
        print(f"No database at {db_path}. Run 'driftwall scan' first.", file=sys.stderr)
        return 1

    init_db(db_path)

    if args.dry_run:
        from .db import get_images_missing_embeddings, query_images
        images = query_images(db_path, [], []) if args.force else get_images_missing_embeddings(db_path, embed_model)
        print(f"Would embed {len(images)} image(s) using model '{embed_model}' (dry run)")
        return 0

    print(f"Computing embeddings using model '{embed_model}'...")

    def progress(done: int, total: int) -> None:
        print(f"\r  {done}/{total}", end="", flush=True)

    result = embed_all_images(
        db_path=db_path,
        embed_model=embed_model,
        host=config.ollama.host,
        force=args.force,
        progress_callback=progress,
    )
    print()
    print(
        f"  Total={result.total} "
        f"embedded={result.embedded} "
        f"skipped={result.skipped_no_text} "
        f"errors={result.errors}"
    )
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    set_pause_sentinel()
    print("Wallpaper rotation paused.")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    clear_pause_sentinel()
    print("Wallpaper rotation resumed.")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    import os
    import sys
    import driftwall as _dw
    from pathlib import Path

    # Tray launch implies an active session — clear any stale pause sentinel so
    # rotations resume even if the tray was killed mid-pause.
    clear_pause_sentinel()

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
    p_scan = sub.add_parser("scan", help="Classify new images and/or index content")
    p_scan.add_argument("--force", action="store_true", help="Re-classify/re-index regardless of cache")
    p_scan.add_argument("--dry-run", action="store_true", help="List files without writing")
    p_scan.add_argument("--images", action="store_true", help="Scan image directories (explicit)")
    p_scan.add_argument("--content", action="store_true", help="Scan content directory for quotes/text")
    p_scan.add_argument("--embed", action="store_true", help="Compute image embeddings after scanning (requires --images or default scan)")
    p_scan.add_argument("--show-output", action="store_true", help="Print raw classifier JSON for each newly classified image")

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

    # fetch
    p_fetch = sub.add_parser("fetch", help="Download artworks from external art APIs")
    p_fetch.add_argument("--source", default="met", choices=["met", "nasa"], help="Art collection source (default: met)")
    p_fetch.add_argument("--list-departments", action="store_true", help="[met] List available Met departments and exit")
    p_fetch.add_argument("--department", type=int, metavar="ID", help="[met] Met department ID to fetch from")
    p_fetch.add_argument("--search", metavar="QUERY", help="Search query string (required for --source nasa)")
    p_fetch.add_argument("--limit", type=int, default=50, metavar="N", help="Max landscape images to save (default: 50)")
    p_fetch.add_argument("--output-dir", type=Path, metavar="DIR", help="Directory to save images (default: from config / NASA default)")
    p_fetch.add_argument("--dry-run", action="store_true", help="Log without writing files")
    p_fetch.add_argument("--no-classify", action="store_true", help="[nasa] Skip LLM classification (faster, no people filter)")
    p_fetch.add_argument("--reclassify", action="store_true", help="[nasa] Re-classify images already on disk using API metadata (no download)")
    p_fetch.add_argument("--show-output", action="store_true", help="Print raw classifier JSON for each classified image")

    # embed
    p_embed = sub.add_parser("embed", help="Pre-compute image embeddings for content search")
    p_embed.add_argument("--force", action="store_true", help="Re-embed all images, even if already computed")
    p_embed.add_argument("--dry-run", action="store_true", help="Show how many images would be embedded")

    # ui
    sub.add_parser("ui", help="Launch system tray UI (GTK3)")

    # pause / resume
    sub.add_parser("pause", help="Pause wallpaper rotation (tray menu equivalent)")
    sub.add_parser("resume", help="Resume wallpaper rotation")

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
        "fetch": cmd_fetch,
        "embed": cmd_embed,
        "ui": cmd_ui,
        "pause": cmd_pause,
        "resume": cmd_resume,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args) or 0)


if __name__ == "__main__":
    main()
