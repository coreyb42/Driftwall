from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from driftwall.config import Config
from driftwall.db import ImageRecord, get_image_by_hash, init_db, upsert_image
from driftwall.scanner import scan_directory
from image_sidecar import sidecar_path_for_image
from image_sidecar.driftwall import (
    extract_current_driftwall_image_record,
    upsert_driftwall_classification,
)


def _config_for_scan(image_dir: Path, db_path: Path, prompt_path: Path) -> Config:
    return Config(
        image_dirs=[image_dir],
        db_path=db_path,
        prompt_path=prompt_path,
    )


def _sample_raw_classification() -> dict:
    return {
        "derived": {
            "geometry": {"orientation": "landscape"},
            "time": {"season": "summer", "time_of_day": "day"},
        },
        "content": {
            "descriptions": {"one_paragraph": "A serene landscape."},
            "subjects": {"genre": "landscape"},
            "scene": {"setting": "outdoor"},
            "entities": {},
            "aesthetics": {"composition": {}, "color": {}},
            "quality": {},
            "privacy": {},
        },
    }


class TestScannerSidecarIntegration(unittest.TestCase):
    def test_scan_uses_adjacent_sidecar_before_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "sample.jpg"
            image_path.write_bytes(b"image-bytes")
            prompt_path = root / "prompt.txt"
            prompt_path.write_text("classify", encoding="utf-8")
            db_path = root / "driftwall.db"
            config = _config_for_scan(root, db_path, prompt_path)

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
            from image_sidecar import write_sidecar
            write_sidecar(image_path, document)

            with patch("driftwall.scanner.classify_image", side_effect=AssertionError("LLM should not run")):
                result = scan_directory(root, db_path, config)

            self.assertEqual(result.newly_classified, 0)
            self.assertEqual(result.already_classified, 1)
            record = get_image_by_hash(db_path, file_hash)
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.genre, "landscape")

    def test_scan_backfills_sidecar_from_existing_db_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "sample.jpg"
            image_path.write_bytes(b"image-bytes")
            prompt_path = root / "prompt.txt"
            prompt_path.write_text("classify", encoding="utf-8")
            db_path = root / "driftwall.db"
            config = _config_for_scan(root, db_path, prompt_path)

            from driftwall.classifier import hash_file

            file_hash = hash_file(image_path)
            init_db(db_path)
            upsert_image(
                db_path,
                ImageRecord(
                    path=str(image_path),
                    file_hash=file_hash,
                    file_size=image_path.stat().st_size,
                    classified_at="2024-01-01T00:00:00+00:00",
                    last_seen_at="2024-01-01T00:00:00+00:00",
                    genre="abstract",
                    setting="indoor",
                    one_paragraph="An abstract composition.",
                ),
            )

            with patch("driftwall.scanner.classify_image", side_effect=AssertionError("LLM should not run")):
                result = scan_directory(root, db_path, config)

            self.assertEqual(result.already_classified, 1)
            self.assertTrue(sidecar_path_for_image(image_path).exists())
            exported = extract_current_driftwall_image_record(
                image_path,
                file_hash=file_hash,
                last_seen_at="2024-01-02T00:00:00+00:00",
            )
            self.assertIsNotNone(exported)
            assert exported is not None
            self.assertEqual(exported.genre, "abstract")

    def test_scan_writes_sidecar_for_new_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "sample.jpg"
            image_path.write_bytes(b"image-bytes")
            prompt_path = root / "prompt.txt"
            prompt_path.write_text("classify", encoding="utf-8")
            db_path = root / "driftwall.db"
            config = _config_for_scan(root, db_path, prompt_path)

            with patch("driftwall.scanner.prepare_image", return_value=b"prepared-image"), patch(
                "driftwall.scanner.classify_image_grok",
                return_value=_sample_raw_classification(),
            ), patch(
                "driftwall.scanner.classify_image",
                return_value=_sample_raw_classification(),
            ):
                result = scan_directory(root, db_path, config)

            self.assertEqual(result.newly_classified, 1)
            self.assertTrue(sidecar_path_for_image(image_path).exists())

            from driftwall.classifier import hash_file

            record = extract_current_driftwall_image_record(
                image_path,
                file_hash=hash_file(image_path),
                last_seen_at="2024-01-02T00:00:00+00:00",
            )
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.genre, "landscape")


if __name__ == "__main__":
    unittest.main()
