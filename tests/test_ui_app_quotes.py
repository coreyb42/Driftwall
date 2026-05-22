from __future__ import annotations

import importlib
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from driftwall import config


class _FakeMenu:
    def __init__(self) -> None:
        self.children = []

    def append(self, item) -> None:
        self.children.append(item)

    def show_all(self) -> None:
        pass


class _FakeMenuItem:
    def __init__(self, label: str = "") -> None:
        self.label = label
        self.handlers = {}
        self.sensitive = True
        self.submenu = None

    def connect(self, signal: str, callback) -> None:
        self.handlers[signal] = callback

    def set_label(self, label: str) -> None:
        self.label = label

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive

    def set_submenu(self, submenu) -> None:
        self.submenu = submenu


class _FakeCheckMenuItem(_FakeMenuItem):
    def __init__(self, label: str = "") -> None:
        super().__init__(label)
        self.active = False

    def set_active(self, active: bool) -> None:
        self.active = active

    def get_active(self) -> bool:
        return self.active


class _FakeSeparatorMenuItem(_FakeMenuItem):
    pass


class _FakeGtk:
    Menu = _FakeMenu
    MenuItem = _FakeMenuItem
    CheckMenuItem = _FakeCheckMenuItem
    SeparatorMenuItem = _FakeSeparatorMenuItem

    class ResponseType:
        OK = 1

    @staticmethod
    def main_quit() -> None:
        pass


class _FakeGLib:
    @staticmethod
    def idle_add(callback, *args):
        return callback(*args)


class _FakeIndicator:
    def set_status(self, _status) -> None:
        pass

    def set_title(self, _title) -> None:
        pass

    def set_menu(self, _menu) -> None:
        pass

    def set_label(self, _label, _guide) -> None:
        pass


class _FakeAppIndicator:
    class IndicatorCategory:
        APPLICATION_STATUS = 1

    class IndicatorStatus:
        ACTIVE = 1

    class Indicator:
        @staticmethod
        def new(_id, _icon, _category):
            return _FakeIndicator()


@contextmanager
def _import_app_with_fake_gtk():
    module_names = ["gi", "gi.repository", "driftwall.ui.app"]
    old_modules = {name: sys.modules.get(name) for name in module_names}

    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_args, **_kwargs: None
    fake_repo = types.ModuleType("gi.repository")
    fake_repo.Gtk = _FakeGtk
    fake_repo.GLib = _FakeGLib
    fake_repo.AyatanaAppIndicator3 = _FakeAppIndicator

    sys.modules["gi"] = fake_gi
    sys.modules["gi.repository"] = fake_repo
    sys.modules.pop("driftwall.ui.app", None)

    try:
        yield importlib.import_module("driftwall.ui.app")
    finally:
        sys.modules.pop("driftwall.ui.app", None)
        for name, module in old_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _FakeOverlayManager:
    def __init__(self) -> None:
        self.calls = []

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")


class TrayQuotePauseTests(unittest.TestCase):
    def test_menu_has_pause_quotes_item_initialized_from_sentinel(self) -> None:
        with TemporaryDirectory() as td, _import_app_with_fake_gtk() as app_module:
            sentinel = Path(td) / "quotes_paused"
            sentinel.touch()

            with mock.patch.object(config, "QUOTES_PAUSE_SENTINEL_PATH", sentinel):
                app = app_module.DriftwallApp()
                menu = app._build_menu()

            labels = [getattr(child, "label", "") for child in menu.children]
            self.assertIn("Pause Quotes", labels)
            self.assertIsNotNone(app._pause_quotes_item)
            self.assertTrue(app._pause_quotes_item.get_active())

    def test_pause_quotes_toggle_persists_and_pauses_overlay_manager(self) -> None:
        with TemporaryDirectory() as td, _import_app_with_fake_gtk() as app_module:
            sentinel = Path(td) / "quotes_paused"
            manager = _FakeOverlayManager()
            app = app_module.DriftwallApp()
            app._overlay_manager = manager

            with mock.patch.object(config, "QUOTES_PAUSE_SENTINEL_PATH", sentinel):
                item = _FakeCheckMenuItem("Pause Quotes")
                item.set_active(True)
                app._on_pause_quotes_toggle(item)
                self.assertTrue(sentinel.exists())
                self.assertEqual(manager.calls[-1], "pause")

                item.set_active(False)
                app._on_pause_quotes_toggle(item)

            self.assertFalse(sentinel.exists())
            self.assertEqual(manager.calls[-1], "resume")

    def test_wallpaper_resume_keeps_overlay_paused_when_quotes_are_paused(self) -> None:
        with _import_app_with_fake_gtk() as app_module:
            manager = _FakeOverlayManager()
            app = app_module.DriftwallApp()
            app._overlay_manager = manager
            app._pause_item = _FakeCheckMenuItem("Pause Wallpaper")
            app._pause_quotes_item = _FakeCheckMenuItem("Pause Quotes")
            app._pause_quotes_item.set_active(True)

            app._pause_item.set_active(False)
            with mock.patch("driftwall.config.clear_pause_sentinel"):
                app._on_pause_toggle(app._pause_item)

            self.assertEqual(manager.calls[-1], "pause")


if __name__ == "__main__":
    unittest.main()
