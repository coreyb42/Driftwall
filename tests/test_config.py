from __future__ import annotations

import unittest
from pathlib import Path

from driftwall.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_uses_defaults_when_file_missing(self) -> None:
        cfg = load_config(Path("/tmp/driftwall-does-not-exist.toml"))

        self.assertEqual(cfg.image_dirs, [Path.home() / "Pictures"])
        self.assertEqual(cfg.rotation.interval_minutes, 30)
        self.assertEqual(cfg.overlay.prompts, ["a haiku"])
        self.assertEqual(cfg.overlay.quadrants, ["bottom-right"])

    def test_load_config_supports_legacy_image_dir_and_overlay_string_values(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        'image_dir = "/tmp/walls"',
                        '',
                        '[overlay]',
                        'prompt = "a limerick"',
                        'quadrant = "top-left"',
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(cfg.image_dirs, [Path("/tmp/walls")])
        self.assertEqual(cfg.overlay.prompts, ["a limerick"])
        self.assertEqual(cfg.overlay.quadrants, ["top-left"])

    def test_load_config_parses_overlay_font_size(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[overlay]",
                        "font_size = 44",
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(cfg.overlay.font_size, 44)

    def test_load_config_parses_trigger_map_and_expands_download_path(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        '[triggers]',
                        'enabled = true',
                        '[[triggers.time_of_day_map]]',
                        'hours = [9, 10]',
                        'values = "morning"',
                        '',
                        '[download]',
                        'output_dir = "~/tmp-driftwall-tests"',
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(len(cfg.triggers.time_of_day_map), 1)
        self.assertEqual(cfg.triggers.time_of_day_map[0].hours, [9, 10])
        self.assertEqual(cfg.triggers.time_of_day_map[0].values, ["morning"])
        self.assertEqual(cfg.download.output_dir, Path.home() / "tmp-driftwall-tests")

    def test_load_config_parses_dynamic_overlay_reserved_margins(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[dynamic_overlay]",
                        "reserved_left_px = 90",
                        "reserved_right_px = 10",
                        "reserved_top_px = 32",
                        "reserved_bottom_px = 50",
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(cfg.dynamic_overlay.reserved_left_px, 90)
        self.assertEqual(cfg.dynamic_overlay.reserved_right_px, 10)
        self.assertEqual(cfg.dynamic_overlay.reserved_top_px, 32)
        self.assertEqual(cfg.dynamic_overlay.reserved_bottom_px, 50)

    def test_load_config_parses_dynamic_overlay_random_source_subset_size(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[dynamic_overlay]",
                        "random_source_subset_size = 3",
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(cfg.dynamic_overlay.random_source_subset_size, 3)

    def test_load_config_parses_fonts_table(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[fonts]",
                        'source = "list"',
                        'directory = "/tmp/fonts"',
                        "[[fonts.entries]]",
                        'path = "/tmp/A.ttf"',
                        'description = "for poetic lines"',
                        "[[fonts.entries]]",
                        'path = "/tmp/B.ttf"',
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(cfg.fonts.source, "list")
        self.assertEqual(cfg.fonts.directory, "/tmp/fonts")
        self.assertEqual(len(cfg.fonts.entries), 2)
        self.assertEqual(cfg.fonts.entries[0]["path"], "/tmp/A.ttf")
        self.assertEqual(cfg.fonts.entries[0]["description"], "for poetic lines")
        self.assertEqual(cfg.fonts.entries[1]["path"], "/tmp/B.ttf")

    def test_load_config_fonts_falls_back_to_legacy_overlay_font_dir(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[overlay]",
                        'font_dir = "/tmp/legacy-fonts"',
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(cfg.fonts.source, "folder")
        self.assertEqual(cfg.fonts.directory, "/tmp/legacy-fonts")


    def test_default_classifier_backend_is_grok(self) -> None:
        cfg = load_config(Path("/tmp/driftwall-does-not-exist.toml"))
        self.assertEqual(cfg.classifier_backend, "grok")

    def test_load_config_parses_grok_section(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        'classifier_backend = "grok"',
                        "[grok]",
                        'model = "grok-2-vision"',
                        "concurrency = 8",
                        'api_key = "test-key"',
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(cfg.classifier_backend, "grok")
        self.assertEqual(cfg.grok.model, "grok-2-vision")
        self.assertEqual(cfg.grok.concurrency, 8)
        self.assertEqual(cfg.grok.api_key, "test-key")

    def test_load_config_parses_ollama_backend(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            config_path = Path(td) / "config.toml"
            config_path.write_text(
                'classifier_backend = "ollama"\n',
                encoding="utf-8",
            )

            cfg = load_config(config_path)

        self.assertEqual(cfg.classifier_backend, "ollama")


if __name__ == "__main__":
    unittest.main()
