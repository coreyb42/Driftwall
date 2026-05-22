# Driftwall Next Steps Brainstorming

## Snapshot: What the app is today

Driftwall is a mature, production-ready wallpaper rotator with deep LLM integration:

- **Image classification**: Incremental, hash-based scanning via Ollama vision models (qwen3-vl:30b default). ~50 metadata fields per image: orientation, aspect, mood, genre, subjects, colors, quality, privacy, season, time-of-day, and more.
- **Rotation engine**: Hard SQL filters + soft scoring (time-of-day/season preference bonuses), recency avoidance window, weighted random selection, history tracking.
- **Static overlays**: LLM-generated text (haiku, quote, reflection, etc.) composited onto wallpaper using PIL/Pango, with LLM-picked fonts.
- **Dynamic overlays**: Floating GTK3 windows spawned in a 4×3 grid zone system, fed by semantic ChromaDB search of local content (books, notes, poems, CSVs).
- **Content ingestion**: Multi-format chunking (TXT/MD/RST/CSV/EPUB/PDF/HTML/DOCX/MOBI) with sentence-level splitting and Ollama embeddings.
- **Artwork downloader**: Met Museum Open Access API with 37 department filters, landscape-first selection, rate limiting.
- **System tray UI**: AyatanaAppIndicator3 + multi-tab settings dialog, status viewer, background scan/fetch tasks.
- **CLI**: 7 subcommands — scan, rotate, daemon, status, config, fetch, ui.

The project has evolved significantly beyond its original scope. It is local-first, offline-friendly, and handles edge cases well (hash dedup, retry logic, font fallbacks, JSON repair for LLM outputs).

---

## Current strengths to preserve

- **Local-first architecture**: private, offline, no telemetry.
- **Hash-based deduplication**: handles file moves/renames transparently.
- **Rich metadata depth**: 50+ fields per image — sufficient to power many future features without schema redesign.
- **Graceful degradation**: soft triggers, font fallbacks, JSON repair, ChromaDB errors non-fatal.
- **Content pipeline breadth**: supports ebooks, markdown, CSVs, PDFs; chunked with authorship metadata.
- **Clean module separation**: classifier, selector, overlay, dynamic_overlay, content_search are distinct, composable units.

---

## Current constraints and risks

- **Flat +0.5 scoring**: all soft preferences contribute equally regardless of confidence or user history.
- **Mood filtering is shallow**: `--mood` CLI arg exists but does not meaningfully affect selection logic.
- **No classification provenance**: model name, prompt hash, and timestamp are not stored per image.
- **No schema migrations**: only `CREATE TABLE IF NOT EXISTS` — adding columns to existing installs requires manual intervention.
- **wallpaper_history grows unbounded**: no pruning; table will bloat on long-running installs.
- **Single desktop environment**: GNOME only; KDE/sway/Hyprland users have no path.
- **No user feedback loop**: no like/skip/ban signals to adapt selection weights over time.
- **LLM failure artifacts**: failures are dumped to `driftwall/llm_failures/` but there is no UI to review or retry them.
- **systemd_timer.py is a stub**: timer integration is documented but not implemented in code.
- **No multi-monitor support**: single wallpaper set across all displays; no per-display logic.
- **Overlay grid and static overlay are separate paradigms**: 12 zones vs 4 quadrants; no unified positioning system.
- **No input validation on config dataclasses**: bad TOML values can cause confusing runtime errors.
- **VRAM requirement is high**: 30B model requires ~24GB; no guided fallback to smaller models.

---

## Product directions

### 1) "Daily companion" personalization

Goal: make wallpaper choices feel intentional and emotionally coherent.

Ideas:
- **Feedback loop**: `driftwall like`, `driftwall skip`, `driftwall ban` commands that adjust per-image scores or suppress images permanently.
- **"Energy mode" presets**: calm, focus, vibrant, cozy — maps to genre/mood/color filters + overlay style.
- **Context packs**: work-hours vs evening vs weekend behavior profiles.
- **"Never again" and "snooze" tags**: per-image suppression with optional expiry.
- **Preference profile**: preferred genre/mood/color by weekday/time block, learned from feedback.
- **Wallpaper journal**: at end-of-week, show which images were displayed and how many times.

### 2) Curation and collection management

Goal: move from rotator to intelligent photo curation assistant.

Ideas:
- **Auto-album generation**: cluster images by metadata into named albums (e.g., "winter landscapes", "golden hour portraits").
- **Quality audit**: identify low-quality/duplicate/near-duplicate images and surface them for cleanup in the UI.
- **Near-duplicate suppression**: perceptual hash (pHash) to de-prioritize visually redundant images in selection.
- **Smart pruning recommendations**: flag unknown/low-confidence/redundant images for review.
- **"Best of this month" rotation mode**: limit candidates to high-quality images from a time period.
- **Visual similarity search**: "show me images similar to this one" using image embeddings (CLIP or Ollama).
- **Collections**: user-defined named groups that can be activated per rotation slot.

### 3) Creative overlay and ambient experience

Goal: make the wallpaper feel like ambient art, not just a random image.

Ideas:
- **Overlay templates**: haiku, quote, one-line reflection, title card, passage, question-of-the-day.
- **Style themes**: minimal, cinematic, typewriter, postcard, polaroid, brutalist.
- **Metadata overlay mode**: show image location/time/genre/mood as an optional caption.
- **Content annotation**: when a dynamic overlay appears, link it to the current wallpaper's subject in the search query — already partially implemented via `build_image_query`.
- **Transition effects**: smooth cross-fade between wallpapers instead of instant switch (GNOME compositor integration or pre-composited blends).
- **Time-of-day visual themes**: lighter/airier overlays at morning, warmer/darker at evening.
- **"Silent mode" schedules**: disable all overlays during work hours or meetings.
- **Wallpaper spotlight**: momentary full-screen display of the current wallpaper with metadata before it settles (a "reveal" animation).

### 4) Platform expansion

Goal: increase reach by reducing platform constraints.

Ideas:
- **KDE Plasma adapter**: `plasma-apply-wallpaperimage` + D-Bus.
- **Sway/Hyprland adapters**: `swaybg` or `hyprpaper` via subprocess.
- **macOS adapter**: AppleScript or `osascript` for wallpaper setting.
- **Windows adapter**: `ctypes.windll.user32.SystemParametersInfoW`.
- **Headless/API mode**: HTTP API for remote trigger, monitoring, or integration with home automation.
- **Multi-monitor support**: per-display wallpaper selection and aspect-aware pairing (different images per output).
- **Lock screen wallpaper**: separate rotation schedule for lock screen (GDM/LightDM).

### 5) Discovery and sourcing

Goal: expand and diversify the image library automatically.

Ideas:
- **Unsplash/Pexels adapter**: free API sources with automated landscape/quality filtering.
- **NASA APOD adapter**: Astronomy Picture of the Day — daily fetch + auto-classify.
- **Flickr Creative Commons adapter**: tag-based search with license filtering.
- **Wikimedia Commons adapter**: cultural/historical imagery with attribution.
- **Local import wizard**: drag-and-drop folders into a setup dialog to add image sources.
- **Scheduled auto-fetch**: cron-style periodic downloads from configured sources.
- **Import deduplication**: detect images that already exist (by hash or pHash) before importing.

---

## Technical roadmap (high-impact)

### Foundation: quality and reliability

- **Mood filtering**: implement proper `--mood` support in `rotate` path (filter and/or boost by mood array match).
- **Schema migrations**: Alembic or a custom SQL migration file approach — track schema version in DB, apply incremental patches.
- **History pruning**: cap `wallpaper_history` at configurable max rows (e.g., 10,000) and prune oldest on trim.
- **Config validation**: add field-level validators to config dataclasses (bad types → helpful error message, not traceback).
- **`driftwall doctor`**: diagnose environment: Ollama reachable? Model present? ChromaDB importable? `gsettings` accessible? `xrandr` present? Font available?
- **Systemd templates in repo**: ship `.service` and `.timer` unit files; add `driftwall install-service` command to copy and enable them.
- **Test expansion**:
  - JSON extraction/sanitization edge cases (malformed, truncated, escaped)
  - Selection query builder combinations (all filter permutations)
  - Trigger boundary conditions (midnight, solstice edge cases)
  - DB upsert, path-move, history pruning behavior
  - Dynamic overlay zone allocation and dedup logic
  - Content chunking edge cases (empty paragraphs, single-line files, binary-clean CSV)

### Selection engine evolution

- **Weighted scoring config**: replace fixed +0.5 bonuses with user-configurable weight table in TOML (`[scoring]`).
- **Confidence-aware selection**: reduce score for images classified with low-confidence fields (unknown genre, mood = "unknown").
- **Exploration vs exploitation**: configurable "surprise" factor — occasionally surface rarely-shown images regardless of score.
- **Feedback-adjusted scores**: store per-image `user_score_delta` column, applied on top of computed score.
- **Diversity constraint**: beyond recency window, add a "no same genre twice in a row" soft rule.
- **pHash near-duplicate suppression**: compute perceptual hashes at scan time; reduce scores for images within perceptual distance of recently-shown images.

### Classification pipeline upgrades

- **Provenance fields**: store `classified_by_model`, `classified_at`, `prompt_hash` per image — enables invalidation when model/prompt changes.
- **Retry policy + fallback model**: on parse failure, retry once with a lighter model (e.g., `llava:7b`) before marking as failed.
- **Priority-based scanning**: scan new/recently-modified directories first; deprioritize fully-indexed stable directories.
- **Re-classification triggers**: detect when `prompt_hash` changes (prompt file was edited) and mark affected images for re-scan.
- **Optional embedding extraction**: during classification, also extract image embeddings for downstream similarity search.
- **LLM failure review UI**: add a "Failed Classifications" section to the Status window with path, raw output snippet, and a "Retry" button.

### UX and operability

- **`driftwall doctor`**: environment health checks (Ollama, model, gsettings, xrandr, ChromaDB, font).
- **First-run setup wizard**: interactive config file generation with sensible defaults.
- **Richer `status`**: unknown ratio, top moods/genres/colors, classification failure queue, last N rotation timestamps, content index stats.
- **Export/import DB metadata**: JSON or CSV export for backup and cross-machine sharing.
- **Systemd unit files in repo + install helper**: `driftwall install-service` copies units, enables timer.
- **Overlay quality controls**: min/max word count, disallow pure emoji, sentiment filter for depressing content.
- **Per-image overlay log**: store what text was generated for which image + which content chunk drove it.

---

## New creative directions

### Accent color sync

- After each rotation, extract dominant colors from the new wallpaper and optionally update GNOME accent color (`gsettings set org.gnome.desktop.interface accent-color`). Creates a unified visual environment.
- Extend to generate matching GTK theme overlays (light/dark based on wallpaper brightness).

### "Memory mode" — temporal photo clustering

- Use EXIF `DateTimeOriginal` as a first-class field (scan at classify time).
- "On this day": prefer images captured within a week-window of the current calendar date, across any year.
- "This season, past years": like Apple Photos' memories, surface cohesive temporal clusters.

### Annotated browsing and tagging UI

- Web UI or GTK dialog: thumbnail grid of all classified images with their metadata badges.
- Manual tag overrides: let users correct wrong genre/mood/season classifications.
- Inline re-classify button: re-run LLM on a specific image without re-scanning all.
- Filter/sort by any metadata field with live preview of what would be selected.

### Contextual awareness expansion

- **Weather integration**: pull current conditions (open-meteo free API, no key needed) — prefer stormy images when it's raining, bright images when sunny.
- **Calendar context**: if user provides calendar file/URL, detect meetings and suppress overlays during work blocks.
- **Music context**: optional integration with MPRIS D-Bus (what's playing) — match wallpaper mood to now-playing genre.
- **Time-since-last-rotation tracking**: if system was asleep or idle, prioritize "fresh" images to mark the new session.

### Content pipeline enhancements

- **Wikipedia article ingestion**: auto-fetch and chunk article text for images tagged with `visible_text` or location context.
- **RSS feed ingestion**: subscribe to text feeds (poems, quotes, news) and pipe into ChromaDB.
- **Content rating/scoring**: let users mark content chunks as liked/disliked; adjust future retrieval.
- **Overlay diversity controls**: configurable cooldown per author/source to avoid same author dominating.
- **Image-linked content**: manually associate specific content files with specific image tags (e.g., haiku collection always surfaces with nature images).

### Wallpaper analytics and insights

- **Rotation log export**: CSV/JSON dump of full history with image path, score, active triggers, and overlay text.
- **Selection explainability**: `driftwall explain` — show why the last image was chosen (score breakdown, active triggers, exclusion reasons).
- **"What would rotate now?" dry run**: `driftwall rotate --dry-run` — print top 5 candidates with scores without changing the wallpaper.
- **Coverage metrics**: what % of library has been shown in the last 30/90/180 days; surface unseen images.
- **Bias detector**: warn if a single folder, genre, or mood is dominating recent rotations.

### Advanced overlay experiences

- **Image-aware text placement**: analyze the image's subject position and place overlay in the least-visually-busy quadrant automatically (using the existing composition/framing metadata).
- **Overlay palette matching**: derive text/scrim color from image dominant colors rather than hardcoded white-on-dark.
- **Animated overlays**: subtle CSS opacity pulsing or type-on animation for dynamic overlays (GTK3 CSS transitions).
- **Multi-language overlays**: instruct overlay LLM to write in a configured language (or rotate through a list).
- **"Today's intent" mode**: show a single, full-width daily affirmation or goal at system startup, then dismiss.

### Distribution and packaging

- **PyPI package**: `pip install driftwall` with optional extras (`[ui]`, `[ebooks]`, `[content]`).
- **Flatpak/Snap**: bundled GTK3 app with sandboxed access to home directory.
- **AUR package**: Arch/Manjaro community package.
- **Docs site**: GitHub Pages with configuration reference, screenshot gallery, and quick-start guide.
- **Docker/Podman image**: headless mode with HTTP API for server/NAS use cases.

---

## Concrete backlog by horizon

### Next 1-2 weeks (fast wins)

- Implement `--mood` filtering/scoring properly in rotate path.
- Add `driftwall doctor` command (Ollama, model, gsettings, xrandr, ChromaDB reachability).
- Prune `wallpaper_history` to configurable max rows.
- Add systemd `.service` and `.timer` templates to repo.
- Add `driftwall rotate --dry-run` to preview candidates without switching.
- Add `classified_by_model` + `classified_at` columns and populate on new classifications.

### Next 1-2 months (core product improvement)

- Weighted scoring config in TOML (`[scoring]` section) — replace fixed +0.5 with named weights.
- User feedback commands: `like`, `skip`, `ban` — adjust per-image delta column.
- Classification provenance: model, prompt hash, classified_at per image.
- Schema migration mechanism: versioned SQL patch files, applied on DB open.
- pHash near-duplicate detection: compute at scan time, use in selection scoring.
- `driftwall explain`: score breakdown for last rotation.
- LLM failure review section in Status UI.
- Weather-aware trigger (open-meteo, no API key required).

### Next quarter (expansion + distribution)

- Desktop environment abstraction (`WallpaperProvider` interface: GNOME, KDE, sway).
- Multi-monitor support: per-display candidate selection, aspect-aware pairing.
- Local web UI: thumbnail grid, metadata viewer, manual tag overrides.
- EXIF date extraction + "on this day" memory mode.
- Accent color sync from dominant wallpaper colors (GNOME only initially).
- PyPI packaging + docs site.

---

## Suggested architecture changes

- **Split selector into layers**:
  - `candidate_query` (SQL filtering)
  - `feature_extractor` (computed features per candidate)
  - `ranker` (weighted score composition)
  - `sampler` (exploration vs exploitation policy)

- **Provider interfaces**:
  - `WallpaperProvider` (`gnome`, `plasma`, `sway`, `macos`, `windows`)
  - `ContextProvider` (time, weather, calendar, music)
  - `ModelProvider` (ollama — extensible to cloud or GGUF direct)

- **Unified positioning system**: merge static overlay quadrants (4) and dynamic overlay zones (12-grid) into a single `PositionedRegion` abstraction.

- **Event log table**: why a specific image was picked — scores, active triggers, exclusion reasons, overlay text, content chunk IDs. Powers `explain` command and analytics.

- **Plugin architecture**: long-term, allow third-party providers and triggers via entry points (e.g., `driftwall.wallpaper_providers`, `driftwall.context_providers`).

---

## Metrics to track

- Rotation success rate.
- Classification failure rate by model/prompt version.
- Unknown genre/time/season rate (quality of classification coverage).
- Repeat frequency and time-to-repeat per image.
- User feedback ratios (likes/skips/bans) over time.
- Mean selection score and diversity entropy across recent window.
- Content overlay utilization rate (% of rotations with active dynamic overlays).
- Per-source content chunk coverage (how evenly content library is drawn from).

---

## Research and experimentation tracks

- **Prompt iteration bakeoff**: compare current prompt vs tighter enum constraints on parse failure rate, unknown rate, and selection satisfaction.
- **Model tradeoff benchmarking**: 7B vs 14B vs 30B — speed, parse quality, field consistency, classification accuracy.
- **pHash threshold tuning**: find the perceptual distance cutoff that meaningfully reduces repetitiveness without excluding too much.
- **Scoring weight ablation**: baseline soft bonuses vs fully weighted contextual model — does richer scoring improve subjective quality?
- **Embedding model comparison**: nomic-embed-text vs mxbai-embed-large for content search relevance.
- **Weather correlation study**: does weather-aligned wallpaper selection increase engagement (measured via skip rate)?

---

## Security and privacy

- **Sensitive image redaction**: optional mode to suppress images with `sensitive` or `faces_present > 0` from overlays, logs, and status UI.
- **Encrypt DB at rest**: document tradeoffs; optional SQLCipher integration.
- **Harden shell integrations**: audit all subprocess calls for injection risk; use `shlex.quote` everywhere.
- **LLM failure storage security**: files in `driftwall/llm_failures/` may contain image descriptions with PII; document and optionally auto-prune.
- **Opt-in telemetry architecture**: disabled by default; if added, fully transparent and local-only (usage stats to local log only).

---

## Documentation improvements

- "How selection works" deep dive with score formula and examples.
- "How dynamic overlays work" — architecture diagram of zone system, lifetime, and ChromaDB search.
- Troubleshooting matrix: Ollama/model/timeouts/GNOME/ChromaDB common failures.
- Configuration reference: every TOML field with type, default, and example.
- Recommended config profiles by GPU tier (4GB/8GB/24GB VRAM).
- Data model reference: every DB column with meaning and valid values.
- "Getting started" tutorial: from install → first scan → first rotation → first overlay.

---

## Prioritized recommendation

If the goal is strongest momentum with least risk, prioritize:

1. **Reliability**: `doctor`, history pruning, config validation, systemd templates, classification provenance.
2. **Smarter selection**: weighted scoring config + mood filtering + feedback loop (`like`/`skip`/`ban`).
3. **Explainability**: `rotate --dry-run`, `driftwall explain`, LLM failure review UI.
4. **Content quality**: near-duplicate suppression, re-classification on prompt change, overlay diversity controls.
5. **Distribution**: PyPI packaging, docs site, cross-desktop wallpaper provider abstraction.

This sequence makes Driftwall reliable first, meaningfully smarter, observable, and then ready for broader adoption.
