"""Settings dialog — GTK3 Notebook with five tabs for all config sections."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]


def _row(label_text: str, widget: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    label = Gtk.Label(label=label_text, xalign=1.0)
    label.set_width_chars(24)
    box.pack_start(label, False, False, 0)
    box.pack_start(widget, True, True, 0)
    return box


class _DirListWidget(Gtk.Box):
    """A vertical list of directory paths with Add / Remove controls."""

    def __init__(self, paths: list[str]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._rows: list[tuple[Gtk.Entry, Gtk.Button]] = []

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.pack_start(self._list_box, True, True, 0)

        add_btn = Gtk.Button(label="+ Add folder…")
        add_btn.connect("clicked", self._on_add)
        self.pack_start(add_btn, False, False, 0)

        for p in paths:
            self._add_row(p)

    def _add_row(self, path: str = "") -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        entry = Gtk.Entry()
        entry.set_text(path)
        entry.set_hexpand(True)

        pick_btn = Gtk.Button(label="…")
        pick_btn.connect("clicked", self._on_pick, entry)

        rm_btn = Gtk.Button(label="✕")
        rm_btn.connect("clicked", self._on_remove, row)

        row.pack_start(entry, True, True, 0)
        row.pack_start(pick_btn, False, False, 0)
        row.pack_start(rm_btn, False, False, 0)
        self._list_box.pack_start(row, False, False, 0)
        self._rows.append((entry, rm_btn))
        row.show_all()

    def _on_add(self, _btn: Gtk.Button) -> None:
        self._add_row("")

    def _on_pick(self, _btn: Gtk.Button, entry: Gtk.Entry) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Select image directory",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
        )
        current = entry.get_text().strip()
        if current:
            dialog.set_filename(current)
        if dialog.run() == Gtk.ResponseType.OK:
            entry.set_text(dialog.get_filename() or "")
        dialog.destroy()

    def _on_remove(self, _btn: Gtk.Button, row: Gtk.Box) -> None:
        self._list_box.remove(row)
        self._rows = [(e, b) for e, b in self._rows if b.get_parent() is not None]

    def get_paths(self) -> list[str]:
        paths = []
        for child in self._list_box.get_children():
            entry = child.get_children()[0]
            val = entry.get_text().strip()
            if val:
                paths.append(val)
        return paths


def _spin(
    value: float,
    lo: float,
    hi: float,
    step: float = 1.0,
    digits: int = 0,
) -> Gtk.SpinButton:
    adj = Gtk.Adjustment(
        value=value, lower=lo, upper=hi,
        step_increment=step, page_increment=step * 10,
    )
    spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=digits)
    spin.set_numeric(True)
    return spin


class SettingsDialog(Gtk.Dialog):
    def __init__(self, config_path: str | None = None) -> None:
        super().__init__(title="Driftwall Settings", modal=True)
        self.set_default_size(620, 520)

        self.config_path = Path(config_path) if config_path else (
            Path.home() / ".config" / "driftwall" / "config.toml"
        )

        # Load existing TOML (preserve unknown keys on save)
        self._raw: dict[str, Any] = {}
        if self.config_path.exists():
            with open(self.config_path, "rb") as f:
                self._raw = tomllib.load(f)

        notebook = Gtk.Notebook()
        notebook.set_border_width(8)
        self.vbox.pack_start(notebook, True, True, 0)
        self._nb = notebook

        self._build_general_tab()
        self._build_rotation_tab()
        self._build_ollama_tab()
        self._build_filters_tab()
        self._build_overlay_tab()
        self._build_content_tab()
        self._build_download_tab()

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save_btn = self.add_button("Save", Gtk.ResponseType.OK)
        save_btn.get_style_context().add_class("suggested-action")
        self.connect("response", self._on_response)

        self._infobar = Gtk.InfoBar()
        self._infobar.set_show_close_button(True)
        self._infobar_label = Gtk.Label()
        self._infobar.get_content_area().pack_start(self._infobar_label, True, True, 0)
        self._infobar.connect("response", lambda ib, _: ib.hide())
        self.vbox.pack_start(self._infobar, False, False, 0)

        self.vbox.show_all()
        self._infobar.hide()

    # ── tab builders ─────────────────────────────────────────────────────────

    def _tab_box(self, label: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        self._nb.append_page(box, Gtk.Label(label=label))
        return box

    def _build_general_tab(self) -> None:
        box = self._tab_box("General")
        raw = self._raw

        from driftwall.config import DEFAULT_PROMPT_PATH

        # Resolve initial dirs: prefer image_dirs list, fall back to image_dir string.
        if "image_dirs" in raw:
            initial_dirs = [str(d) for d in raw["image_dirs"]]
        elif "image_dir" in raw:
            initial_dirs = [raw["image_dir"]]
        else:
            initial_dirs = [str(Path.home() / "Pictures")]
        self._image_dirs_widget = _DirListWidget(initial_dirs)
        box.pack_start(_row("Image directories", self._image_dirs_widget), False, False, 0)

        self._db_path_entry = Gtk.Entry()
        self._db_path_entry.set_placeholder_text(
            "(default: ~/.local/share/driftwall/driftwall.db)"
        )
        self._db_path_entry.set_text(raw.get("db_path") or "")
        box.pack_start(_row("DB path (optional)", self._db_path_entry), False, False, 0)

        self._prompt_btn = Gtk.FileChooserButton(
            title="Select classification prompt",
            action=Gtk.FileChooserAction.OPEN,
        )
        prompt_path = raw.get("prompt_path", str(DEFAULT_PROMPT_PATH))
        self._prompt_btn.set_filename(prompt_path)
        box.pack_start(_row("Classification prompt", self._prompt_btn), False, False, 0)

    def _build_rotation_tab(self) -> None:
        box = self._tab_box("Rotation")
        rot = self._raw.get("rotation", {})

        self._interval_spin = _spin(rot.get("interval_minutes", 30), 1, 1440)
        box.pack_start(_row("Interval (minutes)", self._interval_spin), False, False, 0)

        self._avoid_repeat_spin = _spin(rot.get("avoid_repeat_window", 50), 1, 500)
        box.pack_start(_row("Avoid repeat window", self._avoid_repeat_spin), False, False, 0)

    def _build_ollama_tab(self) -> None:
        box = self._tab_box("Ollama")
        ol = self._raw.get("ollama", {})

        self._ollama_host = Gtk.Entry()
        self._ollama_host.set_text(ol.get("host", "http://localhost:11434"))
        box.pack_start(_row("Host", self._ollama_host), False, False, 0)

        self._ollama_model = Gtk.Entry()
        self._ollama_model.set_text(ol.get("model", "qwen3-vl:30b"))
        box.pack_start(_row("Model", self._ollama_model), False, False, 0)

        self._ollama_timeout = _spin(ol.get("timeout", 120), 10, 3600)
        box.pack_start(_row("Timeout (seconds)", self._ollama_timeout), False, False, 0)

        self._ollama_concurrency = _spin(ol.get("concurrency", 1), 1, 16)
        box.pack_start(_row("Concurrency", self._ollama_concurrency), False, False, 0)

        self._ollama_max_pixels = _spin(ol.get("max_image_pixels", 1344), 0, 8192)
        box.pack_start(_row("Max image pixels (edge)", self._ollama_max_pixels), False, False, 0)

        self._ollama_num_predict = _spin(ol.get("num_predict", 48000), 100, 200000, step=1000)
        box.pack_start(_row("Num predict (tokens)", self._ollama_num_predict), False, False, 0)

    def _build_filters_tab(self) -> None:
        box = self._tab_box("Filters")
        filt = self._raw.get("filters", {})

        self._exclude_faces = Gtk.CheckButton(label="Exclude images with faces")
        self._exclude_faces.set_active(filt.get("exclude_faces", False))
        box.pack_start(self._exclude_faces, False, False, 0)

        self._min_megapixels = _spin(
            float(filt.get("min_megapixels", 0.0)), 0.0, 100.0, step=0.1, digits=1
        )
        box.pack_start(_row("Min megapixels", self._min_megapixels), False, False, 0)

        self._exclude_genre_entry = Gtk.Entry()
        self._exclude_genre_entry.set_placeholder_text("portrait, macro  (comma-separated)")
        self._exclude_genre_entry.set_text(", ".join(filt.get("exclude_genre", [])))
        box.pack_start(_row("Exclude genre", self._exclude_genre_entry), False, False, 0)

        self._require_setting_entry = Gtk.Entry()
        self._require_setting_entry.set_placeholder_text("outdoor, urban  (comma-separated)")
        self._require_setting_entry.set_text(", ".join(filt.get("require_setting", [])))
        box.pack_start(_row("Require setting", self._require_setting_entry), False, False, 0)

        ori_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        req_ori = filt.get("require_orientation", [])
        self._ori_checks: dict[str, Gtk.CheckButton] = {}
        for ori in ("landscape", "portrait", "square", "panoramic"):
            cb = Gtk.CheckButton(label=ori.capitalize())
            cb.set_active(ori in req_ori)
            ori_box.pack_start(cb, False, False, 0)
            self._ori_checks[ori] = cb
        box.pack_start(_row("Require orientation", ori_box), False, False, 0)

    def _build_overlay_tab(self) -> None:
        box = self._tab_box("Overlay")
        ov = self._raw.get("overlay", {})

        switch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        switch_label = Gtk.Label(label="Enabled", xalign=1.0)
        switch_label.set_width_chars(24)
        self._overlay_enabled = Gtk.Switch()
        self._overlay_enabled.set_active(ov.get("enabled", False))
        switch_box.pack_start(switch_label, False, False, 0)
        switch_box.pack_start(self._overlay_enabled, False, False, 0)
        box.pack_start(switch_box, False, False, 0)

        # Prompts — one per line in a small text view.
        prompt_raw = ov.get("prompt", ["a haiku"])
        if isinstance(prompt_raw, list):
            prompt_text = "\n".join(prompt_raw)
        else:
            prompt_text = str(prompt_raw)
        self._overlay_prompts_buf = Gtk.TextBuffer()
        self._overlay_prompts_buf.set_text(prompt_text)
        prompt_view = Gtk.TextView(buffer=self._overlay_prompts_buf)
        prompt_view.set_wrap_mode(Gtk.WrapMode.WORD)
        prompt_scroll = Gtk.ScrolledWindow()
        prompt_scroll.set_min_content_height(72)
        prompt_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        prompt_scroll.add(prompt_view)
        prompt_hint = Gtk.Label(xalign=0.0)
        prompt_hint.set_markup("<small>One prompt per line — a random one is picked each rotation</small>")
        prompt_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        prompt_col.pack_start(prompt_scroll, True, True, 0)
        prompt_col.pack_start(prompt_hint, False, False, 0)
        box.pack_start(_row("Prompts", prompt_col), False, False, 0)

        self._overlay_model = Gtk.Entry()
        self._overlay_model.set_text(ov.get("model", ""))
        self._overlay_model.set_placeholder_text("(same as ollama.model)")
        box.pack_start(_row("Model", self._overlay_model), False, False, 0)

        _quadrants = ["top-left", "top-right", "bottom-left", "bottom-right"]
        quadrant_raw = ov.get("quadrant", ["bottom-right"])
        active_quadrants: set[str] = set(
            quadrant_raw if isinstance(quadrant_raw, list) else [quadrant_raw]
        )
        quad_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._quadrant_checks: dict[str, Gtk.CheckButton] = {}
        for q in _quadrants:
            cb = Gtk.CheckButton(label=q)
            cb.set_active(q in active_quadrants)
            quad_box.pack_start(cb, False, False, 0)
            self._quadrant_checks[q] = cb
        quad_hint = Gtk.Label(xalign=0.0)
        quad_hint.set_markup("<small>Checked positions are picked randomly each rotation</small>")
        quad_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        quad_col.pack_start(quad_box, False, False, 0)
        quad_col.pack_start(quad_hint, False, False, 0)
        box.pack_start(_row("Quadrant", quad_col), False, False, 0)

        self._overlay_font_file = Gtk.FileChooserButton(
            title="Select specific font file",
            action=Gtk.FileChooserAction.OPEN,
        )
        font_file = ov.get("font_file", "")
        if font_file:
            self._overlay_font_file.set_filename(font_file)
        box.pack_start(_row("Font file (specific)", self._overlay_font_file), False, False, 0)

        self._overlay_font_dir = Gtk.FileChooserButton(
            title="Select font directory",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        font_dir = ov.get("font_dir", "")
        if font_dir:
            self._overlay_font_dir.set_filename(font_dir)
        box.pack_start(_row("Font directory", self._overlay_font_dir), False, False, 0)

    def _build_content_tab(self) -> None:
        box = self._tab_box("Content")
        ct = self._raw.get("content", {})
        dyn = self._raw.get("dynamic_overlay", {})

        # ── Content ingestion ─────────────────────────────────────────────────
        section_lbl = Gtk.Label(xalign=0.0)
        section_lbl.set_markup("<b>Content ingestion</b>")
        box.pack_start(section_lbl, False, False, 0)

        ct_switch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ct_switch_lbl = Gtk.Label(label="Enabled", xalign=1.0)
        ct_switch_lbl.set_width_chars(24)
        self._content_enabled = Gtk.Switch()
        self._content_enabled.set_active(ct.get("enabled", False))
        ct_switch_box.pack_start(ct_switch_lbl, False, False, 0)
        ct_switch_box.pack_start(self._content_enabled, False, False, 0)
        box.pack_start(ct_switch_box, False, False, 0)

        default_content_dir = str(Path.home() / "Documents" / "driftwall-content")
        self._content_dir = Gtk.FileChooserButton(
            title="Select content directory",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        current_content_dir = ct.get("content_dir", default_content_dir)
        Path(current_content_dir).expanduser().mkdir(parents=True, exist_ok=True)
        self._content_dir.set_filename(str(Path(current_content_dir).expanduser()))
        box.pack_start(_row("Content directory", self._content_dir), False, False, 0)

        self._chroma_path_entry = Gtk.Entry()
        self._chroma_path_entry.set_placeholder_text(
            "(default: ~/.local/share/driftwall/chromadb)"
        )
        self._chroma_path_entry.set_text(ct.get("chroma_path") or "")
        box.pack_start(_row("ChromaDB path (optional)", self._chroma_path_entry), False, False, 0)

        self._embed_model_entry = Gtk.Entry()
        self._embed_model_entry.set_text(ct.get("embed_model", "nomic-embed-text"))
        box.pack_start(_row("Embed model", self._embed_model_entry), False, False, 0)

        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # ── Dynamic overlay ───────────────────────────────────────────────────
        dyn_section_lbl = Gtk.Label(xalign=0.0)
        dyn_section_lbl.set_markup("<b>Dynamic overlays</b>")
        box.pack_start(dyn_section_lbl, False, False, 0)

        dyn_switch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dyn_switch_lbl = Gtk.Label(label="Enabled", xalign=1.0)
        dyn_switch_lbl.set_width_chars(24)
        self._dyn_enabled = Gtk.Switch()
        self._dyn_enabled.set_active(dyn.get("enabled", False))
        dyn_switch_box.pack_start(dyn_switch_lbl, False, False, 0)
        dyn_switch_box.pack_start(self._dyn_enabled, False, False, 0)
        box.pack_start(dyn_switch_box, False, False, 0)

        self._dyn_max_simultaneous = _spin(dyn.get("max_simultaneous", 3), 1, 10)
        box.pack_start(_row("Max simultaneous", self._dyn_max_simultaneous), False, False, 0)

        self._dyn_spawn_interval = _spin(dyn.get("spawn_interval_seconds", 20), 5, 600)
        box.pack_start(_row("Spawn interval (s)", self._dyn_spawn_interval), False, False, 0)

        self._dyn_random_source_subset_size = _spin(
            dyn.get("random_source_subset_size", 0), 0, 1000
        )
        box.pack_start(
            _row("Random source subset size", self._dyn_random_source_subset_size),
            False,
            False,
            0,
        )

        self._dyn_min_lifetime = _spin(dyn.get("min_lifetime_seconds", 30), 5, 300)
        box.pack_start(_row("Min lifetime (s)", self._dyn_min_lifetime), False, False, 0)

        self._dyn_max_lifetime = _spin(dyn.get("max_lifetime_seconds", 90), 10, 600)
        box.pack_start(_row("Max lifetime (s)", self._dyn_max_lifetime), False, False, 0)

        self._dyn_font_size = _spin(dyn.get("font_size", 18), 8, 72)
        box.pack_start(_row("Font size (px)", self._dyn_font_size), False, False, 0)

        self._dyn_max_fraction = _spin(
            float(dyn.get("max_screen_fraction", 0.10)), 0.05, 0.50, step=0.05, digits=2
        )
        box.pack_start(_row("Max screen fraction", self._dyn_max_fraction), False, False, 0)

        self._dyn_font_file = Gtk.FileChooserButton(
            title="Select font file for dynamic overlays",
            action=Gtk.FileChooserAction.OPEN,
        )
        dyn_font = dyn.get("font_file", "")
        if dyn_font:
            self._dyn_font_file.set_filename(dyn_font)
        box.pack_start(_row("Font file (optional)", self._dyn_font_file), False, False, 0)

    def _build_download_tab(self) -> None:
        box = self._tab_box("Download")
        dl = self._raw.get("download", {})

        default_dir = str(Path.home() / "Pictures" / "driftwall-downloads")
        self._download_output_dir = Gtk.FileChooserButton(
            title="Select download directory",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        current_dir = dl.get("output_dir", default_dir)
        # FileChooserButton requires the directory to exist to set it
        Path(current_dir).expanduser().mkdir(parents=True, exist_ok=True)
        self._download_output_dir.set_filename(str(Path(current_dir).expanduser()))
        box.pack_start(_row("Download directory", self._download_output_dir), False, False, 0)

        hint = Gtk.Label(xalign=0.0)
        hint.set_markup(
            "<small>Images are saved into source-specific subfolders inside this directory.\n"
            "e.g. <i>download_dir/met/dept-11/</i> or <i>download_dir/met/landscape/</i></small>"
        )
        box.pack_start(hint, False, False, 0)

    # ── save ─────────────────────────────────────────────────────────────────

    def _on_response(self, _dialog: Gtk.Dialog, response: int) -> None:
        if response != Gtk.ResponseType.OK:
            return
        if tomli_w is None:
            self._show_info(
                "tomli_w not installed. Run: pip install 'driftwall[ui]'", error=True
            )
            return
        try:
            self._save()
            self._show_info(f"Saved to {self.config_path}")
        except Exception as e:
            self._show_info(f"Error saving: {e}", error=True)

    def _save(self) -> None:
        # Merge over existing raw to preserve unknown/future keys
        data: dict[str, Any] = dict(self._raw)

        # General
        dirs = self._image_dirs_widget.get_paths()
        if dirs:
            data["image_dirs"] = dirs
            data.pop("image_dir", None)  # remove legacy key
        db_path_text = self._db_path_entry.get_text().strip()
        if db_path_text:
            data["db_path"] = db_path_text
        else:
            data.pop("db_path", None)
        prompt_path = self._prompt_btn.get_filename() or ""
        if prompt_path:
            data["prompt_path"] = prompt_path

        # Rotation
        data["rotation"] = {
            **data.get("rotation", {}),
            "interval_minutes": int(self._interval_spin.get_value()),
            "avoid_repeat_window": int(self._avoid_repeat_spin.get_value()),
        }

        # Ollama
        data["ollama"] = {
            **data.get("ollama", {}),
            "host": self._ollama_host.get_text().strip(),
            "model": self._ollama_model.get_text().strip(),
            "timeout": int(self._ollama_timeout.get_value()),
            "concurrency": int(self._ollama_concurrency.get_value()),
            "max_image_pixels": int(self._ollama_max_pixels.get_value()),
            "num_predict": int(self._ollama_num_predict.get_value()),
        }

        # Filters
        exclude_genre = [
            g.strip() for g in self._exclude_genre_entry.get_text().split(",") if g.strip()
        ]
        require_setting = [
            s.strip() for s in self._require_setting_entry.get_text().split(",") if s.strip()
        ]
        require_ori = [ori for ori, cb in self._ori_checks.items() if cb.get_active()]
        data["filters"] = {
            **data.get("filters", {}),
            "exclude_faces": self._exclude_faces.get_active(),
            "min_megapixels": round(self._min_megapixels.get_value(), 1),
            "exclude_genre": exclude_genre,
            "require_setting": require_setting,
            "require_orientation": require_ori,
        }

        # Overlay
        start, end = self._overlay_prompts_buf.get_bounds()
        prompts = [
            line.strip()
            for line in self._overlay_prompts_buf.get_text(start, end, False).splitlines()
            if line.strip()
        ]
        if not prompts:
            prompts = ["a haiku"]
        active_quads = [q for q, cb in self._quadrant_checks.items() if cb.get_active()]
        if not active_quads:
            active_quads = ["bottom-right"]
        data["overlay"] = {
            **data.get("overlay", {}),
            "enabled": self._overlay_enabled.get_active(),
            "prompt": prompts,
            "model": self._overlay_model.get_text().strip(),
            "quadrant": active_quads,
            "font_file": self._overlay_font_file.get_filename() or "",
            "font_dir": self._overlay_font_dir.get_filename() or "",
        }

        # Content
        content_dir = self._content_dir.get_filename() or ""
        chroma_path_text = self._chroma_path_entry.get_text().strip()
        data["content"] = {
            **data.get("content", {}),
            "enabled": self._content_enabled.get_active(),
            "content_dir": content_dir,
            "embed_model": self._embed_model_entry.get_text().strip() or "nomic-embed-text",
        }
        if chroma_path_text:
            data["content"]["chroma_path"] = chroma_path_text
        else:
            data["content"].pop("chroma_path", None)

        # Dynamic overlay
        data["dynamic_overlay"] = {
            **data.get("dynamic_overlay", {}),
            "enabled": self._dyn_enabled.get_active(),
            "max_simultaneous": int(self._dyn_max_simultaneous.get_value()),
            "spawn_interval_seconds": int(self._dyn_spawn_interval.get_value()),
            "random_source_subset_size": int(self._dyn_random_source_subset_size.get_value()),
            "min_lifetime_seconds": int(self._dyn_min_lifetime.get_value()),
            "max_lifetime_seconds": int(self._dyn_max_lifetime.get_value()),
            "font_size": int(self._dyn_font_size.get_value()),
            "max_screen_fraction": round(self._dyn_max_fraction.get_value(), 2),
            "font_file": self._dyn_font_file.get_filename() or "",
        }

        # Download
        dl_dir = self._download_output_dir.get_filename()
        if dl_dir:
            data["download"] = {**data.get("download", {}), "output_dir": dl_dir}

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(tomli_w.dumps(data))
        self._raw = data

    def _show_info(self, msg: str, error: bool = False) -> None:
        self._infobar.set_message_type(
            Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO
        )
        self._infobar_label.set_text(msg)
        self._infobar.show_all()
