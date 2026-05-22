from __future__ import annotations

import re
import subprocess
from pathlib import Path


WALLPAPER_ROTATE_TIMER_PATH = Path.home() / ".config" / "systemd" / "user" / "wallpaper-rotate.timer"


def update_on_unit_active_sec(timer_text: str, interval_minutes: int) -> tuple[str, bool]:
    target_line = f"OnUnitActiveSec={interval_minutes}min"

    pattern = re.compile(r"(?im)^OnUnitActiveSec\s*=.*$")
    if pattern.search(timer_text):
        updated = pattern.sub(target_line, timer_text, count=1)
        return updated, updated != timer_text

    timer_header = re.search(r"(?im)^\[Timer\]\s*$", timer_text)
    if not timer_header:
        return timer_text, False

    insert_at = timer_header.end()
    if insert_at < len(timer_text) and timer_text[insert_at] != "\n":
        updated = timer_text[:insert_at] + "\n" + target_line + timer_text[insert_at:]
    else:
        updated = timer_text[:insert_at] + "\n" + target_line + timer_text[insert_at:]
    return updated, True


def sync_wallpaper_rotate_timer_interval(
    interval_minutes: int,
    timer_path: Path | None = None,
    runner=subprocess.run,
) -> str | None:
    path = timer_path or WALLPAPER_ROTATE_TIMER_PATH
    if not path.exists():
        return None

    original = path.read_text(encoding="utf-8")
    updated, changed = update_on_unit_active_sec(original, interval_minutes)
    if not changed:
        return None

    path.write_text(updated, encoding="utf-8")

    try:
        runner(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        runner(
            ["systemctl", "--user", "restart", "wallpaper-rotate.timer"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return "Saved config, but failed to reload/restart wallpaper-rotate.timer."

    return f"Updated wallpaper-rotate.timer to {interval_minutes} minute(s)."
