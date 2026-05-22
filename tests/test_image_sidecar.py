from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from driftwall.db import ImageRecord
from image_sidecar import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    base_document,
    coerce_document,
    load_sidecar,
    sidecar_path_for_image,
    upgrade_document,
    write_sidecar,
)
from image_sidecar.driftwall import (
    DriftwallSidecarScanResult,
    extract_current_driftwall_image_record,
    scan_image_with_driftwall,
    upsert_driftwall_classification,
    upsert_driftwall_image_record,
)


def _sample_raw_classification() -> dict:
    return {
        "derived": {
            "geometry": {
                "orientation": "landscape",
                "aspect_ratio": 1.5,
                "aspect_class": "standard",
                "megapixels": 2.4,
                "crop_detected": False,
            },
            "time": {
                "season": "summer",
                "time_of_day": "day",
            },
        },
        "content": {
            "descriptions": {
                "one_sentence": "A bright coastal view.",
                "one_paragraph": "A bright coastal landscape under a clear sky.",
                "alt_text": "A coast with blue water and sky.",
                "keywords": ["coast", "water", "sky"],
            },
            "subjects": {
                "primary_subject": "coastline",
                "secondary_subjects": ["ocean"],
                "genre": "landscape",
                "subject_distance": "wide",
            },
            "scene": {
                "setting": "outdoor",
                "environment": "coastal",
                "weather": "clear",
                "lighting": "daylight",
                "event_context": "none",
            },
            "entities": {
                "people": [],
                "animals": [],
                "objects": ["rocks"],
                "buildings": [],
                "text": {"visible_text": []},
            },
            "aesthetics": {
                "composition": {
                    "dominant_lines": ["horizontal"],
                    "framing": "open",
                    "depth": "deep",
                },
                "color": {
                    "palette": "cool",
                    "saturation": "medium",
                    "dominant_colors": ["blue", "white"],
                },
                "mood": ["calm"],
                "style": "photograph",
            },
            "quality": {
                "sharpness": "sharp",
                "noise": "low",
                "exposure": "balanced",
                "motion_blur": "none",
                "focus_issues": [],
                "artifacts": [],
            },
            "privacy": {
                "faces_present": False,
                "sensitive": [],
                "release_needed": False,
            },
        },
    }


class TestImageSidecar(unittest.TestCase):
    def test_base_document_is_generic_and_versioned(self) -> None:
        image_path = Path("/tmp/example/photo.jpg")
        document = base_document(image_path, file_hash="abc123", file_size=42)
        self.assertEqual(document["schema_name"], SCHEMA_NAME)
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(document["image"]["file_name"], "photo.jpg")
        self.assertEqual(document["entries"], {})

    def test_sidecar_path_is_hidden_and_adjacent(self) -> None:
        image_path = Path("/tmp/example/photo.jpg")
        self.assertEqual(sidecar_path_for_image(image_path), image_path.with_name(".photo.jpg.imgmeta.json"))

    def test_coerce_document_upgrades_and_rewrites_image_fields(self) -> None:
        image_path = Path("/tmp/example/photo.jpg")
        document = coerce_document(
            {"schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION, "image": {}, "entries": {"x": 1}},
            image_path=image_path,
            file_hash="hash-1",
            file_size=99,
        )
        self.assertEqual(document["image"]["file_name"], "photo.jpg")
        self.assertEqual(document["image"]["file_hash"], "hash-1")
        self.assertEqual(document["image"]["file_size"], 99)
        self.assertEqual(document["entries"]["x"], 1)

    def test_upgrade_document_rejects_unknown_versions(self) -> None:
        with self.assertRaises(ValueError):
            upgrade_document({"schema_version": 999})

    def test_extract_current_record_prefers_raw_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.jpg"
            image_path.write_bytes(b"image-bytes")
            file_hash = "abc123"

            document = upsert_driftwall_classification(
                None,
                image_path=image_path,
                file_hash=file_hash,
                file_size=image_path.stat().st_size,
                raw=_sample_raw_classification(),
                classified_at="2024-01-01T00:00:00+00:00",
                prompt_text="classify this image",
                model="qwen-test",
            )
            write_sidecar(image_path, document)

            record = extract_current_driftwall_image_record(
                image_path,
                file_hash=file_hash,
                last_seen_at="2024-01-02T00:00:00+00:00",
            )

            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.genre, "landscape")
            self.assertEqual(record.setting, "outdoor")
            self.assertEqual(record.path, str(image_path))
            self.assertEqual(record.file_hash, file_hash)
            self.assertEqual(record.last_seen_at, "2024-01-02T00:00:00+00:00")

    def test_extract_current_record_falls_back_to_exported_image_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.jpg"
            image_path.write_bytes(b"image-bytes")

            exported = ImageRecord(
                path=str(image_path),
                file_hash="hash-1",
                file_size=image_path.stat().st_size,
                classified_at="2024-01-01T00:00:00+00:00",
                last_seen_at="2024-01-01T00:00:00+00:00",
                genre="abstract",
                setting="indoor",
                one_paragraph="A geometric abstract composition.",
            )
            document = upsert_driftwall_image_record(None, image_path=image_path, record=exported)
            write_sidecar(image_path, document)

            record = extract_current_driftwall_image_record(
                image_path,
                file_hash="hash-1",
                last_seen_at="2024-01-03T00:00:00+00:00",
            )

            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.genre, "abstract")
            self.assertEqual(record.setting, "indoor")
            self.assertEqual(record.last_seen_at, "2024-01-03T00:00:00+00:00")

    def test_load_sidecar_returns_none_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.jpg"
            self.assertIsNone(load_sidecar(image_path))


class TestScanImageWithDriftwall(unittest.TestCase):
    def test_returns_cached_result_when_sidecar_matches_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.jpg"
            image_path.write_bytes(b"image-bytes")
            prompt_path = Path(tmpdir) / "prompt.txt"
            prompt_path.write_text("classify", encoding="utf-8")

            from driftwall.classifier import hash_file

            file_hash = hash_file(image_path)
            document = upsert_driftwall_classification(
                None,
                image_path=image_path,
                file_hash=file_hash,
                file_size=image_path.stat().st_size,
                raw=_sample_raw_classification(),
                classified_at="2024-01-01T00:00:00+00:00",
                prompt_text="classify",
                model="qwen-test",
            )
            write_sidecar(image_path, document)

            result = scan_image_with_driftwall(
                image_path,
                prompt_path=prompt_path,
                model="qwen-test",
                host="http://localhost:11434",
            )

            self.assertIsInstance(result, DriftwallSidecarScanResult)
            self.assertEqual(result.status, "cached")
            self.assertEqual(result.record.genre, "landscape")

    def test_classifies_and_writes_sidecar_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.jpg"
            image_path.write_bytes(b"image-bytes")
            prompt_path = Path(tmpdir) / "prompt.txt"
            prompt_path.write_text("classify", encoding="utf-8")

            from unittest.mock import patch

            with patch("image_sidecar.driftwall.prepare_image", return_value=b"prepared-image"), patch(
                "image_sidecar.driftwall.classify_image",
                return_value=_sample_raw_classification(),
            ):
                result = scan_image_with_driftwall(
                    image_path,
                    prompt_path=prompt_path,
                    model="qwen-test",
                    host="http://localhost:11434",
                )

            self.assertEqual(result.status, "classified")
            self.assertEqual(result.record.genre, "landscape")
            self.assertTrue(sidecar_path_for_image(image_path).exists())


if __name__ == "__main__":
    unittest.main()
