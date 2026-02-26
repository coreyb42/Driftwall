# Driftwall

A dynamic wallpaper rotator for GNOME that uses a local vision LLM to classify your photo library once, then rotates wallpapers intelligently based on what's in each image and real-time context — time of day, season, genre, orientation, and more.

> **Status:** Image scanning and classification are working. The rotation, daemon, and selection features are implemented but not yet fully tested.

---

## How It Works

**Classification (once per image)**

Each image is hashed (SHA-256) and, if not already in the database, sent to a local Ollama vision model with a structured prompt. The model returns rich metadata — genre, season, time of day, orientation, mood, quality, subject, and more — which is stored flat in a local SQLite database. Moving or renaming files is handled gracefully: the hash is the canonical identity, not the path.

Images are downscaled in memory before being sent to the model (default: 1344px on the longest edge). Original files are never modified.

**Selection (every rotation)**

1. Active triggers (time of day, season) produce *soft* preferences — images matching the current context score higher but are not excluded.
2. Hard filters from config (`exclude_genre`, `min_megapixels`, etc.) narrow the candidate pool via SQL.
3. Recently shown images are excluded (configurable window).
4. A weighted random pick from scored candidates sets the wallpaper via `gsettings`.

---

## Requirements

- **Python 3.10+**
- **GNOME desktop** — wallpaper is set via `gsettings`
- **[Ollama](https://ollama.com)** — runs the vision model locally for classification

### GPU Requirements

The default model is `qwen3-vl:30b`, which requires approximately **24 GB of VRAM**. Classification is a one-time cost per image; rotation does not require the GPU at all.

If you have a smaller GPU, you can use a lighter model instead:

```toml
[ollama]
model = "qwen3-vl:8b"   # ~8 GB VRAM
```

Any Ollama vision model that accepts image inputs should work. The prompt is in `photo_class_prompt.txt` and can be tuned to match different model capabilities.

---

## Installation

```bash
git clone https://github.com/your-username/driftwall.git
cd driftwall
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then pull your chosen model in Ollama:

```bash
ollama pull qwen3-vl:30b   # or qwen3-vl:8b, etc.
```

---

## Configuration

Create `~/.config/driftwall/config.toml`:

```toml
image_dir = "/path/to/your/photos"   # required

[ollama]
model       = "qwen3-vl:30b"         # any Ollama vision model
timeout     = 120                    # seconds per image
concurrency = 1                      # keep at 1 for large models
host        = "http://localhost:11434"
max_image_pixels = 1344              # longest edge before sending; 0 = no resize

[rotation]
interval_minutes     = 30
avoid_repeat_window  = 50            # don't repeat images within last N shown

[filters]
exclude_genre       = ["screenshot"]
exclude_faces       = false
min_megapixels      = 0.0
require_setting     = []             # e.g. ["outdoor"]
require_orientation = []             # e.g. ["landscape"]

[triggers]
enabled = true                       # time-of-day and season soft preferences
```

The database is stored at `~/.local/share/driftwall/driftwall.db` (local filesystem — SQLite does not work on network mounts).

---

## Usage

```bash
# Classify all images in image_dir (long, runs the LLM on each new image)
driftwall scan

# Check what's been classified
driftwall status

# Set wallpaper once
driftwall rotate

# Run as a background daemon
driftwall daemon --interval 30
```

### All Commands

| Command | Description |
|---|---|
| `driftwall scan` | Walk `image_dir`, classify new images via Ollama |
| `driftwall scan --force` | Re-classify all images |
| `driftwall scan --dry-run` | List images that would be classified, no writes |
| `driftwall rotate` | Select and set wallpaper once |
| `driftwall rotate --no-triggers` | Ignore time-of-day / season context |
| `driftwall rotate --genre landscape` | Require specific genre(s) |
| `driftwall rotate --orientation landscape` | Require specific orientation(s) |
| `driftwall daemon` | Rotate on a timer |
| `driftwall daemon --interval 15` | Override interval in minutes |
| `driftwall status` | DB stats, genre breakdown, last 5 shown |
| `driftwall config` | Print resolved configuration |

---

## Project Layout

```
driftwall/
├── driftwall/
│   ├── cli.py           # Entry point, all subcommands
│   ├── config.py        # TOML loading, Config dataclasses
│   ├── db.py            # SQLite schema, ImageRecord, all queries
│   ├── classifier.py    # Ollama integration, image resizing, JSON parsing
│   ├── scanner.py       # Directory walk, incremental scan
│   ├── triggers.py      # FilterCriteria, time-of-day and season triggers
│   ├── selector.py      # Query builder, weighted random selection
│   └── wallpaper.py     # gsettings wrapper
├── photo_class_prompt.txt   # Vision model prompt (editable)
├── pyproject.toml
└── README.md
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `ollama` | Ollama Python client |
| `Pillow` | In-memory image resizing before classification |
| `json-repair` | Recovery of malformed JSON from model output |
| `tomli` | TOML parsing on Python < 3.11 |

All other dependencies (`sqlite3`, `argparse`, `hashlib`, `pathlib`) are stdlib.
