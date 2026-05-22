from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from driftwall.systemd_timer import (
    sync_wallpaper_rotate_timer_interval,
    update_on_unit_active_sec,
)


class SystemdTimerTests(unittest.TestCase):
    def test_update_on_unit_active_sec_replaces_existing_line(self) -> None:
        text = "[Unit]\nDescription=Run wallpaper rotator every 5 minutes\n\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=5min\n"
        updated, changed = update_on_unit_active_sec(text, 1)

        self.assertTrue(changed)
        self.assertIn("OnUnitActiveSec=1min", updated)
        self.assertNotIn("OnUnitActiveSec=5min", updated)

    def test_update_on_unit_active_sec_inserts_when_missing(self) -> None:
        text = "[Unit]\nDescription=Run wallpaper rotator\n\n[Timer]\nOnBootSec=2min\n"
        updated, changed = update_on_unit_active_sec(text, 3)

        self.assertTrue(changed)
        self.assertIn("[Timer]\nOnUnitActiveSec=3min\nOnBootSec=2min", updated)

    def test_sync_noop_when_timer_missing(self) -> None:
        with TemporaryDirectory() as td:
            missing = Path(td) / "wallpaper-rotate.timer"
            msg = sync_wallpaper_rotate_timer_interval(2, timer_path=missing)
        self.assertIsNone(msg)

    def test_sync_updates_file_and_runs_reload_and_restart(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(cmd, check, stdout, stderr):  # noqa: ANN001
            calls.append(cmd)
            return object()

        with TemporaryDirectory() as td:
            timer_path = Path(td) / "wallpaper-rotate.timer"
            timer_path.write_text(
                "[Unit]\nDescription=Rotate\n\n[Timer]\nOnUnitActiveSec=5min\n",
                encoding="utf-8",
            )
            msg = sync_wallpaper_rotate_timer_interval(
                4, timer_path=timer_path, runner=fake_runner
            )

            updated = timer_path.read_text(encoding="utf-8")

        self.assertEqual(msg, "Updated wallpaper-rotate.timer to 4 minute(s).")
        self.assertIn("OnUnitActiveSec=4min", updated)
        self.assertEqual(
            calls,
            [
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "restart", "wallpaper-rotate.timer"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
