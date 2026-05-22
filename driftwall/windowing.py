"""Window-layer + overlay-geometry helpers (no GTK dependency).

The geometry helpers live here (rather than in dynamic_overlay) so unit tests
can import them without `gi`/GTK bindings being installed in the venv.
"""

from __future__ import annotations

from dataclasses import dataclass


def configure_overlay_window_layer(window, gdk_module) -> None:
    """Put an overlay window behind normal application windows."""
    type_hint = getattr(gdk_module.WindowTypeHint, "DESKTOP", gdk_module.WindowTypeHint.NORMAL)
    window.set_type_hint(type_hint)
    window.set_keep_below(True)
    window.set_skip_taskbar_hint(True)
    window.set_skip_pager_hint(True)
    window.set_accept_focus(False)
    window.stick()


def zone_rect(zone: int, screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
    """Return (x, y, w, h) for a zone cell in a 4-col × 3-row grid (zone-local coords)."""
    col = zone % 4
    row = zone // 4
    cell_w = screen_w // 4
    cell_h = screen_h // 3
    return col * cell_w, row * cell_h, cell_w, cell_h


@dataclass(frozen=True)
class OverlayBounds:
    """Allowed bounding box for an overlay window inside the work area."""

    x: int
    y: int
    max_w: int
    max_h: int


def compute_overlay_bounds(
    zone: int,
    work_x: int,
    work_y: int,
    work_w: int,
    work_h: int,
    gap_px: int = 10,
) -> OverlayBounds:
    """Compute an overlay's allowed placement rect for a zone.

    The returned box is fully inside (work_x, work_y, work_w, work_h) and inset
    by ``gap_px`` on every side of the zone cell so adjacent zones never share
    a pixel. The window is anchored to the inset corner — width/height are
    upper bounds; the actual GTK window may be smaller (natural-sized).
    """
    zx, zy, zw, zh = zone_rect(zone, work_w, work_h)
    inset = max(0, gap_px)
    inner_x = work_x + zx + inset
    inner_y = work_y + zy + inset
    inner_w = max(0, zw - 2 * inset)
    inner_h = max(0, zh - 2 * inset)
    return OverlayBounds(x=inner_x, y=inner_y, max_w=inner_w, max_h=inner_h)
