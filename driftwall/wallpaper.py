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


def get_display_aspect_ratio() -> float | None:
    """
    Return primary display aspect ratio (width / height) from xrandr.
    Returns None if detection fails.
    """
    try:
        result = subprocess.run(
            ["xrandr", "--query"],
            capture_output=True,
            text=True,
        )
    except Exception:
        return None

    if result.returncode != 0 or not result.stdout:
        return None

    # Prefer primary monitor line: "... 2560x1440+0+0 ..."
    for line in result.stdout.splitlines():
        if " connected primary " in line:
            parts = line.split()
            for token in parts:
                if "x" in token and "+" in token:
                    dims = token.split("+", 1)[0]
                    if "x" in dims:
                        try:
                            w_str, h_str = dims.split("x", 1)
                            w = int(w_str)
                            h = int(h_str)
                            if w > 0 and h > 0:
                                return w / h
                        except (TypeError, ValueError):
                            pass

    # Fallback: first connected monitor line.
    for line in result.stdout.splitlines():
        if " connected " in line:
            parts = line.split()
            for token in parts:
                if "x" in token and "+" in token:
                    dims = token.split("+", 1)[0]
                    if "x" in dims:
                        try:
                            w_str, h_str = dims.split("x", 1)
                            w = int(w_str)
                            h = int(h_str)
                            if w > 0 and h > 0:
                                return w / h
                        except (TypeError, ValueError):
                            pass
    return None
