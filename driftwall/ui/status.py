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
        self._config = config

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

        from driftwall.db import get_stats, get_content_stats
        stats = get_stats(self._db_path)
        content_stats = get_content_stats(self._db_path)

        # ── Images ────────────────────────────────────────────────────────────
        section = Gtk.Label(xalign=0.0)
        section.set_markup("<b>Images</b>")
        self._content.pack_start(section, False, False, 0)

        img_grid = Gtk.Grid(row_spacing=2, column_spacing=16)
        img_grid.set_margin_start(16)
        img_grid.attach(Gtk.Label(label="Total classified", xalign=0.0), 0, 0, 1, 1)
        img_grid.attach(Gtk.Label(label=str(stats["total_images"]), xalign=1.0), 1, 0, 1, 1)
        img_grid.attach(Gtk.Label(label="Total shown", xalign=0.0), 0, 1, 1, 1)
        img_grid.attach(Gtk.Label(label=str(stats["total_shown"]), xalign=1.0), 1, 1, 1, 1)
        self._content.pack_start(img_grid, False, False, 0)

        genre_label = Gtk.Label(label="Genre breakdown:", xalign=0.0)
        genre_label.set_margin_top(6)
        self._content.pack_start(genre_label, False, False, 0)

        grid = Gtk.Grid(row_spacing=2, column_spacing=16)
        grid.set_margin_start(16)
        for row_idx, (genre, count) in enumerate(stats["genre_counts"].items()):
            grid.attach(Gtk.Label(label=genre or "unknown", xalign=0.0), 0, row_idx, 1, 1)
            grid.attach(Gtk.Label(label=str(count), xalign=1.0), 1, row_idx, 1, 1)
        self._content.pack_start(grid, False, False, 0)

        last_label = Gtk.Label(label="Last 5 wallpapers:", xalign=0.0)
        last_label.set_margin_top(6)
        self._content.pack_start(last_label, False, False, 0)

        for entry in stats["last_shown"]:
            ts = entry["shown_at"][:19]
            name = Path(entry["path"]).name
            lbl = Gtk.Label(label=f"  {ts}  {name}", xalign=0.0)
            self._content.pack_start(lbl, False, False, 0)

        # ── Content ───────────────────────────────────────────────────────────
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        sep.set_margin_bottom(4)
        self._content.pack_start(sep, False, False, 0)

        content_section = Gtk.Label(xalign=0.0)
        content_section.set_markup("<b>Content</b>")
        self._content.pack_start(content_section, False, False, 0)

        ct_grid = Gtk.Grid(row_spacing=2, column_spacing=16)
        ct_grid.set_margin_start(16)
        ct_grid.attach(Gtk.Label(label="Indexed files", xalign=0.0), 0, 0, 1, 1)
        ct_grid.attach(Gtk.Label(label=str(content_stats["total_sources"]), xalign=1.0), 1, 0, 1, 1)
        ct_grid.attach(Gtk.Label(label="Total chunks", xalign=0.0), 0, 1, 1, 1)
        ct_grid.attach(Gtk.Label(label=str(content_stats["total_chunks"]), xalign=1.0), 1, 1, 1, 1)
        self._content.pack_start(ct_grid, False, False, 0)

        if content_stats["sources"]:
            sources_label = Gtk.Label(label="Indexed files:", xalign=0.0)
            sources_label.set_margin_top(6)
            self._content.pack_start(sources_label, False, False, 0)

            src_grid = Gtk.Grid(row_spacing=2, column_spacing=16)
            src_grid.set_margin_start(16)
            for row_idx, src in enumerate(content_stats["sources"]):
                name = Path(src["source_path"]).name
                ts = src["indexed_at"][:10]
                chunks = src["chunk_count"]
                src_grid.attach(Gtk.Label(label=name, xalign=0.0), 0, row_idx, 1, 1)
                src_grid.attach(
                    Gtk.Label(label=f"{chunks} chunks", xalign=1.0), 1, row_idx, 1, 1
                )
                src_grid.attach(Gtk.Label(label=ts, xalign=0.0), 2, row_idx, 1, 1)
            self._content.pack_start(src_grid, False, False, 0)
        elif not self._config.content.enabled:
            hint = Gtk.Label(xalign=0.0)
            hint.set_markup("<small><i>Content ingestion is disabled in settings.</i></small>")
            hint.set_margin_start(16)
            self._content.pack_start(hint, False, False, 0)
        else:
            hint = Gtk.Label(xalign=0.0)
            hint.set_markup("<small><i>No content indexed yet — use Scan → Content.</i></small>")
            hint.set_margin_start(16)
            self._content.pack_start(hint, False, False, 0)

        # ── Scan logs ─────────────────────────────────────────────────────────
        _log_dir = Path.home() / ".local" / "share" / "driftwall"
        log_entries = [
            ("View last image scan log", "scan-images.log"),
            ("View last content scan log", "scan-content.log"),
        ]
        existing_logs = [(lbl, _log_dir / name) for lbl, name in log_entries
                         if (_log_dir / name).exists()]
        if existing_logs:
            sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep2.set_margin_top(8)
            sep2.set_margin_bottom(4)
            self._content.pack_start(sep2, False, False, 0)
            for label_text, log_path in existing_logs:
                btn = Gtk.Button(label=label_text)
                btn.connect("clicked", lambda _, p=log_path: self._show_log_dialog(p))
                self._content.pack_start(btn, False, False, 0)

        self._content.show_all()

    def _show_log_dialog(self, log_path: Path) -> None:
        dialog = Gtk.Dialog(title=log_path.name, transient_for=self, flags=0)
        dialog.set_default_size(720, 500)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_monospace(True)
        textview.set_wrap_mode(Gtk.WrapMode.NONE)
        textview.set_left_margin(6)
        textview.set_top_margin(6)

        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            text = f"Cannot read log file: {e}"

        textview.get_buffer().set_text(text)
        scrolled.add(textview)

        box = dialog.get_content_area()
        box.set_border_width(8)
        box.pack_start(scrolled, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()
