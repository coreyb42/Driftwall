from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from driftwall.downloader import download_met_artworks, met_output_subdir


class DownloaderTests(unittest.TestCase):
    def test_met_output_subdir_base_only(self) -> None:
        out = met_output_subdir(Path("/tmp/downloads"))
        self.assertEqual(out, Path("/tmp/downloads/met"))

    def test_met_output_subdir_with_department_and_query_sanitization(self) -> None:
        out = met_output_subdir(
            Path("/tmp/downloads"),
            department_id=11,
            search_query="landscape & seascape / 19th century",
        )
        self.assertEqual(out, Path("/tmp/downloads/met/dept-11/landscape---seascape---19th-century"))

    def test_met_output_subdir_truncates_long_query(self) -> None:
        long_query = "x" * 80
        out = met_output_subdir(Path("/tmp/downloads"), search_query=long_query)
        self.assertEqual(out.name, "x" * 40)


class DownloadMetArtworksTests(unittest.TestCase):
    def test_returns_early_when_limit_already_reached(self) -> None:
        """If output dir already has >= limit files, make no network calls."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            for i in range(5):
                (out_dir / f"met_{i}.jpg").touch()

            with mock.patch("driftwall.downloader.met_get_object_ids") as mock_ids:
                result = download_met_artworks(output_dir=out_dir, limit=5)
                mock_ids.assert_not_called()

            self.assertEqual(result.downloaded, 0)

    def test_downloads_only_remaining_needed(self) -> None:
        """With 2 existing images and limit=5, downloads at most 3 more."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "met_0.jpg").touch()
            (out_dir / "met_1.jpg").touch()

            def fake_get_json(url: str) -> dict:
                obj_id = url.rstrip("/").split("/")[-1]
                return {
                    "isPublicDomain": True,
                    "primaryImage": f"https://example.com/{obj_id}.jpg",
                    "title": f"Art {obj_id}",
                    "artistDisplayName": "Artist",
                }

            with mock.patch("driftwall.downloader.met_get_object_ids", return_value=[0, 1, 2, 3, 4, 5]):
                with mock.patch("driftwall.downloader._get_json", side_effect=fake_get_json):
                    with mock.patch("driftwall.downloader.time"):
                        result = download_met_artworks(output_dir=out_dir, limit=5, dry_run=True)

            self.assertEqual(result.downloaded, 3)


if __name__ == "__main__":
    unittest.main()
