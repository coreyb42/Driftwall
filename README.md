# Driftwall

A dynamic wallpaper rotator for GNOME that uses a local vision LLM to classify your photo library once, then rotates wallpapers intelligently based on what's in each image and real-time context — time of day, season, genre, orientation, and more.

While a wallpaper is displayed, Driftwall can surface **quotes, book excerpts, and short poems** that are semantically related to the image — a passage about autumn when a foggy forest is on your screen, a nautical quote when waves are showing. Each snippet fades in and out on its own cadence, independent of the rotation cycle, creating a living desktop that feels curated rather than random.

---

## How It Works

### Wallpaper rotation

**Classification (once per image)**

Each image is hashed (SHA-256) and, if not already in the database, sent to a local Ollama vision model with a structured prompt. The model returns rich metadata — genre, season, time of day, orientation, mood, quality, subject, and more — which is stored flat in a local SQLite database. Moving or renaming files is handled gracefully: the hash is the canonical identity, not the path.

Images are downscaled in memory before being sent to the model (default: 1344px on the longest edge). Original files are never modified.

**Selection (every rotation)**

1. Active triggers (time of day, season) produce *soft* preferences — images matching the current context score higher but are not excluded.
2. Hard filters from config (`exclude_genre`, `min_megapixels`, etc.) narrow the candidate pool via SQL.
3. Recently shown images are excluded (configurable window).
4. A weighted random pick from scored candidates sets the wallpaper via `gsettings`.

### Semantic content overlays

This is the feature that makes Driftwall feel genuinely alive.

You point Driftwall at a folder of text — Project Gutenberg books, your own writing, quote CSV files, anything — and it embeds everything into a local ChromaDB vector store using an Ollama embedding model. When a new wallpaper appears, Driftwall queries that store using the image's LLM-generated description (mood, subject, setting, season, keywords) and retrieves the most semantically relevant passages.

Those passages then float over the wallpaper as small, dark-scrimmed text overlays that fade in and out on a timer. A mountain landscape might surface Muir quotes or Thoreau paragraphs. A storm at sea might pull up Conrad or Melville. A snowy city street might bring up Chekhov. None of this is hardcoded — it emerges from the semantic similarity between what's in the image and what's in your text library.

**Content format:**
- `.txt` / `.md` / `.rst` — prose is chunked at paragraph/sentence boundaries (300–600 chars); poetry short-line blocks and chapter headers are handled automatically
- `.csv` — one quote per row, with optional `author`, `date`, and `source` columns; attribution lines are rendered automatically below each quote
- `.epub` / `.pdf` / `.html` / `.docx` / `.mobi` — full ebook and document ingestion; requires optional dependencies (`pip install -e ".[ebooks]"` or install individually — see below)

### LLM-named text overlays (static)

Separately from the dynamic quotes, Driftwall can ask an LLM to write something specific for each wallpaper — a haiku, a caption, a one-line poem — and render it as a static text overlay in a corner of the image (composited directly into the wallpaper). The font can be auto-detected from system fonts or set explicitly, and the LLM can pick a font from a directory based on the content.

### Artwork downloader

`driftwall fetch` downloads public-domain artworks from the **Metropolitan Museum of Art Open Access** collection. You can browse by department (Impressionism, European Paintings, Arms & Armor…) or search by keyword, and Driftwall will pull landscape-oriented images up to a configurable limit, saving them ready to scan. More art sources are planned.

---

## Requirements

- **Python 3.10+**
- **GNOME desktop** — wallpaper is set via `gsettings`
- **[Ollama](https://ollama.com)** — runs the vision and text models locally

### GPU Requirements

The default classification model is `qwen3-vl:30b`, which requires approximately **24 GB of VRAM**. Classification is a one-time cost per image; rotation, overlay generation, and content search do not require the GPU.

If you have a smaller GPU, you can use a lighter model instead:

```toml
[ollama]
model = "qwen3-vl:8b"   # ~8 GB VRAM
```

Any Ollama vision model that accepts image inputs should work. The prompt is in `photo_class_prompt.txt` and can be tuned to match different model capabilities.

For semantic content overlays, you also need an embedding model:

```bash
ollama pull nomic-embed-text
```

---

## Installation

```bash
git clone https://github.com/your-username/driftwall.git
cd driftwall
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For the optional system tray UI, install the `ui` extra:

```bash
pip install -e ".[ui]"
```

For semantic content overlays, also install ChromaDB:

```bash
pip install chromadb
```

Then pull your chosen models in Ollama:

```bash
ollama pull qwen3-vl:30b        # vision classifier (or qwen3-vl:8b, etc.)
ollama pull nomic-embed-text    # for semantic content search
```

---

## Configuration

Create `~/.config/driftwall/config.toml`:

```toml
image_dirs = ["~/Pictures"]     # list of directories to scan (also accepts image_dir = "...")

[ollama]
model            = "qwen3-vl:30b"        # any Ollama vision model
timeout          = 120                   # seconds per image
concurrency      = 1                     # keep at 1 for large models
host             = "http://localhost:11434"
max_image_pixels = 1344                  # longest edge before sending; 0 = no resize

[rotation]
interval_minutes    = 30
avoid_repeat_window = 50                 # don't repeat images within last N shown

[filters]
exclude_genre       = ["screenshot"]
exclude_faces       = false
min_megapixels      = 0.0
require_setting     = []                 # e.g. ["outdoor"]
require_orientation = []                 # e.g. ["landscape"]

[triggers]
enabled = true                           # time-of-day and season soft preferences

[overlay]
enabled  = false                         # render a short LLM-written text overlay per wallpaper
prompt   = "a haiku"                     # what to generate from the image description
model    = "lfm2.5-thinking"             # text model; defaults to ollama.model if unset
quadrant = "bottom-right"               # top-left / top-right / bottom-left / bottom-right
font_file = ""                           # path to a specific .otf/.ttf file; empty = auto-detect
font_dir  = ""                           # scan a directory for fonts; LLM picks one per rotation

[content]
enabled     = false                      # enable semantic content ingestion
content_dir = "~/Documents/driftwall-content"  # folder with .txt/.md/.csv files
embed_model = "nomic-embed-text"         # Ollama embedding model

[dynamic_overlay]
enabled               = false            # show floating content overlays while wallpaper is displayed
max_simultaneous      = 3               # overlays visible at once
spawn_interval_seconds = 20             # seconds between spawning a new overlay
random_source_subset_size = 0           # 0 disables; otherwise query against a random subset of N sources
min_lifetime_seconds  = 30              # minimum time an overlay stays visible
max_lifetime_seconds  = 90             # maximum time an overlay stays visible
font_size             = 18              # text size in pixels
max_screen_fraction   = 0.10           # max overlay width/height as fraction of screen

[download]
output_dir = "~/Pictures/driftwall-downloads"  # root for downloaded artwork
```

The database is stored at `~/.local/share/driftwall/driftwall.db` (local filesystem — SQLite does not work on network mounts). The ChromaDB vector store lives at `~/.local/share/driftwall/chromadb` by default.

---

## Usage

```bash
# Classify all images in image_dirs (runs the LLM once per new image)
driftwall scan

# Index your content library for semantic overlay search
driftwall scan --content

# Both at once
driftwall scan --images --content

# Download public-domain artworks from the Met Museum
driftwall fetch --source met --search "landscape" --limit 100
driftwall fetch --source met --department 11 --limit 50
driftwall fetch --source met --list-departments

# Set wallpaper once
driftwall rotate

# Run as a background daemon
driftwall daemon --interval 30

# Launch the system tray UI
driftwall ui
```

### All Commands

| Command | Description |
|---|---|
| `driftwall scan` | Classify new images via Ollama (backward-compatible default) |
| `driftwall scan --images` | Explicit image scan |
| `driftwall scan --content` | Index content directory into ChromaDB |
| `driftwall scan --images --content` | Both |
| `driftwall scan --force` | Re-classify / re-index regardless of cache |
| `driftwall scan --dry-run` | List files without writing |
| `driftwall fetch --source met ...` | Download artworks from the Met Museum |
| `driftwall fetch --list-departments` | List available Met departments |
| `driftwall rotate` | Select and set wallpaper once |
| `driftwall rotate --no-triggers` | Ignore time-of-day / season context |
| `driftwall rotate --genre landscape` | Require specific genre(s) |
| `driftwall rotate --orientation landscape` | Require specific orientation(s) |
| `driftwall rotate --no-overlay` | Skip text overlay for this rotation |
| `driftwall daemon` | Rotate on a timer (blocking) |
| `driftwall daemon --interval 15` | Override interval in minutes |
| `driftwall status` | DB stats, genre breakdown, last 5 shown |
| `driftwall config` | Print resolved configuration |
| `driftwall ui` | Launch the GTK3 system tray UI |

---

## Setting Up Semantic Content Overlays

1. **Install ChromaDB and the embedding model:**
   ```bash
   pip install chromadb
   ollama pull nomic-embed-text
   ```

2. **Create your content library.** Drop any supported files into `~/Documents/driftwall-content/` (or whatever `content_dir` you set). Supported formats: `.txt`, `.md`, `.rst`, `.csv`, `.epub`, `.pdf`, `.html`, `.docx`, `.mobi`. For quotes, use CSV with columns `text`, `author` (optional), `source` (optional), `date` (optional):
   ```csv
   text,author,source
   "In every walk with nature, one receives far more than he seeks.",John Muir,Our National Parks
   "The mountains are calling and I must go.",John Muir,Letter to sister
   ```

3. **Index your content:**
   ```bash
   driftwall scan --content
   ```

4. **Enable in your config:**
   ```toml
   [content]
   enabled = true

   [dynamic_overlay]
   enabled = true
   ```

5. **Restart the tray UI** (or rotate a wallpaper) — overlays will begin appearing within `spawn_interval_seconds`.

---

## Downloading Artworks from the Met Museum

The Met Museum makes hundreds of thousands of public-domain artworks available via their Open Access API. Driftwall can download landscape-oriented works directly into your image library.

```bash
# See what departments are available
driftwall fetch --source met --list-departments

# Download up to 100 landscape paintings from European Paintings (dept 11)
driftwall fetch --source met --department 11 --limit 100

# Download landscapes matching a keyword
driftwall fetch --source met --search "seascape" --limit 50

# Preview without downloading
driftwall fetch --source met --search "forest" --dry-run
```

Images are saved as `met_{objectId}.jpg` under `download_dir/met/[dept-N/][query/]`. After downloading, run `driftwall scan` to classify the new images and add them to rotation.

The downloader only keeps landscape-oriented images (width > height) and skips anything without a public-domain primary image. It respects the Met's API with a 1-second delay between requests and retries on rate-limit responses.

---

## System Tray UI

`driftwall ui` launches a GTK3 appindicator icon in the system tray. It requires **AyatanaAppIndicator3** (pre-installed on Ubuntu) and PyGObject (`python3-gi`), both of which live in the system Python. The UI is launched as a subprocess under `/usr/bin/python3` automatically — the venv does not need to provide `gi`.

**Tray menu:**

| Item | Action |
|---|---|
| Next Wallpaper | Runs `driftwall rotate --no-triggers` immediately |
| Scan → Images | Runs `driftwall scan --images` in the background; item greys out until done |
| Scan → Content | Runs `driftwall scan --content` in the background |
| Fetch Artworks… | Opens the artwork downloader dialog |
| Status | Opens a window showing DB stats, content index stats, and scan logs |
| Settings | Opens a multi-tab dialog for editing `config.toml`; saves without losing unknown keys |
| Quit | Exits the tray process |

The status window shows image counts and genre breakdown alongside content index statistics (indexed files, total chunks, per-file details). Scan logs from image and content scans can be opened in the status window for review.

---

## Running at Login

Two complementary systemd user services cover the common setups.

### Timer-based rotation (headless / no tray)

Runs `driftwall rotate` on a fixed schedule via a systemd timer. Suitable for use without the tray UI, or alongside it.

`~/.config/systemd/user/wallpaper-rotate.service`:
```ini
[Unit]
Description=Rotate Wallpaper (Driftwall)

[Service]
Type=oneshot
ExecStart=/path/to/.venv/bin/driftwall rotate
```

`~/.config/systemd/user/wallpaper-rotate.timer`:
```ini
[Unit]
Description=Run wallpaper rotator every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Persistent=true

[Install]
WantedBy=default.target
```

Enable:
```bash
systemctl --user enable --now wallpaper-rotate.timer
```

### Tray UI (with system tray icon)

`~/.config/systemd/user/driftwall-ui.service`:
```ini
[Unit]
Description=Driftwall wallpaper rotator tray UI
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=/path/to/.venv/bin/driftwall ui
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
```

Enable:
```bash
systemctl --user enable --now driftwall-ui.service
```

The tray UI starts after the graphical session is ready and restarts automatically on failure.

> Both services can run simultaneously — the timer handles scheduled rotation while the tray UI provides manual control and settings editing.

---

## Project Layout

```
driftwall/
├── driftwall/
│   ├── cli.py              # Entry point, all subcommands
│   ├── config.py           # TOML loading, Config dataclasses
│   ├── db.py               # SQLite schema, ImageRecord, all queries
│   ├── classifier.py       # Ollama integration, image resizing, JSON parsing
│   ├── scanner.py          # Directory walk, incremental image scan
│   ├── triggers.py         # FilterCriteria, time-of-day and season triggers
│   ├── selector.py         # Query builder, weighted random selection
│   ├── overlay.py          # Static LLM text overlay generation and compositing
│   ├── content_store.py    # ContentChunk dataclass; ChromaDB CRUD helpers
│   ├── content_scanner.py  # Ingest text/ebook files → chunk → embed → ChromaDB
│   ├── content_search.py   # Build image query, search ChromaDB, return chunks
│   ├── dynamic_overlay.py  # FloatingOverlay (GTK3) + DynamicOverlayManager
│   ├── downloader.py       # Met Museum Open Access API downloader
│   ├── wallpaper.py        # gsettings wallpaper setter
│   └── ui/
│       ├── app.py          # AyatanaAppIndicator3 tray + menu
│       ├── settings.py     # Multi-tab settings dialog (GTK3)
│       ├── status.py       # DB stats + content index window (GTK3)
│       └── fetch.py        # Artwork downloader dialog (GTK3)
├── tests/
│   ├── test_config.py
│   ├── test_triggers.py
│   ├── test_selector.py
│   ├── test_content_scanner.py
│   ├── test_content_search.py
│   └── test_downloader.py
├── photo_class_prompt.txt      # Vision model prompt (editable)
├── pyproject.toml
└── README.md
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `ollama` | Ollama Python client |
| `Pillow` | In-memory image resizing before classification; landscape check for downloads |
| `json-repair` | Recovery of malformed JSON from model output |
| `tomli` | TOML parsing on Python < 3.11 |
| `tomli_w` | TOML writing for the settings dialog (`pip install -e ".[ui]"`) |
| `chromadb` | Vector store for semantic content search (optional; `pip install chromadb`) |
| `python3-gi` | PyGObject / GTK3 — system package, not installed by pip |
| `gir1.2-ayatanaappindicator3-0.1` | AppIndicator3 — system package |

**Optional ebook/document dependencies** (`pip install -e ".[ebooks]"` or individually):

| Package | Format |
|---|---|
| `ebooklib` + `beautifulsoup4` | `.epub` |
| `pypdf` | `.pdf` |
| `beautifulsoup4` | `.html` / `.htm` |
| `python-docx` | `.docx` |
| `mobi` | `.mobi` |

All other dependencies (`sqlite3`, `argparse`, `hashlib`, `pathlib`, `urllib`) are stdlib.
