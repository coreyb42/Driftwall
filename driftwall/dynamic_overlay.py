"""Floating GTK3 overlay windows for dynamic content display."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .font_selection import build_font_options, pick_font_for_context
from .overlay import register_font_with_fontconfig, resolve_font_family
from .windowing import (
    OverlayBounds,
    compute_overlay_bounds,
    configure_overlay_window_layer,
    zone_rect,
)

log = logging.getLogger(__name__)

# 4×3 grid, centre 2 cells (indices 5, 6) always excluded
# Grid layout:  col→  0    1    2    3
#          row 0:     0    1    2    3
#          row 1:     4   [5]  [6]   7
#          row 2:     8    9   10   11
_ALL_ZONES = set(range(12))
_EXCLUDED_ZONES = {5, 6}
_ELIGIBLE_ZONES = sorted(_ALL_ZONES - _EXCLUDED_ZONES)

# Zones that correspond to each static-overlay quadrant position
_QUADRANT_ZONES: dict[str, set[int]] = {
    "top-left":     {0, 1, 4},
    "top-right":    {2, 3, 7},
    "bottom-left":  {4, 8, 9},
    "bottom-right": {7, 10, 11},
}

# Internal alias kept for the rest of this module.
_zone_rect = zone_rect

# Inset between zone cells (and between work-area edge and overlay edge).
# Keeps adjacent overlays from touching and gives breathing room from panels.
_INTER_ZONE_GAP_PX = 12


class FloatingOverlay(Gtk.Window):
    """A frameless, transparent GTK window that displays a content chunk."""

    def __init__(
        self,
        text: str,
        attribution: str,
        screen_x: int,
        screen_y: int,
        max_width: int,
        max_height: int,
        font_size: int,
        font_file: str,
        on_destroyed: Callable | None = None,
        chunk=None,
        on_read: Callable | None = None,
    ) -> None:
        super().__init__()
        self._on_destroyed = on_destroyed
        self._fade_id: int | None = None
        self._target_opacity = 1.0

        self.set_decorated(False)
        configure_overlay_window_layer(self, Gdk)

        # RGBA transparency
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)

        self.connect("destroy", self._on_destroy_event)
        self.get_style_context().add_class("driftwall-overlay")

        # CSS: transparent window body + dark rounded box for content
        attr_size = max(10, int(font_size * 0.75))
        font_family = resolve_font_family(font_file)
        css_data = f"""
            window.driftwall-overlay {{
                background-color: transparent;
                background: none;
            }}
            .dw-overlay-box {{
                background-color: rgba(0, 0, 0, 0.58);
                border-radius: 8px;
                padding: 12px;
            }}
            .dw-overlay-text {{
                color: rgba(255, 255, 255, 0.95);
                font-family: "{font_family}";
                font-size: {font_size}px;
            }}
            .dw-overlay-attr {{
                color: rgba(210, 210, 210, 0.90);
                font-family: "{font_family}";
                font-size: {attr_size}px;
                font-style: italic;
            }}
            .dw-overlay-read-btn {{
                color: rgba(210, 210, 210, 0.75);
                background: transparent;
                border: none;
                padding: 0px 4px;
                font-size: 13px;
            }}
        """.encode()
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css_data)
        # Per-widget providers instead of add_provider_for_screen to avoid leaking
        # styles into unrelated app windows (settings dialog, status window, etc.)
        self.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("dw-overlay-box")
        box.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Truncate long quotes so the rendered window doesn't bleed past its
        # zone (which would visually overlap the next zone's overlay). A "more"
        # button — when chunk.drillable — opens the full text in the reader.
        chars_per_line = max(20, max_width // max(1, font_size // 2 + 1))
        line_height_px = max(1, int(font_size * 1.4))
        # Reserve ~3 lines of vertical budget for attribution + button + padding.
        budget_lines = max(3, max_height // line_height_px - 3)
        max_chars = max(80, budget_lines * chars_per_line)
        display_text = _truncate_for_display(text, max_chars)

        text_label = Gtk.Label(label=display_text)
        text_label.set_xalign(0.0)
        text_label.set_line_wrap(True)
        text_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        text_label.set_max_width_chars(chars_per_line)
        text_label.get_style_context().add_class("dw-overlay-text")
        text_label.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        text_desc = Pango.FontDescription()
        text_desc.set_family(font_family)
        text_label.override_font(text_desc)
        box.pack_start(text_label, False, False, 0)

        if attribution:
            attr_label = Gtk.Label(label=attribution)
            attr_label.set_xalign(0.0)
            attr_label.set_line_wrap(True)
            attr_label.set_max_width_chars(chars_per_line)
            attr_label.get_style_context().add_class("dw-overlay-attr")
            attr_label.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            attr_desc = Pango.FontDescription()
            attr_desc.set_family(font_family)
            attr_desc.set_style(Pango.Style.ITALIC)
            attr_label.override_font(attr_desc)
            box.pack_start(attr_label, False, False, 0)

        if chunk is not None and chunk.drillable and on_read is not None:
            btn = Gtk.Button(label="\u22ef")  # ⋯
            btn.get_style_context().add_class("dw-overlay-read-btn")
            btn.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            btn.set_halign(Gtk.Align.END)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.connect("clicked", lambda _: GLib.idle_add(on_read, chunk))
            box.pack_start(btn, False, False, 0)

        self._chunk = chunk
        self._anchor_x = screen_x
        self._anchor_y = screen_y
        self._max_w = max_width
        self._max_h = max_height
        self.add(box)
        # Let GTK natural-size the window from the wrapping labels' max_width_chars.
        # We deliberately do NOT call set_size_request: that would freeze the window
        # at the maximum allowed width, leaving lots of empty transparent space and
        # making adjacent overlays feel cramped. _clamp_to_screen below pulls the
        # window back inside its allowed bounds once GTK has computed the natural
        # size on show_all().
        self.set_resizable(False)
        self.move(screen_x, screen_y)
        self.set_opacity(0.0)

    # ── fade ─────────────────────────────────────────────────────────────────

    def fade_in(self) -> None:
        self.show_all()
        GLib.idle_add(self._clamp_to_screen)
        self._target_opacity = 1.0
        self._fade_id = GLib.timeout_add(30, self._step_fade_in)

    def _clamp_to_screen(self) -> bool:
        """After GTK natural-sizes the window, snap it back inside its allowed bounds.

        Bounds are the zone's (anchor_x, anchor_y) corner with size (max_w, max_h),
        which the manager already insets from the work area. We never let the
        window cross beyond the full screen either, as a hard backstop.
        """
        x, y = self.get_position()
        w, h = self.get_size()
        screen = self.get_screen()
        sw = screen.get_width()
        sh = screen.get_height()

        # Allowed box: anchor + max_w/max_h (assigned by manager); fall back to screen.
        ax = getattr(self, "_anchor_x", 0)
        ay = getattr(self, "_anchor_y", 0)
        mw = getattr(self, "_max_w", sw)
        mh = getattr(self, "_max_h", sh)

        # Right/bottom limits inside the zone
        zone_right = ax + max(mw, w)
        zone_bottom = ay + max(mh, h)

        new_x = max(ax, min(x, zone_right - w))
        new_y = max(ay, min(y, zone_bottom - h))
        # Hard backstop — never poke past the screen
        new_x = max(0, min(new_x, sw - w))
        new_y = max(0, min(new_y, sh - h))

        if new_x != x or new_y != y:
            log.debug(
                "Clamping overlay from (%d,%d) to (%d,%d) size=%dx%d zone=(%d,%d %dx%d)",
                x, y, new_x, new_y, w, h, ax, ay, mw, mh,
            )
            self.move(new_x, new_y)
        return False

    def _step_fade_in(self) -> bool:
        current = self.get_opacity()
        next_op = min(1.0, current + 0.05)
        self.set_opacity(next_op)
        if next_op >= self._target_opacity:
            self._fade_id = None
            return False
        return True

    def fade_out(self) -> None:
        if self._fade_id is not None:
            GLib.source_remove(self._fade_id)
        self._fade_id = GLib.timeout_add(30, self._step_fade_out)

    def _step_fade_out(self) -> bool:
        current = self.get_opacity()
        next_op = max(0.0, current - 0.05)
        self.set_opacity(next_op)
        if next_op <= 0.0:
            self._fade_id = None
            self.destroy()
            return False
        return True

    def _on_destroy_event(self, _widget: Gtk.Widget) -> None:
        if self._on_destroyed:
            self._on_destroyed()


# ── manager ───────────────────────────────────────────────────────────────────

class DynamicOverlayManager:
    """Manages spawning, timing, and teardown of FloatingOverlay windows."""

    # Number of top results to fetch from ChromaDB per spawn; randomise within this window
    _FETCH_N = 50
    # How many recently-shown chunk IDs to remember for deduplication
    _RECENT_MAXLEN = 50

    def __init__(self, config, db_path: Path) -> None:
        self._config = config
        self._db_path = db_path
        self._font_options = build_font_options(config)
        if self._font_options:
            registered = 0
            for opt in self._font_options:
                if register_font_with_fontconfig(str(opt.path)):
                    registered += 1
            log.info(
                "Dynamic overlay font preload: %d/%d fonts registered",
                registered,
                len(self._font_options),
            )
        self._current_image = None  # ImageRecord of the current wallpaper
        # (overlay, expire_time, zone, chunk)  -- chunk.id used for dedup
        self._active: list[tuple] = []
        self._occupied_zones: set[int] = set()
        self._recently_shown: deque[str] = deque(maxlen=self._RECENT_MAXLEN)
        self._fetch_in_progress = False
        self._paused = False
        self._spawn_timer_id: int | None = None
        self._expire_timer_id: int | None = None
        self._lock = threading.Lock()

        # Use the monitor work area so overlays don't overlap system panels.
        # reserved_*_px add extra inset on each edge for docks/panels that don't
        # register X11 struts properly (the GDK work area would include them).
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None
        cfg_do = config.dynamic_overlay
        if monitor:
            wa = monitor.get_workarea()
            self._work_x = wa.x + cfg_do.reserved_left_px
            self._work_y = wa.y + cfg_do.reserved_top_px
            self._screen_w = wa.width - cfg_do.reserved_left_px - cfg_do.reserved_right_px
            self._screen_h = wa.height - cfg_do.reserved_top_px - cfg_do.reserved_bottom_px
            log.debug(
                "Work area: gdk=(%d,%d %dx%d)  reserved l=%d r=%d t=%d b=%d  "
                "effective origin=(%d,%d) size=%dx%d",
                wa.x, wa.y, wa.width, wa.height,
                cfg_do.reserved_left_px, cfg_do.reserved_right_px,
                cfg_do.reserved_top_px, cfg_do.reserved_bottom_px,
                self._work_x, self._work_y, self._screen_w, self._screen_h,
            )
        else:
            self._work_x = cfg_do.reserved_left_px
            self._work_y = cfg_do.reserved_top_px
            self._screen_w = 1920 - cfg_do.reserved_left_px - cfg_do.reserved_right_px
            self._screen_h = 1052 - cfg_do.reserved_top_px - cfg_do.reserved_bottom_px
            log.warning("No primary monitor detected; falling back to 1920x1052 defaults")

        # Zones to avoid because the static text overlay appears there
        self._static_overlay_zones: set[int] = set()
        if config.overlay.enabled:
            for q in config.overlay.quadrants:
                self._static_overlay_zones |= _QUADRANT_ZONES.get(q, set())

    def start(self) -> None:
        cfg = self._config.dynamic_overlay
        self._spawn_timer_id = GLib.timeout_add_seconds(cfg.spawn_interval_seconds, self._tick)
        # Expire check runs more frequently so overlays don't linger past their lifetime
        self._expire_timer_id = GLib.timeout_add_seconds(5, self._expire_check)

    def stop(self, immediate: bool = False) -> None:
        for attr in ("_spawn_timer_id", "_expire_timer_id"):
            tid = getattr(self, attr, None)
            if tid is not None:
                GLib.source_remove(tid)
                setattr(self, attr, None)
        with self._lock:
            active = list(self._active)
        for overlay, _exp, _zone, _chunk in active:
            if immediate:
                GLib.idle_add(overlay.destroy)
            else:
                GLib.idle_add(overlay.fade_out)

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Pause spawning and fade out all active overlays."""
        with self._lock:
            self._paused = True
            active = list(self._active)
        log.debug("DynamicOverlayManager paused")
        for overlay, _exp, _zone, _chunk in active:
            GLib.idle_add(overlay.fade_out)

    def resume(self) -> None:
        """Resume spawning overlays."""
        with self._lock:
            self._paused = False
        log.debug("DynamicOverlayManager resumed")

    def set_image(self, image) -> None:
        """Record the current wallpaper image and fade out existing overlays."""
        with self._lock:
            self._current_image = image
            active = list(self._active)
        log.debug("set_image: %s", getattr(image, "path", image))
        for overlay, _exp, _zone, _chunk in active:
            GLib.idle_add(overlay.fade_out)

    def spawn_now(self) -> None:
        """Attempt one immediate spawn on the GLib loop."""
        GLib.idle_add(self._spawn_one)

    def _expire_check(self) -> bool:
        """Fade out overlays that have exceeded their lifetime. Runs every 5 seconds."""
        now = time.monotonic()
        with self._lock:
            still_active = []
            for overlay, exp, zone, chunk in self._active:
                if now >= exp:
                    GLib.idle_add(overlay.fade_out)
                    # Mark as fading (inf expire) so we don't re-trigger fade_out;
                    # keep zone occupied until _on_destroyed fires after fade completes.
                    still_active.append((overlay, float("inf"), zone, chunk))
                else:
                    still_active.append((overlay, exp, zone, chunk))
            self._active = still_active
        return True

    def _tick(self) -> bool:
        """Spawn a new overlay if below max_simultaneous. Runs every spawn_interval seconds."""
        cfg = self._config.dynamic_overlay
        with self._lock:
            n_active = len(self._active)
            no_image = self._current_image is None
            fetch_busy = self._fetch_in_progress

        log.debug("_tick: active=%d max=%d no_image=%s fetch_busy=%s paused=%s",
                  n_active, cfg.max_simultaneous, no_image, fetch_busy, self._paused)

        if n_active < cfg.max_simultaneous and not no_image and not fetch_busy and not self._paused:
            GLib.idle_add(self._spawn_one)

        return True  # keep repeating

    def _spawn_one(self) -> bool:
        """Kick off a background ChromaDB query then spawn an overlay on return."""
        cfg = self._config.dynamic_overlay
        with self._lock:
            # Re-check — multiple spawn calls may have been queued via idle_add
            if len(self._active) >= cfg.max_simultaneous:
                return False
            if self._current_image is None:
                return False
            if self._fetch_in_progress:
                return False
            if self._paused:
                return False
            self._fetch_in_progress = True
            image = self._current_image

        log.debug("_spawn_one: fetching content for image %s", getattr(image, "path", image))

        def _fetch() -> None:
            from .content_search import get_content_for_image
            try:
                chunks = get_content_for_image(
                    image,
                    self._config.resolved_chroma_path,
                    self._config,
                    n_results=self._FETCH_N,
                )
                log.debug("_fetch: got %d chunks from ChromaDB", len(chunks))
            except Exception as e:
                log.warning("Content fetch failed: %s", e)
                chunks = []
            GLib.idle_add(self._do_spawn, chunks)

        threading.Thread(target=_fetch, daemon=True).start()
        return False

    def _do_spawn(self, chunks: list) -> bool:
        """Called on the GLib main thread with fresh ChromaDB results."""
        cfg = self._config.dynamic_overlay
        with self._lock:
            self._fetch_in_progress = False

            if len(self._active) >= cfg.max_simultaneous:
                return False
            if not chunks:
                log.debug("_do_spawn: no chunks returned")
                return False

            # IDs to exclude: currently displayed + recently shown
            active_ids = {ch.id for _, _, _, ch in self._active}
            recently = set(self._recently_shown)
            candidates = [c for c in chunks if c.id not in active_ids and c.id not in recently]
            if not candidates:
                # Library is small — fall back to excluding only the active ones
                log.debug("_do_spawn: all candidates recently shown, relaxing dedup")
                candidates = [c for c in chunks if c.id not in active_ids]
            if not candidates:
                log.debug("_do_spawn: no candidates after filtering")
                return False

            # Source-diversity selection: group candidates by source file, pick a
            # random source (each source gets equal weight regardless of chunk count),
            # then pick the best-ranked chunk from that source. This prevents any
            # single book from dominating even when it has strong semantic similarity
            # to the current image. Falls back to pure random if grouping fails.
            by_source: dict[str, list] = {}
            for c in candidates:
                by_source.setdefault(c.source_path, []).append(c)
            chosen_source = random.choice(list(by_source.keys()))
            source_pool = by_source[chosen_source][:5]  # top-5 from chosen source
            chunk = random.choice(source_pool)
            log.debug("_do_spawn: chose source '%s' (%d sources available)",
                      chosen_source.split("/")[-1], len(by_source))

            excluded_zones = self._occupied_zones | self._static_overlay_zones
            free_zones = [z for z in _ELIGIBLE_ZONES if z not in excluded_zones]
            if not free_zones:
                log.debug("_do_spawn: no free zones")
                return False

            zone = random.choice(free_zones)
            self._occupied_zones.add(zone)
            self._recently_shown.append(chunk.id)

        log.debug("_do_spawn: spawning '%s…' in zone %d", chunk.text[:40], zone)

        # Bounds: a zone-cell rectangle inside the work area, inset on every
        # edge so adjacent zones never share a pixel. The window is then
        # natural-sized inside this rectangle and clamped before fading in.
        bounds = compute_overlay_bounds(
            zone=zone,
            work_x=self._work_x,
            work_y=self._work_y,
            work_w=self._screen_w,
            work_h=self._screen_h,
            gap_px=_INTER_ZONE_GAP_PX,
        )
        max_w = bounds.max_w
        max_h = bounds.max_h
        screen_x = bounds.x
        screen_y = bounds.y

        attribution = _format_attribution(chunk)

        # Gently dampen font sizes that are significantly above the typical baseline.
        # This reduces right-edge overflow without changing normal-sized fonts at all.
        _FONT_BASELINE_PX = 18
        font_size = cfg.font_size
        if font_size > int(_FONT_BASELINE_PX * 1.5):  # > 27 px
            font_size = int(_FONT_BASELINE_PX + (font_size - _FONT_BASELINE_PX) * 0.65)
            log.debug("Font size dampened from %d to %d px", cfg.font_size, font_size)

        font_file = ""
        if self._font_options:
            try:
                chosen_font = pick_font_for_context(
                    options=self._font_options,
                    context=f"{chunk.text}\n{attribution}".strip(),
                    purpose="dynamic content overlay",
                    model=self._config.overlay.model or self._config.ollama.model,
                    host=self._config.ollama.host,
                )
                font_file = str(chosen_font)
                log.debug("Dynamic overlay font selected: %s", font_file)
            except Exception as e:
                log.warning("Dynamic font selection failed: %s", e)

        def _on_destroyed() -> None:
            with self._lock:
                self._occupied_zones.discard(zone)
                self._active = [(o, e, z, c) for o, e, z, c in self._active if z != zone]

        overlay = FloatingOverlay(
            text=chunk.text,
            attribution=attribution,
            screen_x=screen_x,
            screen_y=screen_y,
            max_width=max_w,
            max_height=max_h,
            font_size=font_size,
            font_file=font_file,
            on_destroyed=_on_destroyed,
            chunk=chunk,
            on_read=self._open_reader,
        )

        lifetime = random.randint(cfg.min_lifetime_seconds, cfg.max_lifetime_seconds)
        expire_time = time.monotonic() + lifetime

        with self._lock:
            self._active.append((overlay, expire_time, zone, chunk))

        overlay.fade_in()
        return False

    def _open_reader(self, chunk) -> bool:
        """Open a ReaderWindow for the given chunk. Called on the GLib main thread."""
        from .reader_window import ReaderWindow
        win = ReaderWindow(chunk, self._config)
        win.show_all()
        return False


def _truncate_for_display(text: str, max_chars: int) -> str:
    """Trim ``text`` to ~``max_chars`` characters, breaking on word boundary."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    # Only break on whitespace if it doesn't strand too much of the budget
    if last_space > int(max_chars * 0.7):
        truncated = truncated[:last_space]
    return truncated.rstrip(" ,.;:—-") + "…"


def _format_attribution(chunk) -> str:
    """Format an attribution line for a ContentChunk."""
    if chunk.source_type == "quote":
        author = chunk.metadata.get("author", "")
        source = chunk.metadata.get("source", "")
        parts = []
        if author:
            parts.append(f"— {author}")
        if source:
            parts.append(source)
        return ", ".join(parts)
    else:
        title = chunk.metadata.get("source_title", "")
        return f"— {title}" if title else ""
