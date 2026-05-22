"""Driftwall system tray application using AyatanaAppIndicator3 (GTK3)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
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
        self._scan_images_item: Gtk.MenuItem | None = None
        self._scan_content_item: Gtk.MenuItem | None = None
        self._pause_item: Gtk.CheckMenuItem | None = None
        self._pause_quotes_item: Gtk.CheckMenuItem | None = None
        self._scan_images_running = False
        self._scan_content_running = False
        self._overlay_manager = None

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

        # Dynamic content overlays (optional)
        try:
            from driftwall.config import load_config
            config = load_config(Path(self.config_path) if self.config_path else None)
            self._start_overlay_manager(config)
        except Exception as e:
            log.warning("Dynamic overlay init failed: %s", e)

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        next_item = Gtk.MenuItem(label="Next Wallpaper")
        next_item.connect("activate", self._on_next_wallpaper)
        menu.append(next_item)

        pause_item = Gtk.CheckMenuItem(label="Pause Wallpaper")
        pause_item.connect("toggled", self._on_pause_toggle)
        menu.append(pause_item)
        self._pause_item = pause_item

        from driftwall.config import are_quotes_paused
        pause_quotes_item = Gtk.CheckMenuItem(label="Pause Quotes")
        pause_quotes_item.set_active(are_quotes_paused())
        pause_quotes_item.connect("toggled", self._on_pause_quotes_toggle)
        menu.append(pause_quotes_item)
        self._pause_quotes_item = pause_quotes_item

        menu.append(Gtk.SeparatorMenuItem())

        scan_item = Gtk.MenuItem(label="Scan")
        scan_submenu = Gtk.Menu()

        scan_images_item = Gtk.MenuItem(label="Images")
        scan_images_item.connect("activate", self._on_scan_images)
        scan_submenu.append(scan_images_item)
        self._scan_images_item = scan_images_item

        scan_content_item = Gtk.MenuItem(label="Content")
        scan_content_item.connect("activate", self._on_scan_content)
        scan_submenu.append(scan_content_item)
        self._scan_content_item = scan_content_item

        scan_submenu.show_all()
        scan_item.set_submenu(scan_submenu)
        menu.append(scan_item)

        fetch_item = Gtk.MenuItem(label="Fetch Artworks…")
        fetch_item.connect("activate", self._on_fetch)
        menu.append(fetch_item)

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
        log_path: "Path | None" = None,
    ) -> None:
        """Run driftwall subcommand in a background thread; call on_done on the GLib main loop."""
        import datetime
        try:
            proc = subprocess.Popen(
                self._base_cmd() + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as e:
            log.error("Failed to launch driftwall %s: %s", " ".join(args), e)
            if log_path:
                try:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text(f"Failed to launch: {e}\n")
                except OSError:
                    pass
            if on_done:
                GLib.idle_add(on_done, False)
            return

        def _reader() -> None:
            assert proc.stdout is not None
            log_file = None
            if log_path:
                try:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_file = open(log_path, "w", buffering=1)
                    log_file.write(f"=== driftwall {' '.join(args)} ===\n")
                    log_file.write(f"Started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                except OSError as e:
                    log.warning("Cannot open scan log %s: %s", log_path, e)
                    log_file = None
            try:
                for line in proc.stdout:
                    log.info("[driftwall %s] %s", " ".join(args), line.rstrip())
                    if log_file:
                        log_file.write(line)
                proc.wait()
                if log_file:
                    log_file.write(f"\nFinished: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    log_file.write(f"  (exit code: {proc.returncode})\n")
            finally:
                if log_file:
                    log_file.close()
            if on_done:
                GLib.idle_add(on_done, proc.returncode == 0)

        threading.Thread(target=_reader, daemon=True).start()

    # ── menu callbacks ───────────────────────────────────────────────────────

    def _on_pause_toggle(self, item: Gtk.CheckMenuItem) -> None:
        from driftwall.config import clear_pause_sentinel, set_pause_sentinel
        if item.get_active():
            try:
                set_pause_sentinel()
            except OSError as e:
                log.warning("Failed to create pause sentinel: %s", e)
        else:
            try:
                clear_pause_sentinel()
            except OSError as e:
                log.warning("Failed to remove pause sentinel: %s", e)
        self._apply_overlay_pause_state()

    def _on_pause_quotes_toggle(self, item: Gtk.CheckMenuItem) -> None:
        from driftwall.config import clear_quotes_pause_sentinel, set_quotes_pause_sentinel
        if self._pause_quotes_item is None:
            self._pause_quotes_item = item
        if item.get_active():
            try:
                set_quotes_pause_sentinel()
            except OSError as e:
                log.warning("Failed to create quote pause sentinel: %s", e)
            self._apply_overlay_pause_state()
        else:
            try:
                clear_quotes_pause_sentinel()
            except OSError as e:
                log.warning("Failed to remove quote pause sentinel: %s", e)
            if self._overlay_manager is None:
                self._restart_overlay_manager()
            else:
                self._apply_overlay_pause_state()

    def _on_next_wallpaper(self, _item: Gtk.MenuItem) -> None:
        if self._pause_item is not None and self._pause_item.get_active():
            return  # paused — no-op

        def _done(success: bool) -> None:
            if success and self._overlay_manager is not None:
                self._update_overlay_manager()

        self._run_async(["rotate", "--no-triggers"], on_done=_done)

    def _update_overlay_manager(self) -> None:
        """Query DB for the latest shown image and pass it to the overlay manager."""
        try:
            from driftwall.config import load_config
            from driftwall.db import get_latest_shown_image
            config = load_config(Path(self.config_path) if self.config_path else None)
            image = get_latest_shown_image(config.resolved_db_path)
            if image and self._overlay_manager is not None:
                self._overlay_manager.set_image(image)
        except Exception as e:
            log.warning("Failed to update overlay manager: %s", e)

    def _seed_overlay_manager_from_history(self, config) -> None:
        """Seed the overlay manager with the most recently shown image."""
        try:
            from driftwall.db import get_latest_shown_image
            image = get_latest_shown_image(config.resolved_db_path)
            if image and self._overlay_manager is not None:
                self._overlay_manager.set_image(image)
        except Exception as e:
            log.warning("Failed to seed overlay manager: %s", e)

    def _update_scan_indicator(self) -> None:
        """Show a pulsing label on the tray icon while any scan is running."""
        scanning = self._scan_images_running or self._scan_content_running
        self.indicator.set_label("⟳" if scanning else "", "⟳")

    def _on_scan_images(self, _item: Gtk.MenuItem) -> None:
        if self._scan_images_running:
            return
        self._scan_images_running = True
        if self._scan_images_item:
            self._scan_images_item.set_sensitive(False)
            self._scan_images_item.set_label("Images (scanning…)")
        self._update_scan_indicator()

        def _done(success: bool) -> None:
            self._scan_images_running = False
            if self._scan_images_item:
                self._scan_images_item.set_sensitive(True)
                self._scan_images_item.set_label("Images")
            self._update_scan_indicator()
            msg = "Image scan complete." if success else "Image scan failed — check logs."
            try:
                subprocess.Popen(["notify-send", "Driftwall", msg])
            except FileNotFoundError:
                pass

        _log = Path.home() / ".local" / "share" / "driftwall" / "scan-images.log"
        self._run_async(["scan", "--images"], on_done=_done, log_path=_log)

    def _on_scan_content(self, _item: Gtk.MenuItem) -> None:
        if self._scan_content_running:
            return
        self._scan_content_running = True
        if self._scan_content_item:
            self._scan_content_item.set_sensitive(False)
            self._scan_content_item.set_label("Content (scanning…)")
        self._update_scan_indicator()

        def _done(success: bool) -> None:
            self._scan_content_running = False
            if self._scan_content_item:
                self._scan_content_item.set_sensitive(True)
                self._scan_content_item.set_label("Content")
            self._update_scan_indicator()
            msg = "Content scan complete." if success else "Content scan failed — check logs."
            try:
                subprocess.Popen(["notify-send", "Driftwall", msg])
            except FileNotFoundError:
                pass

        _log = Path.home() / ".local" / "share" / "driftwall" / "scan-content.log"
        self._run_async(["scan", "--content"], on_done=_done, log_path=_log)

    def _on_status(self, _item: Gtk.MenuItem) -> None:
        from driftwall.ui.status import StatusWindow
        win = StatusWindow(config_path=self.config_path)
        win.show_all()

    def _on_fetch(self, _item: Gtk.MenuItem) -> None:
        from driftwall.ui.fetch import FetchDialog
        dialog = FetchDialog(
            config_path=self.config_path,
            driftwall_bin=_find_driftwall_bin(),
        )
        dialog.show_all()

    def _on_settings(self, _item: Gtk.MenuItem) -> None:
        from driftwall.ui.settings import SettingsDialog
        from driftwall.config import load_config

        before = load_config(Path(self.config_path) if self.config_path else None)
        saved_hook_called = False

        def _on_saved() -> None:
            nonlocal saved_hook_called
            saved_hook_called = True
            self._restart_overlay_manager()

        dialog = SettingsDialog(config_path=self.config_path, on_saved=_on_saved)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            after = load_config(Path(self.config_path) if self.config_path else None)
            if self._fonts_config_fingerprint(before) != self._fonts_config_fingerprint(after):
                self._reexec_self()
                return
            if not saved_hook_called:
                self._restart_overlay_manager()

    def _fonts_config_fingerprint(self, config) -> tuple:
        entries = tuple(
            sorted(
                (
                    str(e.get("path", "")).strip(),
                    str(e.get("description", "")).strip(),
                )
                for e in config.fonts.entries
            )
        )
        return (
            config.fonts.source,
            config.fonts.directory,
            entries,
        )

    def _reexec_self(self) -> None:
        """Re-exec the tray process so runtime font registration is rebuilt cleanly."""
        argv = [sys.executable, "-m", "driftwall.ui"]
        if self.config_path:
            argv += ["--config", self.config_path]
        os.execv(sys.executable, argv)

    def _restart_overlay_manager(self) -> None:
        """Stop the current overlay manager and start a fresh one with reloaded config."""
        if self._overlay_manager is not None:
            self._overlay_manager.stop(immediate=True)
            self._overlay_manager = None
        try:
            from driftwall.config import load_config
            config = load_config(Path(self.config_path) if self.config_path else None)
            self._start_overlay_manager(config)
        except Exception as e:
            log.warning("Dynamic overlay restart failed: %s", e)

    def _start_overlay_manager(self, config) -> None:
        if not (config.dynamic_overlay.enabled and config.content.enabled):
            return
        from driftwall.dynamic_overlay import DynamicOverlayManager
        self._overlay_manager = DynamicOverlayManager(config, config.resolved_db_path)
        self._overlay_manager.start()
        self._seed_overlay_manager_from_history(config)
        self._apply_overlay_pause_state()
        if not self._overlay_pause_requested():
            self._overlay_manager.spawn_now()

    def _overlay_pause_requested(self) -> bool:
        return bool(
            (self._pause_item is not None and self._pause_item.get_active())
            or (self._pause_quotes_item is not None and self._pause_quotes_item.get_active())
        )

    def _apply_overlay_pause_state(self) -> None:
        if self._overlay_manager is None:
            return
        if self._overlay_pause_requested():
            self._overlay_manager.pause()
        else:
            self._overlay_manager.resume()
