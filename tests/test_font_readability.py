from __future__ import annotations

import unittest
from pathlib import Path

from driftwall.font_readability import (
    NAME_REJECT_PATTERNS,
    ReadabilityVerdict,
    classify_font,
    is_readable_body_font,
)


class FontReadabilityTests(unittest.TestCase):
    def test_name_pattern_rejects_stencil(self) -> None:
        path = Path("/fonts/Stencil/Big_Shoulders_Stencil/static/BigShouldersStencil_60pt-ExtraLight.ttf")
        v = classify_font(path)
        self.assertFalse(v.readable)
        self.assertIn("stencil", v.reason.lower())

    def test_name_pattern_rejects_decorative_words(self) -> None:
        for substring in ["Stencil", "Decorative", "Display", "Brush", "Handwriting", "Dingbat", "Symbol"]:
            with self.subTest(substring=substring):
                path = Path(f"/fonts/Whatever/{substring}Sample-Regular.ttf")
                v = classify_font(path)
                self.assertFalse(v.readable, f"{substring} should be rejected")

    def test_path_segment_rejects_category(self) -> None:
        path = Path("/fonts/Medieval/SomeFont-Regular.ttf")
        v = classify_font(path)
        self.assertFalse(v.readable)
        self.assertIn("medieval", v.reason.lower())

    def test_extra_light_weight_rejected_for_body(self) -> None:
        # ExtraLight + larger optical size makes for unreadable body text on a wallpaper
        path = Path("/fonts/Sans/SomeFamily/Family-ExtraLight.ttf")
        v = classify_font(path)
        self.assertFalse(v.readable)
        self.assertIn("weight", v.reason.lower())

    def test_thin_weight_rejected_for_body(self) -> None:
        path = Path("/fonts/Sans/SomeFamily/Family-Thin.ttf")
        v = classify_font(path)
        self.assertFalse(v.readable)

    def test_plain_serif_accepted(self) -> None:
        path = Path("/fonts/Serif/Lora/Lora-Regular.ttf")
        v = classify_font(path)
        self.assertTrue(v.readable, f"unexpected rejection: {v.reason}")

    def test_italic_accepted(self) -> None:
        path = Path("/fonts/Serif/Lora/Lora-Italic.ttf")
        v = classify_font(path)
        self.assertTrue(v.readable)

    def test_helper_returns_bool(self) -> None:
        good = Path("/fonts/Serif/Lora/Lora-Regular.ttf")
        bad = Path("/fonts/Stencil/X/X-Stencil.ttf")
        self.assertTrue(is_readable_body_font(good))
        self.assertFalse(is_readable_body_font(bad))

    def test_verdict_dataclass_fields(self) -> None:
        v = ReadabilityVerdict(readable=True, reason="ok")
        self.assertTrue(v.readable)
        self.assertEqual(v.reason, "ok")

    def test_reject_patterns_are_compiled(self) -> None:
        # Spot check at least one known reject substring is in the patterns
        all_text = " ".join(NAME_REJECT_PATTERNS).lower()
        self.assertIn("stencil", all_text)
        self.assertIn("display", all_text)


if __name__ == "__main__":
    unittest.main()
