"""Fetch dialog — download artworks from external sources via the tray UI."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

log = logging.getLogger(__name__)

_SOURCES = ["met"]


def _row(label_text: str, widget: Gtk.Widget, label_width: int = 20) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    label = Gtk.Label(label=label_text, xalign=1.0)
    label.set_width_chars(label_width)
    box.pack_start(label, False, False, 0)
    box.pack_start(widget, True, True, 0)
    return box


class FetchDialog(Gtk.Dialog):
    """Dialog for fetching artworks from external art APIs."""

    def __init__(
        self,
        config_path: str | None = None,
        driftwall_bin: str = "driftwall",
    ) -> None:
        super().__init__(title="Fetch Artworks", modal=True)
        self.set_default_size(560, 500)

        self._config_path = config_path
        self._driftwall_bin = driftwall_bin
        self._fetch_running = False
        self._proc: subprocess.Popen | None = None

        # Load config for defaults
        self._default_output_dir = self._resolve_default_output_dir()

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_border_width(12)

        self._build_form(content)
        self._build_progress(content)
        self._build_path_label(content)

        self._fetch_btn = self.add_button("Start Fetch", Gtk.ResponseType.APPLY)
        self._fetch_btn.get_style_context().add_class("suggested-action")
        self._fetch_btn.connect("clicked", self._on_fetch)

        self._close_btn = self.add_button("Close", Gtk.ResponseType.CLOSE)
        self._close_btn.connect("clicked", lambda _: self._on_close())
        self.connect("delete-event", self._on_delete)

        content.show_all()
        self._update_path_label()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _resolve_default_output_dir(self) -> Path:
        try:
            from driftwall.config import load_config
            cfg = load_config(Path(self._config_path) if self._config_path else None)
            return cfg.download.output_dir
        except Exception:
            return Path.home() / "Pictures" / "driftwall-downloads"

    def _compute_output_dir(self) -> Path:
        from driftwall.downloader import met_output_subdir
        base = Path(self._output_dir_btn.get_filename() or str(self._default_output_dir))
        dept_text = self._dept_entry.get_text().strip()
        dept_id = int(dept_text) if dept_text.isdigit() else None
        search = self._search_entry.get_text().strip() or None
        return met_output_subdir(base, department_id=dept_id, search_query=search)

    # ── UI builders ───────────────────────────────────────────────────────────

    def _build_form(self, parent: Gtk.Box) -> None:
        # Search query
        self._search_entry = Gtk.Entry()
        self._search_entry.set_placeholder_text("e.g. landscape, impressionism…")
        self._search_entry.connect("changed", lambda _: self._update_path_label())
        parent.pack_start(_row("Search query", self._search_entry), False, False, 0)

        # Department ID
        self._dept_entry = Gtk.Entry()
        self._dept_entry.set_placeholder_text("numeric ID  (leave blank for all)")
        self._dept_entry.set_max_length(6)
        self._dept_entry.connect("changed", lambda _: self._update_path_label())
        dept_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        dept_box.pack_start(self._dept_entry, True, True, 0)
        list_btn = Gtk.Button(label="List departments")
        list_btn.connect("clicked", self._on_list_departments)
        dept_box.pack_start(list_btn, False, False, 0)
        parent.pack_start(_row("Department ID", dept_box), False, False, 0)

        # Limit
        adj = Gtk.Adjustment(value=50, lower=1, upper=5000, step_increment=10, page_increment=50)
        self._limit_spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        self._limit_spin.set_numeric(True)
        parent.pack_start(_row("Limit (images)", self._limit_spin), False, False, 0)

        # Output dir override
        self._output_dir_btn = Gtk.FileChooserButton(
            title="Select output directory",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        self._default_output_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir_btn.set_filename(str(self._default_output_dir))
        self._output_dir_btn.connect("file-set", lambda _: self._update_path_label())
        parent.pack_start(_row("Base output dir", self._output_dir_btn), False, False, 0)

    def _build_path_label(self, parent: Gtk.Box) -> None:
        self._path_label = Gtk.Label(xalign=0.0)
        self._path_label.set_line_wrap(True)
        self._path_label.set_selectable(True)
        parent.pack_start(self._path_label, False, False, 0)

    def _build_progress(self, parent: Gtk.Box) -> None:
        frame = Gtk.Frame(label="Progress")
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(200)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._log_buf = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self._log_buf)
        log_view.set_editable(False)
        log_view.set_cursor_visible(False)
        log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll.add(log_view)
        frame.add(scroll)
        parent.pack_start(frame, True, True, 0)
        self._log_scroll = scroll

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _update_path_label(self) -> None:
        try:
            path = self._compute_output_dir()
            self._path_label.set_markup(
                f"<small>Will save to: <tt>{path}</tt></small>"
            )
        except Exception:
            self._path_label.set_text("")

    def _on_list_departments(self, _btn: Gtk.Button) -> None:
        self._log("Fetching department list…\n")
        self._set_ui_sensitive(False)

        def _run() -> None:
            cmd = [self._driftwall_bin]
            if self._config_path:
                cmd += ["--config", self._config_path]
            cmd += ["fetch", "--list-departments"]
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
                )
                assert proc.stdout
                for line in proc.stdout:
                    GLib.idle_add(self._log, line)
                proc.wait()
            except Exception as e:
                GLib.idle_add(self._log, f"Error: {e}\n")
            finally:
                GLib.idle_add(self._set_ui_sensitive, True)

        threading.Thread(target=_run, daemon=True).start()

    def _cancel_fetch(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._log("\nFetch cancelled.\n")

    def _on_fetch(self, _btn: Gtk.Button) -> None:
        if self._fetch_running:
            self._cancel_fetch()
            return

        dept_text = self._dept_entry.get_text().strip()
        search = self._search_entry.get_text().strip()

        if not dept_text and not search:
            self._log("Error: provide a search query or department ID.\n")
            return

        base_dir = Path(self._output_dir_btn.get_filename() or str(self._default_output_dir))
        output_dir = self._compute_output_dir()  # for display only
        limit = int(self._limit_spin.get_value())

        cmd = [self._driftwall_bin]
        if self._config_path:
            cmd += ["--config", self._config_path]
        cmd += ["fetch", "--source", "met", "--limit", str(limit), "--output-dir", str(base_dir)]
        if dept_text.isdigit():
            cmd += ["--department", dept_text]
        if search:
            cmd += ["--search", search]

        self._log(f"Running: {' '.join(cmd)}\n\n")
        self._fetch_running = True
        self._set_ui_sensitive(False)
        self._fetch_btn.set_sensitive(True)  # keep cancel button active
        self._fetch_btn.set_label("Cancel")
        ctx = self._fetch_btn.get_style_context()
        ctx.remove_class("suggested-action")
        ctx.add_class("destructive-action")

        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        def _run() -> None:
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
                )
                assert self._proc.stdout
                for line in self._proc.stdout:
                    GLib.idle_add(self._log, line)
                self._proc.wait()
                success = self._proc.returncode == 0
                GLib.idle_add(self._on_fetch_done, success, str(output_dir))
            except Exception as e:
                GLib.idle_add(self._log, f"\nError: {e}\n")
                GLib.idle_add(self._on_fetch_done, False, str(output_dir))

        threading.Thread(target=_run, daemon=True).start()

    def _on_fetch_done(self, success: bool, output_dir: str) -> None:
        self._fetch_running = False
        self._proc = None
        self._set_ui_sensitive(True)
        self._fetch_btn.set_label("Start Fetch")
        ctx = self._fetch_btn.get_style_context()
        ctx.remove_class("destructive-action")
        ctx.add_class("suggested-action")
        if success:
            try:
                subprocess.Popen(["notify-send", "Driftwall", f"Fetch complete — {output_dir}"])
            except FileNotFoundError:
                pass

    def _set_ui_sensitive(self, sensitive: bool) -> None:
        self._search_entry.set_sensitive(sensitive)
        self._dept_entry.set_sensitive(sensitive)
        self._limit_spin.set_sensitive(sensitive)
        self._output_dir_btn.set_sensitive(sensitive)
        self._fetch_btn.set_sensitive(sensitive)

    def _log(self, text: str) -> None:
        end = self._log_buf.get_end_iter()
        self._log_buf.insert(end, text)
        # Auto-scroll
        adj = self._log_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())

    def _on_close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self.destroy()

    def _on_delete(self, _widget: Gtk.Widget, _event: object) -> bool:
        self._on_close()
        return False
