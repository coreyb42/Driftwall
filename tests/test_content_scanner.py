"""Unit tests for driftwall.content_scanner — chunking and CSV parsing."""

import csv
import io
import tempfile
import unittest
from pathlib import Path

from driftwall.content_scanner import chunk_text, parse_csv_quotes
from driftwall.content_store import ContentChunk


class TestChunkTextBasic(unittest.TestCase):
    def test_short_paragraphs_each_become_one_chunk(self):
        # Use paragraphs >= 100 chars so they are not merged
        p1 = "A beautiful sunset painted the horizon with shades of orange and pink over the vast ocean waters below."
        p2 = "The waves crashed gently on the shore while seagulls called out above the white sandy beautiful beaches."
        self.assertGreaterEqual(len(p1), 100)
        self.assertGreaterEqual(len(p2), 100)
        text = f"{p1}\n\n{p2}"
        chunks = chunk_text(text, "test.txt")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].text, p1)
        self.assertEqual(chunks[1].text, p2)

    def test_chunk_source_type_is_text(self):
        chunks = chunk_text("Hello world.", "test.txt")
        self.assertTrue(all(c.source_type == "text" for c in chunks))

    def test_chunk_ids_include_source_path(self):
        p1 = "Hello world, this is a longer paragraph that exceeds the one hundred character minimum threshold here."
        p2 = "Foo bar, and this is also a longer paragraph that exceeds the one hundred character minimum threshold."
        self.assertGreaterEqual(len(p1), 100)
        self.assertGreaterEqual(len(p2), 100)
        chunks = chunk_text(f"{p1}\n\n{p2}", "my/source.txt")
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(c.id.startswith("my/source.txt::") for c in chunks))
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[1].chunk_index, 1)

    def test_source_title_in_metadata(self):
        chunks = chunk_text("Some text.", "/path/to/mybook.txt")
        self.assertEqual(chunks[0].metadata["source_title"], "mybook")

    def test_empty_text_returns_no_chunks(self):
        self.assertEqual(chunk_text("", "empty.txt"), [])

    def test_whitespace_only_returns_no_chunks(self):
        self.assertEqual(chunk_text("   \n\n   ", "empty.txt"), [])


class TestChunkTextLongParagraph(unittest.TestCase):
    def test_long_paragraph_split_on_sentence_boundary(self):
        # Build a paragraph > 600 chars with clear sentence boundaries
        sentences = [f"This is sentence number {i} and it has some padding words here." for i in range(12)]
        long_para = " ".join(sentences)
        self.assertGreater(len(long_para), 600)
        chunks = chunk_text(long_para, "long.txt")
        self.assertGreater(len(chunks), 1)
        # Each chunk should be <= 600 chars
        for c in chunks:
            self.assertLessEqual(len(c.text), 610, f"Chunk too long: {len(c.text)}")

    def test_long_paragraph_preserves_all_text(self):
        sentences = [f"Sentence {i} with enough words to make it realistic and meaningful." for i in range(10)]
        long_para = " ".join(sentences)
        chunks = chunk_text(long_para, "long.txt")
        reconstructed = " ".join(c.text for c in chunks)
        # All sentence starts should appear somewhere in the reconstructed text
        for s in sentences:
            self.assertIn(s[:20], reconstructed)


class TestChunkTextTinyMerged(unittest.TestCase):
    def test_tiny_paragraphs_merged_with_next(self):
        # Two short paragraphs (< 100 chars each) should be merged
        text = "Short line.\n\nAnother short line."
        chunks = chunk_text(text, "tiny.txt")
        # They should be merged into a single chunk
        self.assertEqual(len(chunks), 1)
        self.assertIn("Short line.", chunks[0].text)
        self.assertIn("Another short line.", chunks[0].text)

    def test_tiny_merging_does_not_exceed_600(self):
        # Many tiny paragraphs: they should be batched without exceeding 600 chars
        tiny = "\n\n".join([f"Line {i}." for i in range(30)])
        chunks = chunk_text(tiny, "many_tiny.txt")
        for c in chunks:
            self.assertLessEqual(len(c.text), 620)


class TestParseCsvQuotes(unittest.TestCase):
    def _make_csv(self, rows: list[dict], fieldnames: list[str]) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp.flush()
        tmp.close()
        return Path(tmp.name)

    def test_parse_csv_quotes(self):
        path = self._make_csv(
            [
                {"text": "The world is full of magic things.", "author": "W.B. Yeats", "date": "1938", "source": ""},
                {"text": "To be or not to be.", "author": "Shakespeare", "date": "", "source": "Hamlet"},
            ],
            ["text", "author", "date", "source"],
        )
        chunks = parse_csv_quotes(path)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].text, "The world is full of magic things.")
        self.assertEqual(chunks[0].metadata["author"], "W.B. Yeats")
        self.assertEqual(chunks[0].metadata["date"], "1938")
        self.assertNotIn("source", chunks[0].metadata)  # empty → omitted
        self.assertEqual(chunks[1].source_type, "quote")
        self.assertEqual(chunks[1].metadata["source"], "Hamlet")
        path.unlink()

    def test_parse_csv_missing_optional_columns(self):
        path = self._make_csv(
            [{"text": "Only text column here."}],
            ["text"],
        )
        chunks = parse_csv_quotes(path)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "Only text column here.")
        self.assertEqual(chunks[0].metadata, {})
        path.unlink()

    def test_parse_csv_empty_rows_skipped(self):
        path = self._make_csv(
            [{"text": "Real quote."}, {"text": ""}],
            ["text"],
        )
        chunks = parse_csv_quotes(path)
        self.assertEqual(len(chunks), 1)
        path.unlink()

    def test_parse_csv_chunk_ids_include_source_path(self):
        path = self._make_csv([{"text": "Hello."}], ["text"])
        chunks = parse_csv_quotes(path)
        self.assertTrue(chunks[0].id.startswith(str(path)))
        path.unlink()


if __name__ == "__main__":
    unittest.main()
