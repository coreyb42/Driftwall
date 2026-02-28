"""Driftwall system tray application using AyatanaAppIndicator3 (GTK3)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3, GLib, Gtk  # noqa: E402

log = logging.getLogger(__name__)


def _find_driftwall_bin() -> str:
    """Find the driftwall binary via PATH or common install locations."""
    found = shutil.which("driftwall")
    if found:
        return found
    candidates = [
        Path(__file__).parent.parent.parent / ".venv" / "bin" / "driftwall",
        Path.home() / ".local" / "bin" / "driftwall",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "driftwall"


class DriftwallApp:
    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = config_path
        self._scan_item: Gtk.MenuItem | None = None
        self._scan_running = False

    def setup(self) -> None:
        """Create the AppIndicator and tray menu."""
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "driftwall",
            "preferences-desktop-wallpaper",
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Driftwall")
        self.indicator.set_menu(self._build_menu())

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        next_item = Gtk.MenuItem(label="Next Wallpaper")
        next_item.connect("activate", self._on_next_wallpaper)
        menu.append(next_item)

        menu.append(Gtk.SeparatorMenuItem())

        scan_item = Gtk.MenuItem(label="Scan Images")
        scan_item.connect("activate", self._on_scan)
        menu.append(scan_item)
        self._scan_item = scan_item

        status_item = Gtk.MenuItem(label="Status")
        status_item.connect("activate", self._on_status)
        menu.append(status_item)

        settings_item = Gtk.MenuItem(label="Settings")
        settings_item.connect("activate", self._on_settings)
        menu.append(settings_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: Gtk.main_quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    # ── subprocess helpers ───────────────────────────────────────────────────

    def _base_cmd(self) -> list[str]:
        cmd = [_find_driftwall_bin()]
        if self.config_path:
            cmd += ["--config", self.config_path]
        return cmd

    def _run_async(
        self,
        args: list[str],
        on_done: "callable[[bool], None] | None" = None,
    ) -> None:
        """Run driftwall subcommand in a background thread; call on_done on the GLib main loop."""
        try:
            proc = subprocess.Popen(
                self._base_cmd() + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as e:
            log.error("Failed to launch driftwall %s: %s", " ".join(args), e)
            if on_done:
                GLib.idle_add(on_done, False)
            return

        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                log.info("[driftwall %s] %s", " ".join(args), line.rstrip())
            proc.wait()
            if on_done:
                GLib.idle_add(on_done, proc.returncode == 0)

        threading.Thread(target=_reader, daemon=True).start()

    # ── menu callbacks ───────────────────────────────────────────────────────

    def _on_next_wallpaper(self, _item: Gtk.MenuItem) -> None:
        self._run_async(["rotate", "--no-triggers"])

    def _on_scan(self, _item: Gtk.MenuItem) -> None:
        if self._scan_running:
            return
        self._scan_running = True
        if self._scan_item:
            self._scan_item.set_sensitive(False)
            self._scan_item.set_label("Scanning…")

        def _done(success: bool) -> None:
            self._scan_running = False
            if self._scan_item:
                self._scan_item.set_sensitive(True)
                self._scan_item.set_label("Scan Images")
            msg = "Scan complete." if success else "Scan failed — check logs."
            try:
                subprocess.Popen(["notify-send", "Driftwall", msg])
            except FileNotFoundError:
                pass

        self._run_async(["scan"], on_done=_done)

    def _on_status(self, _item: Gtk.MenuItem) -> None:
        from driftwall.ui.status import StatusWindow
        win = StatusWindow(config_path=self.config_path)
        win.show_all()

    def _on_settings(self, _item: Gtk.MenuItem) -> None:
        from driftwall.ui.settings import SettingsDialog
        dialog = SettingsDialog(config_path=self.config_path)
        dialog.run()
        dialog.destroy()
