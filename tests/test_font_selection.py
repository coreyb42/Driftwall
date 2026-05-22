from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from driftwall.font_selection import FontOption, build_font_options, pick_font_for_context


class FontSelectionTests(unittest.TestCase):
    def test_build_font_options_from_list_uses_description_or_font_name(self) -> None:
        from driftwall.config import Config

        with TemporaryDirectory() as td:
            one = Path(td) / "One.ttf"
            two = Path(td) / "NotoSans-Regular.ttf"
            one.write_bytes(b"a")
            two.write_bytes(b"b")

            config = Config()
            config.fonts.source = "list"
            config.fonts.entries = [
                {"path": str(one), "description": "for poetic overlays"},
                {"path": str(two), "description": ""},
            ]

            options = build_font_options(config)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0].rationale, "for poetic overlays")
        self.assertEqual(options[1].rationale, "Noto Sans")

    def test_build_font_options_from_folder_scans_recursively(self) -> None:
        from driftwall.config import Config

        with TemporaryDirectory() as td:
            d = Path(td)
            nested = d / "nested"
            nested.mkdir()
            (d / "A.ttf").write_bytes(b"a")
            (nested / "B.otf").write_bytes(b"b")
            (nested / "ignore.txt").write_text("x", encoding="utf-8")

            config = Config()
            config.fonts.source = "folder"
            config.fonts.directory = str(d)

            options = build_font_options(config)

        self.assertEqual(sorted(o.path.name for o in options), ["A.ttf", "B.otf"])

    def test_build_font_options_filters_unreadable_when_enabled(self) -> None:
        from driftwall.config import Config

        with TemporaryDirectory() as td:
            d = Path(td)
            stencil_dir = d / "Stencil" / "Big_Shoulders_Stencil"
            stencil_dir.mkdir(parents=True)
            serif_dir = d / "Serif" / "Lora"
            serif_dir.mkdir(parents=True)
            (stencil_dir / "BigShouldersStencil-ExtraLight.ttf").write_bytes(b"x")
            (serif_dir / "Lora-Regular.ttf").write_bytes(b"x")

            config = Config()
            config.fonts.source = "folder"
            config.fonts.directory = str(d)
            config.fonts.filter_unreadable = True

            options = build_font_options(config)

        names = sorted(o.path.name for o in options)
        self.assertEqual(names, ["Lora-Regular.ttf"])

    def test_build_font_options_keeps_unreadable_when_disabled(self) -> None:
        from driftwall.config import Config

        with TemporaryDirectory() as td:
            d = Path(td)
            stencil_dir = d / "Stencil"
            stencil_dir.mkdir(parents=True)
            (stencil_dir / "Stencil-Bold.ttf").write_bytes(b"x")

            config = Config()
            config.fonts.source = "folder"
            config.fonts.directory = str(d)
            config.fonts.filter_unreadable = False

            options = build_font_options(config)

        self.assertEqual([o.path.name for o in options], ["Stencil-Bold.ttf"])

    def test_build_font_options_list_mode_also_filters_when_enabled(self) -> None:
        from driftwall.config import Config

        with TemporaryDirectory() as td:
            ok = Path(td) / "Lora-Regular.ttf"
            bad = Path(td) / "BigShouldersStencil-ExtraLight.ttf"
            ok.write_bytes(b"a")
            bad.write_bytes(b"b")

            config = Config()
            config.fonts.source = "list"
            config.fonts.entries = [
                {"path": str(ok), "description": "serif body"},
                {"path": str(bad), "description": ""},
            ]
            config.fonts.filter_unreadable = True

            options = build_font_options(config)

        self.assertEqual([o.path.name for o in options], ["Lora-Regular.ttf"])

    def test_pick_font_for_context_uses_llm_choice(self) -> None:
        options = [
            FontOption(path=Path("/tmp/FontA.ttf"), rationale="calm and meditative"),
            FontOption(path=Path("/tmp/FontB.ttf"), rationale="urgent and punchy"),
        ]

        class _Client:
            def __init__(self, host: str):
                self.host = host

            def generate(self, **_kwargs):
                return {"response": "2"}

        ollama_mod = types.ModuleType("ollama")
        ollama_mod.Client = _Client  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"ollama": ollama_mod}):
            chosen = pick_font_for_context(
                options=options,
                context="short energetic quote",
                purpose="dynamic content overlay",
                model="tiny-local",
                host="http://localhost:11434",
            )

        self.assertEqual(chosen, Path("/tmp/FontB.ttf"))


if __name__ == "__main__":
    unittest.main()
