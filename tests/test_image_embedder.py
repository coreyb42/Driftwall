"""Unit tests for driftwall.image_embedder."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from driftwall.db import ImageRecord, init_db, upsert_image
from driftwall.image_embedder import EmbedResult, compute_embedding, embed_all_images


def _fake_ollama(embeddings: list[list[float]]):
    """Return a fake ollama module whose Client().embed() cycles through embeddings."""
    call_count = iter(embeddings)

    class _FakeClient:
        def __init__(self, host: str) -> None:
            pass

        def embed(self, model: str, input: list[str]):
            return SimpleNamespace(embeddings=[next(call_count)])

    return SimpleNamespace(Client=_FakeClient)


def _make_image(file_hash: str, **kwargs) -> ImageRecord:
    defaults = dict(
        path=f"/img/{file_hash}.jpg",
        file_hash=file_hash,
        file_size=1000,
        classified_at="2024-01-01T00:00:00+00:00",
        last_seen_at="2024-01-01T00:00:00+00:00",
    )
    defaults.update(kwargs)
    return ImageRecord(**defaults)


class TestComputeEmbedding(unittest.TestCase):
    def test_returns_embedding_from_ollama(self):
        fake_ollama = _fake_ollama([[0.1, 0.2, 0.3]])
        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            result = compute_embedding("hello world", "nomic-embed-text", "http://localhost:11434")
        self.assertEqual(result, [0.1, 0.2, 0.3])


class TestEmbedAllImages(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        init_db(self.db_path)

    def tearDown(self):
        self._tmp.cleanup()

    def _insert(self, image: ImageRecord) -> None:
        upsert_image(self.db_path, image)

    def test_embeds_images_missing_embeddings(self):
        self._insert(_make_image("hash1", one_paragraph="A sunny meadow"))
        self._insert(_make_image("hash2", one_paragraph="A stormy sea"))

        fake_ollama = _fake_ollama([[0.1] * 3, [0.2] * 3])
        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            result = embed_all_images(
                db_path=self.db_path,
                embed_model="nomic-embed-text",
                host="http://localhost:11434",
            )

        self.assertEqual(result.total, 2)
        self.assertEqual(result.embedded, 2)
        self.assertEqual(result.skipped_no_text, 0)
        self.assertEqual(result.errors, 0)

    def test_skips_images_with_no_text(self):
        self._insert(_make_image("hash1"))  # no text fields set

        result = embed_all_images(
            db_path=self.db_path,
            embed_model="nomic-embed-text",
            host="http://localhost:11434",
        )

        self.assertEqual(result.total, 1)
        self.assertEqual(result.skipped_no_text, 1)
        self.assertEqual(result.embedded, 0)

    def test_skips_already_embedded_without_force(self):
        from driftwall.db import upsert_image_embedding
        self._insert(_make_image("hash1", one_paragraph="A sunny meadow"))
        upsert_image_embedding(self.db_path, "hash1", "nomic-embed-text", [0.1, 0.2])

        result = embed_all_images(
            db_path=self.db_path,
            embed_model="nomic-embed-text",
            host="http://localhost:11434",
        )

        self.assertEqual(result.total, 0)

    def test_force_reembeds_existing(self):
        from driftwall.db import upsert_image_embedding
        self._insert(_make_image("hash1", one_paragraph="A sunny meadow"))
        upsert_image_embedding(self.db_path, "hash1", "nomic-embed-text", [0.1, 0.2])

        fake_ollama = _fake_ollama([[0.9, 0.9]])
        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            result = embed_all_images(
                db_path=self.db_path,
                embed_model="nomic-embed-text",
                host="http://localhost:11434",
                force=True,
            )

        self.assertEqual(result.total, 1)
        self.assertEqual(result.embedded, 1)

    def test_errors_are_counted_and_skipped(self):
        self._insert(_make_image("hash1", one_paragraph="A sunny meadow"))

        class _FailClient:
            def __init__(self, host):
                pass
            def embed(self, model, input):
                raise RuntimeError("Ollama down")

        fake_ollama = SimpleNamespace(Client=_FailClient)
        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            result = embed_all_images(
                db_path=self.db_path,
                embed_model="nomic-embed-text",
                host="http://localhost:11434",
            )

        self.assertEqual(result.errors, 1)
        self.assertEqual(result.embedded, 0)

    def test_progress_callback_called(self):
        self._insert(_make_image("hash1", one_paragraph="A sunny meadow"))

        calls: list[tuple[int, int]] = []
        fake_ollama = _fake_ollama([[0.1] * 3])
        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            embed_all_images(
                db_path=self.db_path,
                embed_model="nomic-embed-text",
                host="http://localhost:11434",
                progress_callback=lambda done, total: calls.append((done, total)),
            )

        # Should be called at least once with final (total, total)
        self.assertIn((1, 1), calls)


if __name__ == "__main__":
    unittest.main()
