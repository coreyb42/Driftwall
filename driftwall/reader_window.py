"""GTK3 reader window: shows a content chunk in surrounding document context."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

log = logging.getLogger(__name__)

_SEPARATOR = "\n\u2E3B\n\n"  # ⸻ em-dash separator between chunks


class ReaderWindow(Gtk.Window):
    """Book-like reader window with infinite scroll around a seed chunk."""

    _INIT_WINDOW = 15   # chunks on each side of seed at initial load
    _MORE_CHUNK  = 10   # chunks added when near an edge
    _NEAR_FRAC   = 0.15 # trigger load when within 15% of edge

    def __init__(self, chunk, config) -> None:
        super().__init__()
        self._chunk = chunk
        self._config = config
        self._all_chunks: list = []
        self._loaded_start = 0
        self._loaded_end = 0
        self._seed_mark: Gtk.TextMark | None = None
        self._begin_inserted = False
        self._end_inserted = False
        self._scroll_handler_id: int | None = None

        # Window chrome
        title = chunk.metadata.get("source_title", Path(chunk.source_path).stem)
        author = chunk.metadata.get("author", "")
        self.set_title(f"{title} — {author}" if author else title)
        self.set_default_size(720, 800)
        self.set_resizable(True)

        # Header bar
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = title
        if author:
            header.props.subtitle = author
        self.set_titlebar(header)

        # Initial spinner while parsing
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(48, 48)
        spinner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        spinner_box.set_valign(Gtk.Align.CENTER)
        spinner_box.set_halign(Gtk.Align.CENTER)
        spinner_box.pack_start(self._spinner, True, True, 0)
        self.add(spinner_box)
        self._spinner.start()

        threading.Thread(target=self._parse_source, daemon=True).start()

    # ── background parsing ────────────────────────────────────────────────────

    def _parse_source(self) -> None:
        """Re-parse the source file to get all chunks. Runs in a background thread."""
        from .content_scanner import chunk_text, parse_csv_quotes, _EXTRACTORS

        source_path = Path(self._chunk.source_path)
        suffix = source_path.suffix.lower()
        try:
            if suffix == ".csv":
                all_chunks = parse_csv_quotes(source_path)
            else:
                extractor = _EXTRACTORS.get(suffix)
                if extractor is None:
                    log.warning("ReaderWindow: no extractor for %s", suffix)
                    GLib.idle_add(self._on_load_failed, f"Unsupported format: {suffix}")
                    return
                text = extractor(source_path)
                all_chunks = chunk_text(text, str(source_path))
        except Exception as e:
            log.warning("ReaderWindow: failed to parse %s: %s", source_path, e)
            GLib.idle_add(self._on_load_failed, str(e))
            return

        GLib.idle_add(self._on_loaded, all_chunks)

    def _on_load_failed(self, msg: str) -> bool:
        self._spinner.stop()
        child = self.get_child()
        if child:
            self.remove(child)
        label = Gtk.Label(label=f"Could not load document:\n{msg}")
        label.set_line_wrap(True)
        self.add(label)
        self.show_all()
        return False

    def _on_loaded(self, all_chunks: list) -> bool:
        """Called on the GLib main thread once parsing completes."""
        self._all_chunks = all_chunks

        # Remove spinner container
        child = self.get_child()
        if child:
            self.remove(child)

        # Build text view
        self._buf = Gtk.TextBuffer()
        self._tv = Gtk.TextView(buffer=self._buf)
        self._tv.set_editable(False)
        self._tv.set_cursor_visible(False)
        self._tv.set_wrap_mode(Gtk.WrapMode.WORD)
        self._tv.set_left_margin(24)
        self._tv.set_right_margin(24)
        self._tv.set_pixels_above_lines(4)
        self._tv.set_pixels_below_lines(4)

        # Font — use font_file from config if set, otherwise system monospace
        font_file = getattr(self._config.dynamic_overlay, "font_file", "")
        if font_file:
            from .overlay import resolve_font_family
            family = resolve_font_family(font_file)
        else:
            family = "serif"
        font_desc = Pango.FontDescription.from_string(f"{family} 14")
        self._tv.override_font(font_desc)

        # Highlight tag for seed chunk
        self._highlight_tag = self._buf.create_tag(
            "seed-highlight",
            background="#3a3a00",
        )

        # ScrolledWindow
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scrolled.add(self._tv)
        self.add(self._scrolled)

        # Populate initial window of chunks around the seed
        self._populate_initial()

        self.show_all()
        GLib.idle_add(self._scroll_to_seed)

        # Connect scroll handler after initial display
        adj = self._scrolled.get_vadjustment()
        self._scroll_handler_id = adj.connect("value-changed", self._on_scroll)

        return False

    # ── buffer population ─────────────────────────────────────────────────────

    def _find_seed_index(self) -> int:
        """Find the index of the seed chunk in all_chunks by chunk_index."""
        seed_idx = self._chunk.chunk_index
        for i, c in enumerate(self._all_chunks):
            if c.chunk_index == seed_idx:
                return i
        # fallback: match by id
        for i, c in enumerate(self._all_chunks):
            if c.id == self._chunk.id:
                return i
        return 0

    def _populate_initial(self) -> None:
        seed_pos = self._find_seed_index()
        start = max(0, seed_pos - self._INIT_WINDOW)
        end = min(len(self._all_chunks), seed_pos + self._INIT_WINDOW + 1)
        self._loaded_start = start
        self._loaded_end = end

        self._buf.set_text("")
        insert_iter = self._buf.get_end_iter()

        if start == 0:
            self._buf.insert(insert_iter, "[Beginning of document]\n\n")
            self._begin_inserted = True

        for i, chunk in enumerate(self._all_chunks[start:end], start=start):
            if i > start:
                insert_iter = self._buf.get_end_iter()
                self._buf.insert(insert_iter, _SEPARATOR)

            chunk_start_iter = self._buf.get_end_iter()
            insert_iter = self._buf.get_end_iter()
            self._buf.insert(insert_iter, chunk.text)
            chunk_end_iter = self._buf.get_end_iter()

            if chunk.chunk_index == self._chunk.chunk_index:
                self._buf.apply_tag(self._highlight_tag, chunk_start_iter, chunk_end_iter)
                self._seed_mark = self._buf.create_mark(
                    "seed", chunk_start_iter, left_gravity=True
                )

        if end == len(self._all_chunks):
            insert_iter = self._buf.get_end_iter()
            self._buf.insert(insert_iter, "\n\n[End of document]")
            self._end_inserted = True

    def _scroll_to_seed(self) -> bool:
        if self._seed_mark is not None:
            self._tv.scroll_to_mark(self._seed_mark, 0.1, True, 0.0, 0.3)
        return False

    # ── infinite scroll ───────────────────────────────────────────────────────

    def _on_scroll(self, adj: Gtk.Adjustment) -> None:
        upper = adj.get_upper()
        page = adj.get_page_size()
        val = adj.get_value()
        scrollable = upper - page
        if scrollable <= 0:
            return
        frac = val / scrollable
        if frac < self._NEAR_FRAC and self._loaded_start > 0:
            self._prepend_more()
        elif frac > 1.0 - self._NEAR_FRAC and self._loaded_end < len(self._all_chunks):
            self._append_more()

    def _prepend_more(self) -> None:
        adj = self._scrolled.get_vadjustment()
        old_upper = adj.get_upper()

        new_start = max(0, self._loaded_start - self._MORE_CHUNK)
        chunks_to_add = self._all_chunks[new_start:self._loaded_start]
        if not chunks_to_add:
            return

        start_iter = self._buf.get_start_iter()

        # If beginning-of-document label is present, insert after it
        if self._begin_inserted:
            # Move past the marker line
            start_iter = self._buf.get_start_iter()
            start_iter.forward_line()
            start_iter.forward_line()  # skip blank line

        # Build text to prepend (separator + chunks, then separator before existing)
        parts: list[str] = []
        if self._begin_inserted and new_start == 0:
            pass  # already shown
        elif new_start == 0 and not self._begin_inserted:
            parts.append("[Beginning of document]\n\n")
            self._begin_inserted = True

        for i, chunk in enumerate(chunks_to_add):
            parts.append(chunk.text)
            parts.append(_SEPARATOR)  # separator after each prepended chunk

        text_to_insert = "".join(parts)
        self._buf.insert(start_iter, text_to_insert)
        self._loaded_start = new_start

        def _fix_scroll() -> bool:
            new_upper = adj.get_upper()
            adj.set_value(adj.get_value() + (new_upper - old_upper))
            return False

        GLib.idle_add(_fix_scroll)

    def _append_more(self) -> None:
        new_end = min(len(self._all_chunks), self._loaded_end + self._MORE_CHUNK)
        chunks_to_add = self._all_chunks[self._loaded_end:new_end]
        if not chunks_to_add:
            return

        end_iter = self._buf.get_end_iter()

        # If end-of-document label already present, insert before it
        if self._end_inserted:
            # Move back before the "\n\n[End of document]" marker
            end_iter = self._buf.get_end_iter()
            end_iter.backward_chars(len("\n\n[End of document]"))

        parts: list[str] = []
        for chunk in chunks_to_add:
            parts.append(_SEPARATOR)
            parts.append(chunk.text)

        if new_end == len(self._all_chunks) and not self._end_inserted:
            parts.append("\n\n[End of document]")
            self._end_inserted = True

        self._buf.insert(end_iter, "".join(parts))
        self._loaded_end = new_end
