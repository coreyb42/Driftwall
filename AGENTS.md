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
