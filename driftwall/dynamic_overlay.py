"""Floating GTK3 overlay windows for dynamic content display."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

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


def _zone_rect(zone: int, screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
    """Return (x, y, w, h) for a zone cell in a 4-col × 3-row grid."""
    col = zone % 4
    row = zone // 4
    cell_w = screen_w // 4
    cell_h = screen_h // 3
    return col * cell_w, row * cell_h, cell_w, cell_h


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
    ) -> None:
        super().__init__()
        self._on_destroyed = on_destroyed
        self._fade_id: int | None = None
        self._relower_id: int | None = None
        self._target_opacity = 1.0

        self.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        # Do NOT use set_keep_below() — on Mutter/GNOME it pushes windows below
        # the desktop compositor layer, making them invisible. Instead we call
        # gdk_win.lower() in fade_in() after the window is realized, which sends
        # XLowerWindow and places the overlay at the bottom of the normal stack
        # (above the desktop, below other application windows).
        self.stick()

        # RGBA transparency
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)

        self.connect("destroy", self._on_destroy_event)
        self.get_style_context().add_class("driftwall-overlay")

        # CSS: transparent window body + dark rounded box for content
        attr_size = max(10, int(font_size * 0.75))
        font_family = Path(font_file).stem if font_file else "Sans"
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
                font-family: {font_family};
                font-size: {font_size}px;
            }}
            .dw-overlay-attr {{
                color: rgba(210, 210, 210, 0.90);
                font-family: {font_family};
                font-size: {attr_size}px;
                font-style: italic;
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

        text_label = Gtk.Label(label=text)
        text_label.set_xalign(0.0)
        text_label.set_line_wrap(True)
        text_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        # width_chars gives GTK a reference width so height-for-width works correctly
        chars_per_line = max(20, max_width // max(1, font_size // 2 + 1))
        text_label.set_max_width_chars(chars_per_line)
        text_label.get_style_context().add_class("dw-overlay-text")
        text_label.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box.pack_start(text_label, False, False, 0)

        if attribution:
            attr_label = Gtk.Label(label=attribution)
            attr_label.set_xalign(0.0)
            attr_label.set_line_wrap(True)
            attr_label.set_max_width_chars(chars_per_line)
            attr_label.get_style_context().add_class("dw-overlay-attr")
            attr_label.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            box.pack_start(attr_label, False, False, 0)

        self.add(box)
        # set_size_request fixes the width; set_resizable(False) lets GTK compute
        # natural height correctly via height-for-width on the wrapping labels.
        self.set_size_request(max_width, -1)
        self.set_resizable(False)
        self.move(screen_x, screen_y)
        self.set_opacity(0.0)

    # ── fade ─────────────────────────────────────────────────────────────────

    def fade_in(self) -> None:
        self.show_all()
        # Lower to bottom of normal window stack on initial show, then keep re-lowering
        # so the overlay stays below any window raised after us. gdk_win.lower() is a
        # one-shot XLowerWindow call; without the periodic re-lower, raising any other
        # window leaves our overlay above it until the next explicit lower() call.
        gdk_win = self.get_window()
        if gdk_win:
            gdk_win.lower()
        self._relower_id = GLib.timeout_add(1500, self._relower)
        self._target_opacity = 1.0
        self._fade_id = GLib.timeout_add(30, self._step_fade_in)

    def _relower(self) -> bool:
        gdk_win = self.get_window()
        if gdk_win:
            gdk_win.lower()
            return True
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
        if self._relower_id is not None:
            GLib.source_remove(self._relower_id)
            self._relower_id = None
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
        self._current_image = None  # ImageRecord of the current wallpaper
        # (overlay, expire_time, zone, chunk_id)
        self._active: list[tuple[FloatingOverlay, float, int, str]] = []
        self._occupied_zones: set[int] = set()
        self._recently_shown: deque[str] = deque(maxlen=self._RECENT_MAXLEN)
        self._fetch_in_progress = False
        self._spawn_timer_id: int | None = None
        self._expire_timer_id: int | None = None
        self._lock = threading.Lock()

        # Use the monitor work area so overlays don't overlap system panels
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None
        if monitor:
            wa = monitor.get_workarea()
            self._work_x = wa.x
            self._work_y = wa.y
            self._screen_w = wa.width
            self._screen_h = wa.height
        else:
            self._work_x = 0
            self._work_y = 0
            self._screen_w = 1920
            self._screen_h = 1052

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

    def stop(self) -> None:
        for attr in ("_spawn_timer_id", "_expire_timer_id"):
            tid = getattr(self, attr, None)
            if tid is not None:
                GLib.source_remove(tid)
                setattr(self, attr, None)
        with self._lock:
            active = list(self._active)
        for overlay, _exp, _zone, _cid in active:
            GLib.idle_add(overlay.fade_out)

    def set_image(self, image) -> None:
        """Record the current wallpaper image and fade out existing overlays."""
        with self._lock:
            self._current_image = image
            active = list(self._active)
        log.debug("set_image: %s", getattr(image, "path", image))
        for overlay, _exp, _zone, _cid in active:
            GLib.idle_add(overlay.fade_out)

    def _expire_check(self) -> bool:
        """Fade out overlays that have exceeded their lifetime. Runs every 5 seconds."""
        now = time.monotonic()
        with self._lock:
            still_active = []
            for overlay, exp, zone, cid in self._active:
                if now >= exp:
                    GLib.idle_add(overlay.fade_out)
                    self._occupied_zones.discard(zone)
                else:
                    still_active.append((overlay, exp, zone, cid))
            self._active = still_active
        return True

    def _tick(self) -> bool:
        """Spawn a new overlay if below max_simultaneous. Runs every spawn_interval seconds."""
        cfg = self._config.dynamic_overlay
        with self._lock:
            n_active = len(self._active)
            no_image = self._current_image is None
            fetch_busy = self._fetch_in_progress

        log.debug("_tick: active=%d max=%d no_image=%s fetch_busy=%s",
                  n_active, cfg.max_simultaneous, no_image, fetch_busy)

        if n_active < cfg.max_simultaneous and not no_image and not fetch_busy:
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
            active_ids = {cid for _, _, _, cid in self._active}
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

        zx, zy, zw, zh = _zone_rect(zone, self._screen_w, self._screen_h)
        # Shift zone coordinates into the work area (accounts for top/side panels)
        zx += self._work_x
        zy += self._work_y
        max_w = int(self._screen_w * cfg.max_screen_fraction * 4)  # reasonable max
        max_h = int(self._screen_h * cfg.max_screen_fraction * 4)
        max_w = max(200, min(max_w, zw - 20))
        max_h = max(100, min(max_h, zh - 20))

        # Random offset within zone
        ox = random.randint(0, max(0, zw - max_w - 10))
        oy = random.randint(0, max(0, zh - max_h - 10))

        attribution = _format_attribution(chunk)

        chunk_id = chunk.id

        def _on_destroyed() -> None:
            with self._lock:
                self._occupied_zones.discard(zone)
                self._active = [(o, e, z, c) for o, e, z, c in self._active if z != zone]

        overlay = FloatingOverlay(
            text=chunk.text,
            attribution=attribution,
            screen_x=zx + ox,
            screen_y=zy + oy,
            max_width=max_w,
            max_height=max_h,
            font_size=cfg.font_size,
            font_file=cfg.font_file,
            on_destroyed=_on_destroyed,
        )

        lifetime = random.randint(cfg.min_lifetime_seconds, cfg.max_lifetime_seconds)
        expire_time = time.monotonic() + lifetime

        with self._lock:
            self._active.append((overlay, expire_time, zone, chunk_id))

        overlay.fade_in()
        return False


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
