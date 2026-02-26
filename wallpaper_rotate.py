#!/usr/bin/env python3

import os
import random
import subprocess
from pathlib import Path

WALLPAPER_DIR = Path.home() / "Pictures"

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def get_images(directory: Path):
    return [
        p for p in directory.rglob("*")
        if p.suffix.lower() in VALID_EXTENSIONS and p.is_file()
    ]


def set_wallpaper(image_path: Path):
    uri = f"file://{image_path}"
    subprocess.run(
        [
            "gsettings",
            "set",
            "org.gnome.desktop.background",
            "picture-uri",
            uri,
        ],
        check=True,
    )
    subprocess.run(
        [
            "gsettings",
            "set",
            "org.gnome.desktop.background",
            "picture-uri-dark",
            uri,
        ],
        check=True,
    )


def main():
    if not WALLPAPER_DIR.exists():
        raise RuntimeError(f"Directory not found: {WALLPAPER_DIR}")

    images = get_images(WALLPAPER_DIR)

    if not images:
        raise RuntimeError("No valid images found.")

    selected = random.choice(images)
    set_wallpaper(selected)


if __name__ == "__main__":
    main()
