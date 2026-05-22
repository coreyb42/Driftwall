from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from driftwall import cli, config


class PauseSentinelHelpersTests(unittest.TestCase):
    def test_set_and_clear_create_and_remove_sentinel(self) -> None:
        with TemporaryDirectory() as td:
            sentinel = Path(td) / "nested" / "paused"
            with mock.patch.object(config, "PAUSE_SENTINEL_PATH", sentinel):
                self.assertFalse(config.is_paused())

                config.set_pause_sentinel()
                self.assertTrue(sentinel.exists())
                self.assertTrue(config.is_paused())

                config.clear_pause_sentinel()
                self.assertFalse(sentinel.exists())
                self.assertFalse(config.is_paused())

    def test_set_is_idempotent(self) -> None:
        with TemporaryDirectory() as td:
            sentinel = Path(td) / "paused"
            with mock.patch.object(config, "PAUSE_SENTINEL_PATH", sentinel):
                config.set_pause_sentinel()
                config.set_pause_sentinel()
                self.assertTrue(sentinel.exists())

    def test_clear_is_idempotent_when_missing(self) -> None:
        with TemporaryDirectory() as td:
            sentinel = Path(td) / "paused"
            with mock.patch.object(config, "PAUSE_SENTINEL_PATH", sentinel):
                # Should not raise even though it doesn't exist.
                config.clear_pause_sentinel()
                self.assertFalse(sentinel.exists())


class CliPauseResumeTests(unittest.TestCase):
    def _args(self) -> argparse.Namespace:
        return argparse.Namespace(config=None, verbose=False)

    def test_cmd_pause_creates_sentinel(self) -> None:
        with TemporaryDirectory() as td:
            sentinel = Path(td) / "paused"
            with mock.patch.object(config, "PAUSE_SENTINEL_PATH", sentinel), \
                 mock.patch.object(cli, "PAUSE_SENTINEL_PATH", sentinel):
                rc = cli.cmd_pause(self._args())
                self.assertEqual(rc, 0)
                self.assertTrue(sentinel.exists())

    def test_cmd_pause_idempotent(self) -> None:
        with TemporaryDirectory() as td:
            sentinel = Path(td) / "paused"
            sentinel.touch()
            with mock.patch.object(config, "PAUSE_SENTINEL_PATH", sentinel), \
                 mock.patch.object(cli, "PAUSE_SENTINEL_PATH", sentinel):
                rc = cli.cmd_pause(self._args())
                self.assertEqual(rc, 0)
                self.assertTrue(sentinel.exists())

    def test_cmd_resume_removes_sentinel(self) -> None:
        with TemporaryDirectory() as td:
            sentinel = Path(td) / "paused"
            sentinel.touch()
            with mock.patch.object(config, "PAUSE_SENTINEL_PATH", sentinel), \
                 mock.patch.object(cli, "PAUSE_SENTINEL_PATH", sentinel):
                rc = cli.cmd_resume(self._args())
                self.assertEqual(rc, 0)
                self.assertFalse(sentinel.exists())

    def test_cmd_resume_idempotent_when_not_paused(self) -> None:
        with TemporaryDirectory() as td:
            sentinel = Path(td) / "paused"
            with mock.patch.object(config, "PAUSE_SENTINEL_PATH", sentinel), \
                 mock.patch.object(cli, "PAUSE_SENTINEL_PATH", sentinel):
                rc = cli.cmd_resume(self._args())
                self.assertEqual(rc, 0)
                self.assertFalse(sentinel.exists())

    def test_pause_and_resume_registered_in_parser(self) -> None:
        parser = cli.build_parser()
        # parse_args will SystemExit if subcommand is unknown.
        args = parser.parse_args(["pause"])
        self.assertEqual(args.command, "pause")
        args = parser.parse_args(["resume"])
        self.assertEqual(args.command, "resume")


class UiAutoClearTests(unittest.TestCase):
    def test_cmd_ui_clears_pause_sentinel_before_exec(self) -> None:
        with TemporaryDirectory() as td:
            sentinel = Path(td) / "paused"
            sentinel.touch()
            self.assertTrue(sentinel.exists())

            captured: dict[str, bool] = {"sentinel_existed_at_exec": True}

            def fake_execve(_path: str, _argv: list[str], _env: dict[str, str]) -> None:
                captured["sentinel_existed_at_exec"] = sentinel.exists()
                # Don't actually exec.

            with mock.patch.object(config, "PAUSE_SENTINEL_PATH", sentinel), \
                 mock.patch.object(cli, "PAUSE_SENTINEL_PATH", sentinel), \
                 mock.patch("os.execve", side_effect=fake_execve):
                cli.cmd_ui(argparse.Namespace(config=None, verbose=False))

            self.assertFalse(captured["sentinel_existed_at_exec"])
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
