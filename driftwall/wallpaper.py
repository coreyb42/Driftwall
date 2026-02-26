"""GNOME wallpaper setter via gsettings."""

from __future__ import annotations

import subprocess
from pathlib import Path


class WallpaperError(Exception):
    pass


def set_wallpaper(image_path: Path) -> None:
    """Set the GNOME desktop wallpaper (both light and dark variants)."""
    uri = f"file://{image_path}"
    for key in ("picture-uri", "picture-uri-dark"):
        result = subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.background", key, uri],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise WallpaperError(
                f"gsettings failed for {key}: {result.stderr.strip()}"
            )


def get_current_wallpaper() -> str | None:
    """Return the current wallpaper URI, or None on failure."""
    result = subprocess.run(
        ["gsettings", "get", "org.gnome.desktop.background", "picture-uri"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip().strip("'")
    return None
