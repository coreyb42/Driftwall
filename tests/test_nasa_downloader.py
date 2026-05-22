"""Unit tests for nasa_downloader helpers."""

import unittest
from pathlib import Path

from driftwall.nasa_downloader import (
    NasaDownloadResult,
    _clean_description,
    build_nasa_context,
    nasa_infer_mission,
    nasa_output_subdir,
)


class TestNasaInferMission(unittest.TestCase):
    def test_apollo_in_keywords(self):
        self.assertEqual(nasa_infer_mission(["Apollo 11", "Moon Landing"], ""), "apollo")

    def test_apollo_in_title(self):
        self.assertEqual(nasa_infer_mission([], "Apollo 17 Lunar Surface"), "apollo")

    def test_hubble(self):
        self.assertEqual(nasa_infer_mission(["Hubble Space Telescope"], "Nebula"), "hubble")

    def test_jwst_keyword(self):
        self.assertEqual(nasa_infer_mission(["JWST", "galaxies"], "Deep Field"), "jwst")

    def test_james_webb_title(self):
        self.assertEqual(nasa_infer_mission([], "James Webb Space Telescope Deep Field"), "jwst")

    def test_iss(self):
        self.assertEqual(nasa_infer_mission(["ISS", "Expedition 70"], ""), "iss")

    def test_international_space_station(self):
        self.assertEqual(
            nasa_infer_mission(["International Space Station"], ""),
            "iss",
        )

    def test_shuttle(self):
        self.assertEqual(nasa_infer_mission(["Space Shuttle", "Discovery"], ""), "shuttle")

    def test_sts_prefix(self):
        self.assertEqual(nasa_infer_mission(["STS-135", "Atlantis"], "Final Mission"), "shuttle")

    def test_mars(self):
        self.assertEqual(nasa_infer_mission(["Mars", "Curiosity"], "Surface"), "curiosity")

    def test_perseverance_beats_mars(self):
        # perseverance appears before mars in _MISSION_PATTERNS so it takes priority
        self.assertEqual(
            nasa_infer_mission(["Perseverance", "Mars 2020"], "Jezero Crater"),
            "perseverance",
        )

    def test_moon_keyword(self):
        self.assertEqual(nasa_infer_mission(["Moon", "Crater"], "Lunar Surface"), "moon")

    def test_lunar_keyword(self):
        self.assertEqual(nasa_infer_mission(["Lunar Reconnaissance Orbiter"], ""), "moon")

    def test_new_horizons(self):
        self.assertEqual(nasa_infer_mission(["New Horizons", "Pluto"], "Flyby"), "new-horizons")

    def test_fallback_to_first_keyword(self):
        mission = nasa_infer_mission(["Astrophysics"], "Generic Image")
        self.assertEqual(mission, "astrophysics")

    def test_fallback_sanitizes_spaces(self):
        mission = nasa_infer_mission(["Solar Wind Study"], "")
        self.assertNotIn(" ", mission)

    def test_no_keywords_no_match_is_misc(self):
        self.assertEqual(nasa_infer_mission([], "Unrecognized"), "misc")

    def test_empty_inputs_is_misc(self):
        self.assertEqual(nasa_infer_mission([], ""), "misc")

    def test_keywords_case_insensitive(self):
        self.assertEqual(nasa_infer_mission(["APOLLO"], ""), "apollo")

    def test_title_case_insensitive(self):
        self.assertEqual(nasa_infer_mission([], "HUBBLE DEEP FIELD"), "hubble")

    def test_artemis(self):
        self.assertEqual(nasa_infer_mission(["Artemis I"], "Moon Mission"), "artemis")

    def test_voyager(self):
        self.assertEqual(nasa_infer_mission(["Voyager 2"], "Jupiter Flyby"), "voyager")

    def test_cassini(self):
        self.assertEqual(nasa_infer_mission(["Cassini", "Saturn"], "Ring System"), "cassini")

    def test_juno(self):
        self.assertEqual(nasa_infer_mission(["Juno", "Jupiter"], "Great Red Spot"), "juno")


class TestNasaOutputSubdir(unittest.TestCase):
    def test_basic(self):
        base = Path("/output/NASA")
        result = nasa_output_subdir(base, "apollo")
        self.assertEqual(result, Path("/output/NASA/apollo"))

    def test_misc(self):
        base = Path("/tmp/nasa")
        self.assertEqual(nasa_output_subdir(base, "misc"), Path("/tmp/nasa/misc"))


class TestCleanDescription(unittest.TestCase):
    def test_strips_html_tags(self):
        result = _clean_description('<b>Title</b> and <a href="x">link</a> text')
        self.assertNotIn("<b>", result)
        self.assertNotIn("<a", result)
        self.assertIn("Title", result)
        self.assertIn("text", result)

    def test_decodes_html_entities(self):
        result = _clean_description("Hubble&rsquo;s view &amp; more")
        self.assertIn("’", result)  # right single quote
        self.assertIn("&", result)

    def test_truncates_at_word_boundary(self):
        long_text = "word " * 200
        result = _clean_description(long_text, max_chars=50)
        self.assertLessEqual(len(result), 55)  # some tolerance for the ellipsis
        self.assertTrue(result.endswith("…"))

    def test_short_text_unchanged(self):
        text = "A short description."
        self.assertEqual(_clean_description(text), text)

    def test_collapses_whitespace(self):
        result = _clean_description("word   \n\t  another")
        self.assertEqual(result, "word another")


class TestBuildNasaContext(unittest.TestCase):
    def test_includes_title(self):
        ctx = build_nasa_context("Ring Nebula", "", [])
        self.assertIn("Ring Nebula", ctx)

    def test_includes_cleaned_description(self):
        ctx = build_nasa_context("Title", "<b>Stars</b> and galaxies", [])
        self.assertIn("Stars", ctx)
        self.assertNotIn("<b>", ctx)

    def test_includes_keywords(self):
        ctx = build_nasa_context("T", "", ["hubble", "nebula"])
        self.assertIn("hubble", ctx)
        self.assertIn("nebula", ctx)

    def test_excludes_url_keywords(self):
        ctx = build_nasa_context("T", "", ["http://nasa.gov/foo", "nebula"])
        self.assertNotIn("nasa.gov", ctx)
        self.assertIn("nebula", ctx)

    def test_includes_photographer(self):
        ctx = build_nasa_context("T", "", [], photographer="NASA/ESA")
        self.assertIn("NASA/ESA", ctx)

    def test_date_truncated_to_date(self):
        ctx = build_nasa_context("T", "", [], date_created="2023-07-12T00:00:00Z")
        self.assertIn("2023-07-12", ctx)
        self.assertNotIn("T00:00:00Z", ctx)

    def test_empty_inputs_produce_empty_string(self):
        ctx = build_nasa_context("", "", [])
        self.assertEqual(ctx, "")

    def test_empty_description_omitted(self):
        ctx = build_nasa_context("Ring Nebula", "", [])
        self.assertNotIn("Description:", ctx)


class TestNasaDownloadResult(unittest.TestCase):
    def test_defaults_zero(self):
        r = NasaDownloadResult()
        self.assertEqual(r.downloaded, 0)
        self.assertEqual(r.skipped_existing, 0)
        self.assertEqual(r.skipped_not_landscape, 0)
        self.assertEqual(r.skipped_has_people, 0)
        self.assertEqual(r.skipped_no_image, 0)
        self.assertEqual(r.errors, 0)


if __name__ == "__main__":
    unittest.main()
