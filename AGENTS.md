# Driftwall — Agent Notes

## System Tray Service

The GTK3 tray UI runs as a user systemd service:

```
systemctl --user status driftwall-ui
```

**After making any changes to the UI code, you must restart the service for them to take effect:**

```bash
systemctl --user restart driftwall-ui
```

The service uses the installed package from `.venv`. If you have changed Python source files but not reinstalled, do a quick editable reinstall first:

```bash
source .venv/bin/activate && pip install -e .
systemctl --user restart driftwall-ui
```

To watch live logs from the tray app:

```bash
journalctl --user -u driftwall-ui -f
```

## Project Layout

```
driftwall/
├── cli.py          # argparse entry point
├── config.py       # TOML config dataclasses
├── db.py           # SQLite queries
├── classifier.py   # Ollama vision classification
├── scanner.py      # Incremental directory scan
├── triggers.py     # Time/season filter triggers
├── selector.py     # Weighted image selection
├── overlay.py      # LLM text overlay on wallpaper
├── downloader.py   # Met Museum API downloader
├── wallpaper.py    # gsettings wallpaper setter
└── ui/
    ├── app.py      # DriftwallApp — tray indicator + menu
    ├── settings.py # SettingsDialog — multi-tab config editor
    ├── fetch.py    # FetchDialog — artwork downloader UI
    └── status.py   # StatusWindow — DB stats viewer
```

## Config & Data

| Purpose | Default path |
|---|---|
| Config | `~/.config/driftwall/config.toml` |
| Database | `~/.local/share/driftwall/driftwall.db` |
| Overlay cache | `~/.cache/driftwall/overlay.jpg` |
| Downloads | `~/Pictures/driftwall-downloads/{source}/…` |

## Tests

We use Python `unittest` for unit tests and follow TDD: write or update a failing test first, then implement the code change.

Run tests from the repo root:

```bash
source .venv/bin/activate && python -m unittest discover -s tests -v
```

Run tests before opening or merging changes, and after modifying core logic (config loading, trigger/filter behavior, selection/query logic, scanning/downloading helpers).

## Visual verification of overlays

GTK overlay behavior (placement, font readability, panel/dock collisions) cannot be checked from unit tests alone. When working on `dynamic_overlay.py`, `overlay.py`, `windowing.py`, `font_selection.py`, or anything else that paints on screen, **screenshot the live desktop and check the result yourself** — do not rely solely on the user's report.

Workflow:

1. Make the change, then `pip install -e . && systemctl --user restart driftwall-ui`.
2. Run the placement checker, which finds driftwall overlay windows by WM_CLASS, reads `_NET_WORKAREA` + `_NET_WM_STRUT_PARTIAL`, and reports overlap / off-screen / panel-collision issues:

   ```bash
   python tools/overlay_check.py                  # one shot
   python tools/overlay_check.py --save out.png   # also save annotated screenshot
   python tools/overlay_check.py --watch          # re-run every 5s
   ```

3. Read the saved PNG (annotated with red overlay rects, cyan work area, magenta struts, and a green issues block) to spot-check visual quality — font readability, breathing room from the panel/dock, scrim contrast, etc. The checker reports geometry; only the screenshot reveals "this font is unreadable" or "the scrim is too dark."
4. The dynamic overlay spawn interval is in `[dynamic_overlay].spawn_interval_seconds` (default 60s). To wait for a second overlay before checking mutual placement, poll with `until [ "$(... overlay count)" -ge 2 ]; do sleep 5; done`.

`tools/overlay_check.py` requires X11 (`xprop`, `xwininfo`) and `PIL.ImageGrab` — both already available on the dev box. It auto-detects the display from `$DISPLAY` or `/tmp/.X11-unix/`. The checker is dev-only; do not depend on it from production code.

Pure-geometry helpers (`compute_overlay_bounds`, `zone_rect`, `_truncate_for_display`) live in `windowing.py` / extracted from `dynamic_overlay.py` so they are unit-testable without `gi`/GTK installed in the venv.
