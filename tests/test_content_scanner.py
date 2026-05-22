"""Unit tests for driftwall.content_scanner — chunking, CSV parsing, and binary extractors."""

import csv
import io
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from driftwall.content_scanner import (
    chunk_text,
    parse_csv_quotes,
    SUPPORTED_SUFFIXES,
    _extract_epub,
    _extract_pdf,
    _extract_html,
    _extract_docx,
    _extract_mobi,
    _read_text,
    _EXTRACTORS,
    _strip_gutenberg_boilerplate,
    _looks_like_list_block,
    _is_section_title,
    _soup_to_text,
    _MIN_CHUNK_CHARS,
)
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
        text = "Some text that is long enough to meet the minimum chunk length threshold here."
        chunks = chunk_text(text, "/path/to/mybook.txt")
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
        # Two short paragraphs (< 100 chars each) should be merged into one chunk
        p1 = "The old clock on the mantle had not moved in years."
        p2 = "Dust settled on every surface of the forgotten room."
        text = f"{p1}\n\n{p2}"
        chunks = chunk_text(text, "tiny.txt")
        self.assertEqual(len(chunks), 1)
        self.assertIn(p1, chunks[0].text)
        self.assertIn(p2, chunks[0].text)

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


class TestSupportedSuffixes(unittest.TestCase):
    def test_plain_text_always_present(self):
        for ext in (".txt", ".md", ".rst", ".csv"):
            self.assertIn(ext, SUPPORTED_SUFFIXES)

    def test_ebook_formats_present(self):
        for ext in (".epub", ".pdf", ".html", ".htm", ".docx", ".mobi"):
            self.assertIn(ext, SUPPORTED_SUFFIXES)

    def test_read_text_used_for_plain(self):
        for ext in (".txt", ".md", ".rst"):
            self.assertIs(_EXTRACTORS[ext], _read_text)


class TestExtractorImportErrors(unittest.TestCase):
    """Each binary extractor must raise ImportError when its library is absent."""

    def _missing(self, *module_names: str):
        """Context manager that hides the given modules from the import system."""
        return unittest.mock.patch.dict(sys.modules, {m: None for m in module_names})

    def test_epub_raises_import_error(self):
        with self._missing("ebooklib", "ebooklib.epub"):
            with self.assertRaises(ImportError):
                _extract_epub(Path("dummy.epub"))

    def test_pdf_raises_import_error(self):
        with self._missing("pypdf"):
            with self.assertRaises(ImportError):
                _extract_pdf(Path("dummy.pdf"))

    def test_html_raises_import_error(self):
        with self._missing("bs4"):
            with self.assertRaises(ImportError):
                _extract_html(Path("dummy.html"))

    def test_docx_raises_import_error(self):
        with self._missing("docx"):
            with self.assertRaises(ImportError):
                _extract_docx(Path("dummy.docx"))

    def test_mobi_raises_import_error(self):
        with self._missing("mobi"):
            with self.assertRaises(ImportError):
                _extract_mobi(Path("dummy.mobi"))


_HAS_BS4 = True
try:
    import bs4  # noqa: F401
except ImportError:
    _HAS_BS4 = False


@unittest.skipUnless(_HAS_BS4, "beautifulsoup4 not installed")
class TestExtractHtml(unittest.TestCase):
    def _write(self, html: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        )
        tmp.write(html)
        tmp.flush()
        tmp.close()
        return Path(tmp.name)

    def test_basic_html_extraction(self):
        path = self._write("<html><body><p>Hello world.</p></body></html>")
        try:
            text = _extract_html(path)
            self.assertIn("Hello world", text)
        finally:
            path.unlink()

    def test_script_and_style_stripped(self):
        path = self._write(
            "<html><head><style>body{color:red}</style></head>"
            "<body><script>alert(1)</script><p>Keep this.</p></body></html>"
        )
        try:
            text = _extract_html(path)
            self.assertNotIn("body{color:red}", text)
            self.assertNotIn("alert(1)", text)
            self.assertIn("Keep this", text)
        finally:
            path.unlink()

    def test_nav_and_footer_stripped(self):
        path = self._write(
            "<html><body><nav>Menu</nav><p>Content.</p><footer>Footer</footer></body></html>"
        )
        try:
            text = _extract_html(path)
            self.assertNotIn("Menu", text)
            self.assertNotIn("Footer", text)
            self.assertIn("Content", text)
        finally:
            path.unlink()


# ── Real-book excerpt tests ────────────────────────────────────────────────────

# Real excerpt from "Leaves of Grass" by Walt Whitman (Project Gutenberg)
_LEAVES_OF_GRASS_EXCERPT = """\
*** START OF THE PROJECT GUTENBERG EBOOK LEAVES OF GRASS ***

LEAVES OF GRASS

By Walt Whitman



     Come, said my soul,
     Such verses for my Body let us write, (for we are one,)
     That should I after return,
     Or, long, long hence, in other spheres,
     There to some group of mates the chants resuming,
     (Tallying Earth's soil, trees, winds, tumultuous waves,)
     Ever with pleas'd smile I may keep on,
     Ever and ever yet the verses owning--as, first, I here and now
     Signing for Soul and Body, set to them my name,

     Walt Whitman


BOOK I.  INSCRIPTIONS


One's-Self I Sing

  One's-self I sing, a simple separate person,
  Yet utter the word Democratic, the word En-Masse.

  Of physiology from top to toe I sing,
  Not physiognomy alone nor brain alone is worthy for the Muse, I say
      the Form complete is worthier far,
  The Female equally with the Male I sing.

  Of Life immense in passion, pulse, and power,
  Cheerful, for freest action form'd under the laws divine,
  The Modern Man I sing.


As I Ponder'd in Silence

  As I ponder'd in silence,
  Returning upon my poems, considering, lingering long,
  A Phantom arose before me with distrustful aspect,
  Terrible in beauty, age, and power,
  The genius of poets of old lands,
  As to me directing like flame its eyes,
  With finger pointing to many immortal songs,
  And menacing voice, What singest thou? it said,
  Know'st thou not there is but one theme for ever-enduring bards?
  And that is the theme of War, the fortune of battles,
  The making of perfect soldiers.
"""

# Real excerpt from "Romeo and Juliet" (Folger Shakespeare Library edition)
_ROMEO_CHARACTER_LIST = """\
Characters in the Play
======================
ROMEO
MONTAGUE, his father
LADY MONTAGUE, his mother
BENVOLIO, their kinsman
ABRAM, a Montague servingman
BALTHASAR, Romeo's servingman
JULIET
CAPULET, her father
LADY CAPULET, her mother
NURSE to Juliet
TYBALT, kinsman to the Capulets
PETRUCHIO, Tybalt's companion
"""

# Real excerpt of dialog from Romeo and Juliet
_ROMEO_DIALOG_EXCERPT = """\
SAMPSON  Gregory, on my word we'll not carry coals.

GREGORY  No, for then we should be colliers.

SAMPSON  I mean, an we be in choler, we'll draw.

GREGORY  Ay, while you live, draw your neck out of
collar.

SAMPSON  I strike quickly, being moved.

GREGORY  But thou art not quickly moved to strike.

SAMPSON  A dog of the house of Montague moves me.

GREGORY  To move is to stir, and to be valiant is to
stand. Therefore if thou art moved thou runn'st away.
"""

# Simulated MOBI-style HTML (matches what mobi + BeautifulSoup produces)
_MOBI_STYLE_HTML = """\
<html><body>
<p>Table of Contents</p>
<p>Title Page</p>
<p>OF MICE AND MEN</p>
<p>A few miles south of Soledad, the Salinas River drops in close to the hillside
bank and runs deep and green. The water is warm too, for it has slipped twinkling
over the yellow sands in the sunlight before reaching the narrow pool.</p>
<p>On one side of the river the golden foothill slopes curve up to the strong and
rocky Gabilan Mountains, but on the valley side the water is lined with trees—
willows fresh and green with every spring, carrying in their lower leaf junctures
the debris of the winter's flooding.</p>
<p>"We'll have a big vegetable patch and a rabbit hutch and chickens. And when it
rains in the winter, we'll just say the hell with goin' to work, and we'll build up
a fire in the stove and set around it an' listen to the rain comin' down on the
roof."</p>
</body></html>
"""

# Gutenberg boilerplate test
_GUTENBERG_WITH_TOC = """\
The Project Gutenberg eBook of The Adventures of Tom Sawyer

*** START OF THE PROJECT GUTENBERG EBOOK THE ADVENTURES OF TOM SAWYER ***

THE ADVENTURES OF TOM SAWYER
By Mark Twain

CONTENTS

CHAPTER I. Y-o-u-u Tom—Aunt Polly Decides Upon her Duty—Tom Practices Music
CHAPTER II. Strong Temptations—Strategic Movements—The Innocents Beguiled
CHAPTER III. Tom as a General—Triumphant Return Home—His Interior Fades

CHAPTER I.

"TOM!"

No answer.

"TOM!"

No answer.

"What's gone with that boy, I wonder? You TOM!"

No answer.

The old lady pulled her spectacles down and looked over them about the
room; then she put them up and looked out under them. She seldom or never
looked through them for so small a thing as a boy; they were her state pair,
the pride of her heart, and were built for "style," not service—she could
have seen through a pair of stove-lids just as well.

*** END OF THE PROJECT GUTENBERG EBOOK THE ADVENTURES OF TOM SAWYER ***
"""


class TestGutenbergBoilerplate(unittest.TestCase):
    def test_strips_header_and_footer(self):
        result = _strip_gutenberg_boilerplate(_GUTENBERG_WITH_TOC)
        self.assertNotIn("Project Gutenberg eBook", result)
        self.assertNotIn("END OF THE PROJECT GUTENBERG", result)
        # The chapter content should remain (case varies by book)
        self.assertIn("spectacles", result)

    def test_content_outside_markers_removed(self):
        text = "Before header.\n*** START OF THE PROJECT GUTENBERG EBOOK FOO ***\nContent here.\n*** END OF THE PROJECT GUTENBERG EBOOK FOO ***\nAfter footer."
        result = _strip_gutenberg_boilerplate(text)
        self.assertNotIn("Before header", result)
        self.assertNotIn("After footer", result)
        self.assertIn("Content here", result)

    def test_no_markers_returns_unchanged(self):
        text = "Just some regular text without any Gutenberg markers."
        self.assertEqual(_strip_gutenberg_boilerplate(text), text)

    def test_toc_entries_not_in_chunks(self):
        chunks = chunk_text(_GUTENBERG_WITH_TOC, "tom_sawyer.txt")
        chunk_texts = [c.text for c in chunks]
        for text in chunk_texts:
            self.assertNotIn("CHAPTER I. Y-o-u-u Tom", text)
            self.assertNotIn("CHAPTER II. Strong Temptations", text)

    def test_actual_prose_included(self):
        chunks = chunk_text(_GUTENBERG_WITH_TOC, "tom_sawyer.txt")
        all_text = " ".join(c.text for c in chunks)
        self.assertIn("spectacles", all_text)


class TestLeavesOfGrassChunking(unittest.TestCase):
    def setUp(self):
        self.chunks = chunk_text(_LEAVES_OF_GRASS_EXCERPT, "leaves.txt")
        self.all_text = " ".join(c.text for c in self.chunks)

    def test_no_standalone_poem_titles(self):
        """Poem titles like 'As I Ponder'd in Silence' should not appear as standalone chunks."""
        for chunk in self.chunks:
            self.assertNotEqual(chunk.text.strip(), "As I Ponder'd in Silence")
            self.assertNotEqual(chunk.text.strip(), "One's-Self I Sing")

    def test_poetry_stanzas_preserved(self):
        """Stanza line structure must be preserved (newlines intact)."""
        stanza_found = any(
            "One's-self I sing" in c.text and "\n" in c.text
            for c in self.chunks
        )
        self.assertTrue(stanza_found, "Poetry stanza line breaks should be preserved")

    def test_book_heading_excluded(self):
        """'BOOK I. INSCRIPTIONS' all-caps heading should be filtered."""
        self.assertNotIn("BOOK I.  INSCRIPTIONS", self.all_text)

    def test_gutenberg_header_excluded(self):
        """Project Gutenberg preamble should not appear in chunks."""
        self.assertNotIn("Project Gutenberg", self.all_text)

    def test_no_chunk_below_minimum_length(self):
        for chunk in self.chunks:
            self.assertGreaterEqual(
                len(chunk.text.strip()), _MIN_CHUNK_CHARS,
                f"Chunk too short: {repr(chunk.text)}"
            )

    def test_poem_content_preserved(self):
        """Actual poem content should be in the output."""
        self.assertIn("simple separate person", self.all_text)
        self.assertIn("ponder'd in silence", self.all_text)


class TestShakespeareChunking(unittest.TestCase):
    def test_character_list_excluded(self):
        """Multi-line character roster (avg < 25 chars/line, > 4 lines) should be skipped."""
        chunks = chunk_text(_ROMEO_CHARACTER_LIST, "romeo.txt")
        all_text = " ".join(c.text for c in chunks)
        # The character list block should produce no meaningful chunks
        self.assertEqual(len(chunks), 0)

    def test_dialog_exchanges_merged(self):
        """Short dialog lines should be merged into multi-line chunks."""
        chunks = chunk_text(_ROMEO_DIALOG_EXCERPT, "romeo.txt")
        self.assertGreater(len(chunks), 0)
        all_text = "\n".join(c.text for c in chunks)
        self.assertIn("GREGORY", all_text)
        self.assertIn("SAMPSON", all_text)

    def test_no_chunk_below_minimum(self):
        chunks = chunk_text(_ROMEO_DIALOG_EXCERPT, "romeo.txt")
        for chunk in chunks:
            self.assertGreaterEqual(len(chunk.text.strip()), _MIN_CHUNK_CHARS)


class TestListBlockDetection(unittest.TestCase):
    def test_character_roster_is_list_block(self):
        roster = "ROMEO\nMONTAGUE, his father\nLADY MONTAGUE, his mother\nBENVOLIO, their kinsman\nABRAM, a Montague servingman"
        self.assertTrue(_looks_like_list_block(roster))

    def test_poetry_stanza_not_list_block(self):
        stanza = "  One's-self I sing, a simple separate person,\n  Yet utter the word Democratic, the word En-Masse.\n  Of physiology from top to toe I sing,\n  The Female equally with the Male I sing."
        self.assertFalse(_looks_like_list_block(stanza))

    def test_short_block_not_list(self):
        # Only 3 lines — not enough to be a list block
        short = "ROMEO\nJULIET\nMERCUTIO"
        self.assertFalse(_looks_like_list_block(short))

    def test_prose_paragraph_not_list_block(self):
        prose = "The river runs along the edge of the valley.\nIn summer it dries to a trickle.\nThe willows follow it down to the flats.\nRabbits come out in the evening to drink.\nEagles circle overhead in the afternoon heat."
        self.assertFalse(_looks_like_list_block(prose))


class TestSectionTitleDetection(unittest.TestCase):
    def test_poem_title_is_section_title(self):
        self.assertTrue(_is_section_title("One's-Self I Sing"))
        self.assertTrue(_is_section_title("As I Ponder'd in Silence"))
        self.assertTrue(_is_section_title("In Cabin'd Ships at Sea"))

    def test_sentence_not_section_title(self):
        self.assertFalse(_is_section_title("SAMPSON  Gregory, on my word we'll not carry coals."))
        self.assertFalse(_is_section_title("What's in a name?"))
        self.assertFalse(_is_section_title("He walked into the room alone."))

    def test_multiline_not_section_title(self):
        self.assertFalse(_is_section_title("Walt Whitman\nOne's-Self I Sing"))

    def test_long_text_not_section_title(self):
        long = "A" * 81
        self.assertFalse(_is_section_title(long))


@unittest.skipUnless(_HAS_BS4, "beautifulsoup4 not installed")
class TestSoupToText(unittest.TestCase):
    def test_paragraphs_get_double_newlines(self):
        """Each <p> tag should be separated by \\n\\n so chunk_text can split them."""
        from bs4 import BeautifulSoup
        html = "<html><body><p>First paragraph.</p><p>Second paragraph.</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        text = _soup_to_text(soup)
        self.assertIn("\n\n", text)
        self.assertIn("First paragraph", text)
        self.assertIn("Second paragraph", text)

    def test_mobi_style_html_paragraphs_separate(self):
        """Simulated MOBI HTML should produce properly separated paragraphs."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_MOBI_STYLE_HTML, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = _soup_to_text(soup)
        # Verify paragraph breaks exist
        self.assertGreater(text.count("\n\n"), 2)

    def test_mobi_style_chunking_preserves_prose(self):
        """After fixing paragraph separation, prose content should survive chunking."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_MOBI_STYLE_HTML, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = _soup_to_text(soup)
        chunks = chunk_text(text, "mice.mobi")
        all_text = " ".join(c.text for c in chunks)
        # Key prose from the actual book should appear
        self.assertIn("Salinas River", all_text)
        self.assertIn("rabbit hutch", all_text)

    def test_mobi_front_matter_separated_from_prose(self):
        """Front-matter entries (Table of Contents, Title Page) should be separate paragraphs."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_MOBI_STYLE_HTML, "html.parser")
        text = _soup_to_text(soup)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        # "Table of Contents" and story prose should be in separate paragraphs
        toc_para = next((p for p in paragraphs if "Table of Contents" in p), None)
        prose_para = next((p for p in paragraphs if "Salinas River" in p), None)
        self.assertIsNotNone(toc_para)
        self.assertIsNotNone(prose_para)
        self.assertNotEqual(toc_para, prose_para)


if __name__ == "__main__":
    unittest.main()
