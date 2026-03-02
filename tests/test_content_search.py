"""Unit tests for driftwall.content_search — query building."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from driftwall.content_search import build_image_query, get_content_for_image, search_content
from driftwall.config import Config
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


class TestSearchContent(unittest.TestCase):
    def test_search_content_applies_in_where_filter_for_multiple_sources(self):
        fake_collection = MagicMock()
        fake_collection.query.return_value = {
            "ids": [["a::0"]],
            "documents": [["hello"]],
            "metadatas": [[{"source_path": "a", "source_type": "text", "chunk_index": 0}]],
        }

        class _FakeOllamaClient:
            def __init__(self, host: str) -> None:
                self.host = host

            def embed(self, model: str, input: list[str]):
                return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])

        fake_ollama = SimpleNamespace(Client=_FakeOllamaClient)
        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            search_content(
                query_text="stormy sea",
                collection=fake_collection,
                embed_model="nomic-embed-text",
                host="http://localhost:11434",
                source_paths=["a", "b", "c"],
            )

        kwargs = fake_collection.query.call_args.kwargs
        self.assertEqual(kwargs["where"], {"source_path": {"$in": ["a", "b", "c"]}})

    def test_search_content_applies_equals_filter_for_single_source(self):
        fake_collection = MagicMock()
        fake_collection.query.return_value = {
            "ids": [["a::0"]],
            "documents": [["hello"]],
            "metadatas": [[{"source_path": "a", "source_type": "text", "chunk_index": 0}]],
        }

        class _FakeOllamaClient:
            def __init__(self, host: str) -> None:
                self.host = host

            def embed(self, model: str, input: list[str]):
                return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])

        fake_ollama = SimpleNamespace(Client=_FakeOllamaClient)
        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            search_content(
                query_text="stormy sea",
                collection=fake_collection,
                embed_model="nomic-embed-text",
                host="http://localhost:11434",
                source_paths=["a"],
            )

        kwargs = fake_collection.query.call_args.kwargs
        self.assertEqual(kwargs["where"], {"source_path": "a"})


class TestGetContentForImage(unittest.TestCase):
    def test_uses_random_subset_of_sources_when_configured(self):
        config = Config()
        config.dynamic_overlay.random_source_subset_size = 3
        image = ImageRecord(one_sentence="A snowy mountain")

        with patch("driftwall.content_search.get_chroma_client", return_value=object()), patch(
            "driftwall.content_search.get_collection", return_value=object()
        ), patch(
            "driftwall.content_search.list_content_source_paths",
            return_value=["s1", "s2", "s3", "s4", "s5"],
        ), patch(
            "driftwall.content_search.random.sample",
            return_value=["s2", "s4", "s5"],
        ), patch(
            "driftwall.content_search.search_content",
            return_value=[],
        ) as mock_search:
            get_content_for_image(
                image=image,
                chroma_path=Path("/tmp/chroma"),
                config=config,
                n_results=7,
            )

        self.assertEqual(mock_search.call_args.kwargs["source_paths"], ["s2", "s4", "s5"])


if __name__ == "__main__":
    unittest.main()
