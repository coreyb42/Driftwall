"""Unit tests for driftwall.content_search — query building."""

import unittest

from driftwall.content_search import build_image_query
from driftwall.db import ImageRecord


class TestBuildImageQueryFull(unittest.TestCase):
    def test_one_paragraph_used_directly(self):
        """When one_paragraph is set it is returned as-is; other fields are not appended."""
        image = ImageRecord(
            one_paragraph="A stormy seascape at dusk",
            one_sentence="Dramatic waves crash on rocky shores",
            keywords="ocean|storm|waves|drama",
            mood="melancholic|tense",
            primary_subject="ocean",
            setting="coastal",
        )
        query = build_image_query(image)
        self.assertEqual(query, "A stormy seascape at dusk")

    def test_fallback_fields_used_when_no_paragraph(self):
        """When one_paragraph is absent, remaining fields are assembled into the query."""
        image = ImageRecord(
            one_sentence="Dramatic waves crash on rocky shores",
            keywords="ocean|storm|waves|drama",
            mood="melancholic|tense",
            primary_subject="ocean",
            setting="coastal",
        )
        query = build_image_query(image)
        self.assertIn("Dramatic waves", query)
        self.assertIn("ocean storm waves drama", query)
        self.assertIn("melancholic tense", query)
        self.assertIn("coastal", query)

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
