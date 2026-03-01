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


if __name__ == "__main__":
    unittest.main()
