from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from driftwall.overlay import apply_overlay, resolve_font_family


class OverlayFontFamilyTests(unittest.TestCase):
    def test_resolve_font_family_uses_pillow_name_when_available(self) -> None:
        try:
            from PIL import ImageFont
        except ImportError:
            self.skipTest("Pillow is not installed")

        class _Font:
            def getname(self):
                return ("Configured Family", "Regular")

        with patch.object(ImageFont, "truetype", return_value=_Font()):
            family = resolve_font_family("/tmp/AnyFont-Regular.ttf")

        self.assertEqual(family, "Configured Family")

    def test_resolve_font_family_falls_back_to_sanitized_filename(self) -> None:
        pil_mod = types.ModuleType("PIL")
        imagefont_mod = types.ModuleType("PIL.ImageFont")

        def _truetype(_path: str, _size: int):
            raise OSError("bad font")

        imagefont_mod.truetype = _truetype  # type: ignore[attr-defined]
        pil_mod.ImageFont = imagefont_mod  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"PIL": pil_mod, "PIL.ImageFont": imagefont_mod}):
            family = resolve_font_family("/tmp/NotoSans-Regular.ttf")

        self.assertEqual(family, "Noto Sans")

    def test_resolve_font_family_uses_default_when_empty(self) -> None:
        self.assertEqual(resolve_font_family(""), "Sans")

    def test_resolve_font_family_uses_fc_scan_when_pillow_fails(self) -> None:
        pil_mod = types.ModuleType("PIL")
        imagefont_mod = types.ModuleType("PIL.ImageFont")

        def _truetype(_path: str, _size: int):
            raise OSError("bad font")

        imagefont_mod.truetype = _truetype  # type: ignore[attr-defined]
        pil_mod.ImageFont = imagefont_mod  # type: ignore[attr-defined]

        class _Proc:
            stdout = "Cinzel Decorative\n"

        with patch.dict(sys.modules, {"PIL": pil_mod, "PIL.ImageFont": imagefont_mod}):
            with patch("driftwall.overlay.subprocess.run", return_value=_Proc()):
                family = resolve_font_family("/tmp/cinzel.ttf")

        self.assertEqual(family, "Cinzel Decorative")


class ApplyOverlayTests(unittest.TestCase):
    def test_apply_overlay_uses_configured_font_size_when_provided(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")

        captured_sizes: list[int] = []

        class _Font:
            def getlength(self, text: str) -> float:
                return max(1, len(text)) * 10.0

        class _Draw:
            def rounded_rectangle(self, *_args, **_kwargs) -> None:
                return None

            def text(self, *_args, **_kwargs) -> None:
                return None

        def _truetype(_path: str, size: int):
            captured_sizes.append(size)
            return _Font()

        with TemporaryDirectory() as td:
            image_path = Path(td) / "input.jpg"
            output_path = Path(td) / "output.jpg"
            Image.new("RGB", (1600, 900), "black").save(image_path)

            with patch("driftwall.overlay._resolve_font", return_value="/tmp/custom.ttf"):
                with patch("PIL.ImageFont.truetype", side_effect=_truetype):
                    with patch("PIL.ImageDraw.Draw", return_value=_Draw()):
                        apply_overlay(
                            image_path=image_path,
                            text="configured size",
                            quadrant="bottom-right",
                            font_file="/tmp/custom.ttf",
                            font_size=44,
                            output_path=output_path,
                        )
                    self.assertTrue(output_path.exists())

        self.assertIn(44, captured_sizes)


if __name__ == "__main__":
    unittest.main()
