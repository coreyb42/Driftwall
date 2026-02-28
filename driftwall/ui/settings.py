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

        self._image_dir_btn = Gtk.FileChooserButton(
            title="Select image directory",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        img_dir = raw.get("image_dir", str(Path.home() / "Pictures"))
        self._image_dir_btn.set_filename(img_dir)
        box.pack_start(_row("Image directory", self._image_dir_btn), False, False, 0)

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

        self._overlay_prompt = Gtk.Entry()
        self._overlay_prompt.set_text(ov.get("prompt", "a haiku"))
        box.pack_start(_row("Prompt", self._overlay_prompt), False, False, 0)

        self._overlay_model = Gtk.Entry()
        self._overlay_model.set_text(ov.get("model", ""))
        self._overlay_model.set_placeholder_text("(same as ollama.model)")
        box.pack_start(_row("Model", self._overlay_model), False, False, 0)

        _quadrants = ["top-left", "top-right", "bottom-left", "bottom-right"]
        self._overlay_quadrant = Gtk.ComboBoxText()
        for q in _quadrants:
            self._overlay_quadrant.append_text(q)
        quadrant = ov.get("quadrant", "bottom-right")
        idx = _quadrants.index(quadrant) if quadrant in _quadrants else 3
        self._overlay_quadrant.set_active(idx)
        box.pack_start(_row("Quadrant", self._overlay_quadrant), False, False, 0)

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
        img_dir = self._image_dir_btn.get_filename() or ""
        if img_dir:
            data["image_dir"] = img_dir
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
        _quadrants = ["top-left", "top-right", "bottom-left", "bottom-right"]
        qi = self._overlay_quadrant.get_active()
        quadrant = _quadrants[qi] if 0 <= qi < len(_quadrants) else "bottom-right"
        data["overlay"] = {
            **data.get("overlay", {}),
            "enabled": self._overlay_enabled.get_active(),
            "prompt": self._overlay_prompt.get_text().strip(),
            "model": self._overlay_model.get_text().strip(),
            "quadrant": quadrant,
            "font_file": self._overlay_font_file.get_filename() or "",
            "font_dir": self._overlay_font_dir.get_filename() or "",
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(tomli_w.dumps(data))
        self._raw = data

    def _show_info(self, msg: str, error: bool = False) -> None:
        self._infobar.set_message_type(
            Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO
        )
        self._infobar_label.set_text(msg)
        self._infobar.show_all()
