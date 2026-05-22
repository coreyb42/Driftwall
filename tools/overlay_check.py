#!/usr/bin/env python3
"""Dev tool: screenshot the live desktop, find driftwall overlay windows, and
report placement issues (overlap with panel/dock, off-screen, mutual overlap).

Run from the project root:

    python tools/overlay_check.py            # one shot
    python tools/overlay_check.py --watch    # repeat every 5s
    python tools/overlay_check.py --save out.png   # also save annotated screenshot

Requires X11 (`xprop`, `xwininfo`) and PIL. Picks the active display by checking
$DISPLAY then falling back to :1.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageGrab

OVERLAY_WM_CLASS_SUBSTRING = "__main__.py"  # python3 -m driftwall.ui registers this


def _pick_display() -> str:
    if os.environ.get("DISPLAY"):
        return os.environ["DISPLAY"]
    sock_dir = Path("/tmp/.X11-unix")
    if sock_dir.is_dir():
        for entry in sorted(sock_dir.iterdir()):
            if entry.name.startswith("X"):
                return f":{entry.name[1:]}"
    return ":0"


def _xprop(args: list[str], display: str) -> str:
    env = {**os.environ, "DISPLAY": display}
    return subprocess.run(["xprop", *args], capture_output=True, text=True, env=env).stdout


def _xwininfo(args: list[str], display: str) -> str:
    env = {**os.environ, "DISPLAY": display}
    return subprocess.run(["xwininfo", *args], capture_output=True, text=True, env=env).stdout


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )

    def intersection(self, other: "Rect") -> "Rect | None":
        ix = max(self.x, other.x)
        iy = max(self.y, other.y)
        iw = min(self.right, other.right) - ix
        ih = min(self.bottom, other.bottom) - iy
        if iw <= 0 or ih <= 0:
            return None
        return Rect(ix, iy, iw, ih)


@dataclass
class WindowInfo:
    wid: str
    name: str
    wm_class: str
    rect: Rect


def list_windows(display: str) -> list[WindowInfo]:
    out = _xprop(["-root", "_NET_CLIENT_LIST"], display)
    m = re.search(r"# (.+)$", out.strip())
    if not m:
        return []
    ids = [s.strip() for s in m.group(1).split(",") if s.strip()]
    result: list[WindowInfo] = []
    for wid in ids:
        info = _xwininfo(["-id", wid], display)
        pos = re.search(
            r"Absolute upper-left X:\s+(-?\d+).*?Absolute upper-left Y:\s+(-?\d+)"
            r".*?Width:\s+(\d+).*?Height:\s+(\d+)",
            info,
            re.DOTALL,
        )
        if not pos:
            continue
        x, y, w, h = map(int, pos.groups())
        meta = _xprop(["-id", wid, "WM_CLASS", "_NET_WM_NAME", "WM_NAME"], display)
        cls_m = re.search(r'WM_CLASS\(.*?\)\s*=\s*(.+)', meta)
        nm_m = re.search(r'_NET_WM_NAME.*?=\s*"([^"]+)"', meta) or re.search(
            r'WM_NAME.*?=\s*"([^"]+)"', meta
        )
        result.append(
            WindowInfo(
                wid=wid,
                name=nm_m.group(1) if nm_m else "",
                wm_class=cls_m.group(1) if cls_m else "",
                rect=Rect(x, y, w, h),
            )
        )
    return result


def find_overlays(windows: list[WindowInfo]) -> list[WindowInfo]:
    return [w for w in windows if OVERLAY_WM_CLASS_SUBSTRING in w.wm_class]


def get_workarea(display: str) -> Rect:
    """Read _NET_WORKAREA in PHYSICAL pixels."""
    out = _xprop(["-root", "_NET_WORKAREA"], display)
    m = re.search(r"=\s*([\d,\s]+)", out)
    if not m:
        return Rect(0, 0, 0, 0)
    nums = [int(n.strip()) for n in m.group(1).split(",")]
    if len(nums) >= 4:
        return Rect(nums[0], nums[1], nums[2], nums[3])
    return Rect(0, 0, 0, 0)


def get_struts(display: str) -> dict[str, Rect]:
    """Find windows that reserve screen edges (panels, docks) via _NET_WM_STRUT_PARTIAL.

    Returns dict of wid -> Rect of the reserved screen region.
    """
    out = _xprop(["-root", "_NET_CLIENT_LIST"], display)
    m = re.search(r"# (.+)$", out.strip())
    if not m:
        return {}
    ids = [s.strip() for s in m.group(1).split(",") if s.strip()]
    screen_size = _screen_size(display)
    sw, sh = screen_size
    result: dict[str, Rect] = {}
    for wid in ids:
        prop = _xprop(["-id", wid, "_NET_WM_STRUT_PARTIAL", "_NET_WM_STRUT"], display)
        partial = re.search(r"_NET_WM_STRUT_PARTIAL\(.*?\)\s*=\s*([\d,\s]+)", prop)
        if partial:
            nums = [int(n.strip()) for n in partial.group(1).split(",")]
            if len(nums) >= 12:
                left, right, top, bottom = nums[:4]
                left_y_start, left_y_end = nums[4], nums[5]
                right_y_start, right_y_end = nums[6], nums[7]
                top_x_start, top_x_end = nums[8], nums[9]
                bottom_x_start, bottom_x_end = nums[10], nums[11]
                if top > 0:
                    result[f"{wid}-top"] = Rect(top_x_start, 0, top_x_end - top_x_start + 1, top)
                if bottom > 0:
                    result[f"{wid}-bottom"] = Rect(
                        bottom_x_start, sh - bottom, bottom_x_end - bottom_x_start + 1, bottom
                    )
                if left > 0:
                    result[f"{wid}-left"] = Rect(
                        0, left_y_start, left, left_y_end - left_y_start + 1
                    )
                if right > 0:
                    result[f"{wid}-right"] = Rect(
                        sw - right, right_y_start, right, right_y_end - right_y_start + 1
                    )
    return result


def _screen_size(display: str) -> tuple[int, int]:
    img = ImageGrab.grab()
    return img.size


def _annotate(
    img: Image.Image,
    overlays: list[WindowInfo],
    workarea: Rect,
    struts: dict[str, Rect],
    issues: list[str],
) -> Image.Image:
    draw = ImageDraw.Draw(img)
    # work area in cyan
    draw.rectangle(
        [(workarea.x, workarea.y), (workarea.right, workarea.bottom)],
        outline="cyan",
        width=4,
    )
    # struts in magenta
    for s in struts.values():
        draw.rectangle([(s.x, s.y), (s.right, s.bottom)], outline="magenta", width=3)
    # overlays in red
    for w in overlays:
        r = w.rect
        draw.rectangle([(r.x, r.y), (r.right, r.bottom)], outline="red", width=4)
    # issues block
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    text = "\n".join(issues) if issues else "OK — no placement issues detected"
    draw.rectangle([(20, img.height - 280), (img.width - 20, img.height - 20)], fill="black")
    draw.multiline_text((40, img.height - 270), text, fill="lime", font=font, spacing=4)
    return img


def check_placement(
    overlays: list[WindowInfo], workarea: Rect, struts: dict[str, Rect], screen_size: tuple[int, int]
) -> list[str]:
    issues: list[str] = []
    sw, sh = screen_size
    for w in overlays:
        r = w.rect
        # Out of screen bounds?
        if r.x < 0 or r.y < 0 or r.right > sw or r.bottom > sh:
            issues.append(f"OFF-SCREEN  {w.wid}  rect=({r.x},{r.y} {r.w}x{r.h}) screen={sw}x{sh}")
        # Overlap with panel/dock struts
        for sname, srect in struts.items():
            inter = r.intersection(srect)
            if inter is not None:
                issues.append(
                    f"PANEL OVERLAP  {w.wid}  hits {sname} by {inter.w}x{inter.h} px at ({inter.x},{inter.y})"
                )
        # Outside reported work area?
        wa_overlap_top = max(0, workarea.y - r.y)
        if wa_overlap_top > 0:
            issues.append(
                f"ABOVE WORKAREA  {w.wid}  top={r.y} workarea_top={workarea.y} (gap={wa_overlap_top}px above)"
            )
    # Mutual overlap
    for i, a in enumerate(overlays):
        for b in overlays[i + 1 :]:
            inter = a.rect.intersection(b.rect)
            if inter is not None:
                issues.append(
                    f"OVERLAP  {a.wid} ↔ {b.wid}  by {inter.w}x{inter.h} px at ({inter.x},{inter.y})"
                )
    return issues


def report(display: str, save_path: Path | None = None) -> int:
    img = ImageGrab.grab()
    sw, sh = img.size
    windows = list_windows(display)
    overlays = find_overlays(windows)
    workarea = get_workarea(display)
    struts = get_struts(display)
    issues = check_placement(overlays, workarea, struts, (sw, sh))

    print(f"display={display}  screen={sw}x{sh}")
    print(f"workarea=({workarea.x},{workarea.y} {workarea.w}x{workarea.h})")
    if struts:
        print("struts:")
        for sname, srect in struts.items():
            print(f"  {sname}: ({srect.x},{srect.y} {srect.w}x{srect.h})")
    print(f"overlays: {len(overlays)}")
    for w in overlays:
        print(f"  {w.wid}  pos=({w.rect.x},{w.rect.y}) size={w.rect.w}x{w.rect.h}  name={w.name!r}")
    if issues:
        print("issues:")
        for line in issues:
            print(f"  {line}")
    else:
        print("issues: none")

    if save_path is not None:
        annotated = _annotate(img, overlays, workarea, struts, issues)
        annotated.save(save_path)
        print(f"saved annotated screenshot to {save_path}")

    return 1 if issues else 0


def main() -> None:
    p = argparse.ArgumentParser(description="driftwall overlay placement checker")
    p.add_argument("--display", default=_pick_display(), help="X display (default: auto-detect)")
    p.add_argument("--watch", action="store_true", help="re-run every 5 seconds")
    p.add_argument("--save", type=Path, help="save annotated screenshot to this path")
    args = p.parse_args()

    if args.watch:
        try:
            while True:
                rc = report(args.display, args.save)
                print(f"---  exit={rc}  ---", flush=True)
                time.sleep(5)
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        sys.exit(report(args.display, args.save))


if __name__ == "__main__":
    main()
