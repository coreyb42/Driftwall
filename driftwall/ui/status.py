"""Status window — shows DB statistics and recent wallpaper history."""

from __future__ import annotations

from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class StatusWindow(Gtk.Window):
    def __init__(self, config_path: str | None = None) -> None:
        super().__init__(title="Driftwall Status")
        self.set_default_size(500, 400)
        self.set_border_width(12)
        self.connect("destroy", lambda _: self.destroy())

        from driftwall.config import load_config
        config = load_config(Path(config_path) if config_path else None)
        self._db_path = config.resolved_db_path

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(outer)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scrolled, True, True, 0)

        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._content.set_border_width(4)
        scrolled.add(self._content)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda _: self._refresh())
        outer.pack_start(refresh_btn, False, False, 0)

        self._refresh()

    def _refresh(self) -> None:
        for child in self._content.get_children():
            self._content.remove(child)

        if not self._db_path.exists():
            self._content.pack_start(
                Gtk.Label(
                    label=f"No database at:\n{self._db_path}\n\nRun 'driftwall scan' first.",
                    xalign=0.0,
                ),
                True, True, 0,
            )
            self._content.show_all()
            return

        from driftwall.db import get_stats
        stats = get_stats(self._db_path)

        self._content.pack_start(
            Gtk.Label(label=f"Total images: {stats['total_images']}", xalign=0.0),
            False, False, 0,
        )
        self._content.pack_start(
            Gtk.Label(label=f"Total shown:  {stats['total_shown']}", xalign=0.0),
            False, False, 0,
        )

        genre_label = Gtk.Label(label="Genre breakdown:", xalign=0.0)
        genre_label.set_margin_top(8)
        self._content.pack_start(genre_label, False, False, 0)

        grid = Gtk.Grid(row_spacing=2, column_spacing=16)
        grid.set_margin_start(16)
        for row_idx, (genre, count) in enumerate(stats["genre_counts"].items()):
            grid.attach(Gtk.Label(label=genre or "unknown", xalign=0.0), 0, row_idx, 1, 1)
            grid.attach(Gtk.Label(label=str(count), xalign=1.0), 1, row_idx, 1, 1)
        self._content.pack_start(grid, False, False, 0)

        last_label = Gtk.Label(label="Last 5 wallpapers:", xalign=0.0)
        last_label.set_margin_top(8)
        self._content.pack_start(last_label, False, False, 0)

        for entry in stats["last_shown"]:
            ts = entry["shown_at"][:19]
            name = Path(entry["path"]).name
            lbl = Gtk.Label(label=f"  {ts}  {name}", xalign=0.0)
            self._content.pack_start(lbl, False, False, 0)

        self._content.show_all()
