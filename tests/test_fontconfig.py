from __future__ import annotations

import ctypes
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from driftwall.overlay import register_font_with_fontconfig


class FontconfigTests(unittest.TestCase):
    def test_register_font_with_fontconfig_returns_false_for_empty_path(self) -> None:
        self.assertFalse(register_font_with_fontconfig(""))

    def test_register_font_with_fontconfig_returns_false_when_file_missing(self) -> None:
        self.assertFalse(register_font_with_fontconfig("/tmp/does-not-exist-font.ttf"))

    def test_register_font_with_fontconfig_registers_existing_font_file(self) -> None:
        with TemporaryDirectory() as td:
            font_path = Path(td) / "Custom.ttf"
            font_path.write_bytes(b"not-a-real-font")

            lib = MagicMock()
            lib.FcInit.return_value = 1
            lib.FcConfigGetCurrent.return_value = ctypes.c_void_p(123)
            lib.FcConfigAppFontAddFile.return_value = 1
            lib.FcConfigBuildFonts.return_value = 1

            with patch("driftwall.overlay.ctypes.util.find_library", return_value="libfontconfig.so.1"), \
                 patch("driftwall.overlay.ctypes.CDLL", return_value=lib):
                ok = register_font_with_fontconfig(str(font_path))

            self.assertTrue(ok)
            self.assertTrue(lib.FcConfigAppFontAddFile.called)

    def test_register_font_with_fontconfig_returns_false_when_add_fails(self) -> None:
        with TemporaryDirectory() as td:
            font_path = Path(td) / "Custom.ttf"
            font_path.write_bytes(b"not-a-real-font")

            lib = MagicMock()
            lib.FcInit.return_value = 1
            lib.FcConfigGetCurrent.return_value = ctypes.c_void_p(123)
            lib.FcConfigAppFontAddFile.return_value = 0

            with patch("driftwall.overlay.ctypes.util.find_library", return_value="libfontconfig.so.1"), \
                 patch("driftwall.overlay.ctypes.CDLL", return_value=lib):
                ok = register_font_with_fontconfig(str(font_path))

            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
