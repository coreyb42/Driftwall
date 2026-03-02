# Driftwall Next Steps Brainstorming

## Snapshot: What the app is today

Driftwall is already a functional local-first pipeline with:
- A one-time image scanner/classifier using a local Ollama vision model.
- A rich SQLite schema for image metadata (content, aesthetic, quality, privacy, scene).
- A wallpaper selector that combines hard filters, recency avoidance, and soft contextual scoring.
- GNOME wallpaper setting and an optional generated text overlay.
- A CLI that supports scan/rotate/daemon/status/config.

This means the project has strong foundations in data modeling and practical automation, but it is still pre-polish and pre-distribution.

## Current strengths to preserve

- Local-first architecture: private and offline-friendly.
- Incremental scan by file hash: resilient to moves/renames.
- Good metadata depth: future features can be unlocked without schema redesign.
- Soft trigger design: avoids brittle “hard only” filtering.
- Simple operational model: SQLite + CLI lowers friction.

## Current constraints and risks

- No automated test suite yet; regressions are likely as feature surface grows.
- Scoring logic is very shallow (+0.5 bonuses only), leaving selection quality under-optimized.
- Trigger context only includes local hour/month; no weather/calendar/activity context yet.
- GNOME-only setter and no first-class systemd integration in repo.
- Overlay pipeline depends on model quality and can introduce noisy UX.
- Limited observability (no per-image confidence, no evaluation metrics, no benchmark harness).
- Mood CLI arg currently doesn’t implement meaningful behavior (placeholder in rotate path).
- No explicit migration/versioning strategy beyond `CREATE IF NOT EXISTS`.

## Product directions

### 1) “Daily companion” personalization

Goal: make wallpaper choices feel intentional and emotionally coherent.

Ideas:
- Preference profile: preferred genres/moods/colors by weekday/time block.
- “Energy mode” presets: calm, focus, vibrant, cozy.
- Context packs: work hours vs evening vs weekend behavior.
- User feedback loop: like/dislike/skip commands to retrain scoring weights.
- “Never show again” and temporary snooze tags.

### 2) Curation and collection management

Goal: move from rotator to photo curation assistant.

Ideas:
- Auto-album generation from metadata (e.g., winter landscapes, golden hour portraits).
- Quality cleanup workflows: identify low-quality, duplicates, near-duplicates.
- Smart pruning recommendations (unknown/low-confidence/redundant images).
- “Best-of this month” and “rediscover old photos” rotation modes.

### 3) Creative overlay/ambient experience

Goal: make wallpaper feel like ambient art, not just a random image.

Ideas:
- Overlay templates: haiku, quote, one-line reflection, title card.
- Style themes (minimal, cinematic, typewriter, postcard).
- Multi-line adaptive typography with stronger guardrails.
- Optional metadata overlay mode (location/time/genre/mood).
- “Silent mode” schedules to disable overlay at work hours.

### 4) Platform expansion

Goal: increase usage by reducing platform constraints.

Ideas:
- KDE Plasma and sway/hyprland wallpaper adapters.
- macOS and Windows adapters behind provider interfaces.
- Headless/server mode with API for remote clients.
- Multi-monitor strategies: per-display selection and aspect-aware pairing.

## Technical roadmap (high-impact)

### Foundation: quality and reliability

- Add tests for:
  - JSON extraction/sanitization edge cases.
  - Selection query builder combinations.
  - Trigger mapping boundaries (hour/month).
  - DB upsert/path-move/history behavior.
- Add static checks/linting in CI.
- Add schema migration mechanism (Alembic-like approach for SQLite or SQL migration files).
- Add safer daemon behavior (jitter, lockfile, crash backoff, structured logs).

### Selection engine evolution

- Replace fixed +0.5 scoring with weighted features.
- Support user-configurable weights in TOML.
- Introduce exploration vs exploitation (occasionally surface unseen content).
- Add confidence-aware selection (deprioritize low-confidence classifications).
- Add duplicate/near-duplicate suppression to reduce repetitiveness.

### Classification pipeline upgrades

- Store model/version/prompt hash per classification for traceability.
- Add retry policy + fallback model for malformed responses.
- Batch scheduling: prioritize new/changed/high-value folders first.
- Add optional embedding extraction for semantic search and clustering.
- Add confidence or self-rating fields from model output template.

### UX and operability

- `driftwall doctor` command for environment checks (Ollama, DB, gsettings, xrandr).
- First-run interactive setup command.
- Better `status`: show unknown ratio, top moods/colors, failed-classification queue.
- Export/import DB metadata (for backup and sharing across machines).
- Systemd user unit templates in repo with install helper.

## Concrete backlog ideas by horizon

## Next 1-2 weeks (fast wins)

- Implement mood filtering/scoring properly in rotate path.
- Add unit tests for selector/triggers/classifier parser.
- Add `driftwall doctor` command.
- Improve status report with coverage/quality stats.
- Add systemd service/timer example files.

## Next 1-2 months (core product improvement)

- Weighted scoring config + feedback signals (`like`, `skip`, `ban`).
- Classification provenance fields (model, prompt hash, classified version).
- Migration/version management for DB schema.
- Add near-duplicate detection and suppression.
- Introduce weather/timezone-aware contextual triggers.

## Next quarter (expansion)

- Desktop environment abstraction for non-GNOME support.
- Optional small local web UI for browsing/tagging/explaining choices.
- Semantic search and “playlist” modes using embeddings.
- Public packaging/distribution (PyPI + distro package + docs site).

## Suggested architecture changes

- Split selector into:
  - `candidate_query` (SQL filtering)
  - `feature_extractor` (computed features)
  - `ranker` (weighted score)
  - `sampler` (randomization policy)
- Add provider interfaces:
  - Wallpaper provider (`gnome`, `plasma`, etc.)
  - Context provider (time, weather, calendar)
  - Model provider (ollama now, extensible later)
- Add event log table for explainability:
  - why a specific image was picked (scores + active triggers + excluded reasons).

## Metrics to track

- Rotation success rate.
- Classification failure rate by model/prompt.
- Unknown genre/time/season rate.
- Repeat frequency and time-to-repeat.
- User feedback ratios (likes/skips/bans).
- Mean selection score and entropy/diversity over time.

## Research and experimentation tracks

- Prompt iteration bakeoff:
  - Compare current prompt vs tighter enum constraints.
  - Measure parse failure, unknown rate, and selection satisfaction.
- Model tradeoff benchmarking:
  - 8B vs 30B on speed, parse quality, and metadata consistency.
- Scoring AB tests:
  - Baseline soft bonuses vs weighted contextual model.

## Security and privacy opportunities

- Optional redaction mode for sensitive images in overlays/logs.
- Encrypt DB at rest option (document tradeoffs and support boundaries).
- Add opt-in telemetry architecture (disabled by default).
- Harden shell command integrations and error surfaces.

## Documentation improvements

- Add “How selection works” deep dive with examples.
- Add troubleshooting matrix for Ollama/model/timeouts/GNOME issues.
- Publish recommended config profiles by GPU tier.
- Include data model reference for each metadata field.

## Prioritized recommendation

If the goal is strongest momentum with least risk, prioritize:
1. Test coverage + `doctor` + systemd templates.
2. Scoring engine upgrade + mood/favorites feedback loop.
3. Classification provenance + migration/versioning.
4. Cross-desktop wallpaper provider abstraction.

This sequence makes Driftwall reliable first, then meaningfully smarter, then ready for broader adoption.
