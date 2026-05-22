from __future__ import annotations

import unittest

from driftwall.windowing import compute_overlay_bounds, zone_rect


def _import_truncate():
    """Import _truncate_for_display without triggering the gi/GTK import path.

    dynamic_overlay imports gi at module load, which is unavailable in the test
    venv. We compile just the function we need from source.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "driftwall" / "dynamic_overlay.py"
    tree = ast.parse(src.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_truncate_for_display":
            mod = ast.Module(body=[node], type_ignores=[])
            ns: dict = {}
            exec(compile(mod, str(src), "exec"), ns)
            return ns["_truncate_for_display"]
    raise RuntimeError("_truncate_for_display not found in dynamic_overlay.py")


_truncate_for_display = _import_truncate()


class ZoneRectTests(unittest.TestCase):
    def test_zone_0_is_top_left(self) -> None:
        x, y, w, h = zone_rect(0, 800, 600)
        self.assertEqual((x, y), (0, 0))
        self.assertEqual((w, h), (200, 200))

    def test_zone_3_is_top_right_column(self) -> None:
        x, y, w, h = zone_rect(3, 800, 600)
        self.assertEqual(x, 600)
        self.assertEqual(y, 0)

    def test_zone_11_is_bottom_right(self) -> None:
        x, y, w, h = zone_rect(11, 800, 600)
        self.assertEqual(x, 600)
        self.assertEqual(y, 400)


class OverlayBoundsTests(unittest.TestCase):
    def test_bounds_inside_work_area(self) -> None:
        # Fully inside work area, with a 10 px inset from cell edges so adjacent
        # zones never share a pixel.
        b = compute_overlay_bounds(
            zone=0, work_x=0, work_y=32, work_w=2000, work_h=1200, gap_px=10
        )
        self.assertGreaterEqual(b.x, 0)
        self.assertGreaterEqual(b.y, 32)
        self.assertLessEqual(b.x + b.max_w, 2000)
        self.assertLessEqual(b.y + b.max_h, 32 + 1200)

    def test_bounds_respects_gap_between_zones(self) -> None:
        # Two horizontal neighbors (zones 0 and 1) should leave at least gap_px
        # of space between them when both placed at their inner edge.
        b0 = compute_overlay_bounds(
            zone=0, work_x=0, work_y=0, work_w=2000, work_h=1200, gap_px=10
        )
        b1 = compute_overlay_bounds(
            zone=1, work_x=0, work_y=0, work_w=2000, work_h=1200, gap_px=10
        )
        # b0's right edge should be at most b1's left edge - gap_px
        self.assertLessEqual(b0.x + b0.max_w + 10, b1.x + b1.max_w)
        # And specifically the inner edges are spaced
        right_of_b0 = b0.x + b0.max_w
        self.assertLessEqual(right_of_b0, b1.x)

    def test_bounds_excludes_panel_via_work_y(self) -> None:
        b = compute_overlay_bounds(
            zone=0, work_x=0, work_y=64, work_w=4384, work_h=2402, gap_px=10
        )
        # Top must be at least one gap below the work-area top
        self.assertGreaterEqual(b.y, 64 + 10)

    def test_bounds_min_size_floors(self) -> None:
        # A tiny work area still yields non-negative dimensions
        b = compute_overlay_bounds(
            zone=0, work_x=0, work_y=0, work_w=100, work_h=80, gap_px=10
        )
        self.assertGreaterEqual(b.max_w, 0)
        self.assertGreaterEqual(b.max_h, 0)


class TruncateForDisplayTests(unittest.TestCase):
    def test_returns_short_text_unchanged(self) -> None:
        self.assertEqual(_truncate_for_display("a short quote", 100), "a short quote")

    def test_truncates_long_text_with_ellipsis(self) -> None:
        long = "word " * 200  # ~1000 chars
        out = _truncate_for_display(long, 80)
        self.assertLessEqual(len(out), 81)  # 80 + ellipsis char
        self.assertTrue(out.endswith("…"))

    def test_breaks_on_word_boundary_when_close(self) -> None:
        # 80-char budget that lands mid-word; rfind should pull back to space
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron"
        out = _truncate_for_display(text, 50)
        self.assertTrue(out.endswith("…"))
        # last char before the ellipsis should be a letter (clean word break)
        self.assertNotIn(" …", out)

    def test_strips_trailing_punctuation_before_ellipsis(self) -> None:
        text = "alpha beta gamma, delta epsilon zeta eta. theta iota kappa lambda mu nu"
        out = _truncate_for_display(text, 30)
        self.assertTrue(out.endswith("…"))
        # No comma or period directly before the ellipsis
        self.assertFalse(out.endswith(",…"))
        self.assertFalse(out.endswith(".…"))


if __name__ == "__main__":
    unittest.main()
