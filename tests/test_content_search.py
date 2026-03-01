"""Unit tests for driftwall.content_search — query building."""

import unittest

from driftwall.content_search import build_image_query
from driftwall.db import ImageRecord


class TestBuildImageQueryFull(unittest.TestCase):
    def test_all_fields_present_in_query(self):
        image = ImageRecord(
            one_paragraph="A stormy seascape at dusk",
            one_sentence="Dramatic waves crash on rocky shores",
            keywords="ocean|storm|waves|drama",
            mood="melancholic|tense",
            primary_subject="ocean",
            setting="coastal",
            season="autumn",
            time_of_day="dusk",
            dominant_colors="grey|blue|white",
        )
        query = build_image_query(image)
        self.assertIn("stormy seascape at dusk", query)
        self.assertIn("Dramatic waves", query)
        self.assertIn("ocean storm waves drama", query)
        self.assertIn("melancholic tense", query)
        self.assertIn("coastal", query)
        self.assertIn("autumn", query)
        self.assertIn("dusk", query)
        self.assertIn("grey blue white", query)

    def test_pipe_delimiters_replaced_with_spaces(self):
        image = ImageRecord(keywords="fog|mist|morning")
        query = build_image_query(image)
        self.assertNotIn("|", query)
        self.assertIn("fog mist morning", query)


class TestBuildImageQuerySparse(unittest.TestCase):
    def test_only_one_sentence_present(self):
        image = ImageRecord(one_sentence="A lone tree on a hill")
        query = build_image_query(image)
        self.assertIn("A lone tree on a hill", query)
        # Should not crash when other fields are None
        self.assertIsInstance(query, str)

    def test_all_none_fields_returns_empty_or_short(self):
        image = ImageRecord()
        query = build_image_query(image)
        self.assertIsInstance(query, str)
        # All fields are None/empty, so query should be essentially empty
        self.assertEqual(query.strip(), "")

    def test_none_fields_do_not_appear_as_none_string(self):
        image = ImageRecord(one_sentence="Beautiful sunrise", season=None)
        query = build_image_query(image)
        self.assertNotIn("None", query)


if __name__ == "__main__":
    unittest.main()
