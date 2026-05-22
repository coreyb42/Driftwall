from __future__ import annotations

import unittest

from driftwall.windowing import configure_overlay_window_layer


class _DummyWindow:
    def __init__(self) -> None:
        self.calls = []

    def set_type_hint(self, value):
        self.calls.append(("set_type_hint", value))

    def set_keep_below(self, value):
        self.calls.append(("set_keep_below", value))

    def set_skip_taskbar_hint(self, value):
        self.calls.append(("set_skip_taskbar_hint", value))

    def set_skip_pager_hint(self, value):
        self.calls.append(("set_skip_pager_hint", value))

    def set_accept_focus(self, value):
        self.calls.append(("set_accept_focus", value))

    def stick(self):
        self.calls.append(("stick", None))


class _Hints:
    DESKTOP = "DESKTOP"
    NORMAL = "NORMAL"


class _Gdk:
    WindowTypeHint = _Hints


class WindowingTests(unittest.TestCase):
    def test_configure_overlay_window_layer_uses_desktop_hint(self) -> None:
        win = _DummyWindow()

        configure_overlay_window_layer(win, _Gdk)

        self.assertIn(("set_type_hint", "DESKTOP"), win.calls)
        self.assertIn(("set_keep_below", True), win.calls)
        self.assertIn(("set_skip_taskbar_hint", True), win.calls)
        self.assertIn(("set_skip_pager_hint", True), win.calls)
        self.assertIn(("set_accept_focus", False), win.calls)
        self.assertIn(("stick", None), win.calls)

    def test_configure_overlay_window_layer_falls_back_to_normal_hint(self) -> None:
        class _HintsNoDesktop:
            NORMAL = "NORMAL"

        class _GdkNoDesktop:
            WindowTypeHint = _HintsNoDesktop

        win = _DummyWindow()

        configure_overlay_window_layer(win, _GdkNoDesktop)

        self.assertIn(("set_type_hint", "NORMAL"), win.calls)


if __name__ == "__main__":
    unittest.main()
