"""Global 3D terrain tiles are checked against MOLA; wrong Esri tiles are rebuilt from correct coarser ones."""
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

import lerc
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import murray

# a smooth stand-in for MOLA: 1/16 degree grid, 90N..90S, 0..360E
_rows, _cols = np.meshgrid(np.arange(murray.MOLA_REF_SHAPE[0]), np.arange(murray.MOLA_REF_SHAPE[1]), indexing="ij")
FAKE_MOLA = (2000 * np.sin(_rows / 300) * np.cos(_cols / 400)).astype("float32")


def true_tile(z, y, x):
    lat, lon = murray._tile_grid(z, y, x, 513)
    return murray.mola_heights(lat, lon).astype("float32")


class ElevationCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(murray, "CACHE", Path(self.tmp.name)),
                        patch.object(murray, "mola_reference", return_value=FAKE_MOLA)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def fake_esri(self, wrong=()):
        def fetch(url, timeout=600):
            z, y, x = map(int, re.search(r"tile/(\d+)/(\d+)/(\d+)$", url).groups())
            heights = true_tile(z, y, x)
            if (z, y, x) in wrong:
                heights = heights + 2500            # heights from somewhere else, kilometres off
            return murray._lerc2_v3(heights)
        return fetch

    def test_lerc_v3_round_trips_exactly_with_valid_checksum(self):
        heights = (np.random.default_rng(1).random((513, 513)) * 9000 - 4000).astype("float32")
        blob = murray._lerc2_v3(heights)
        self.assertEqual(blob[:6], b"Lerc2 ")
        self.assertEqual(lerc.getLercBlobInfo(blob)[:3], (0, 3, 6))   # version 3: Cesium reads up to 4
        np.testing.assert_array_equal(murray._decode_heights(blob), heights)
        flat = murray._lerc2_v3(np.full((513, 513), -1200, "float32"))
        np.testing.assert_array_equal(murray._decode_heights(flat), np.full((513, 513), -1200, "float32"))

    def test_correct_tile_is_served_unchanged(self):
        fetch = self.fake_esri()
        with patch.object(murray, "_fetch", side_effect=fetch):
            self.assertEqual(murray.elevation_tile_bytes(7, 58, 124), fetch("tile/7/58/124"))

    def test_wrong_tile_is_rebuilt_from_correct_parent(self):
        with patch.object(murray, "_fetch", side_effect=self.fake_esri(wrong={(7, 58, 124)})):
            fixed = murray._decode_heights(murray.elevation_tile_bytes(7, 58, 124))
        self.assertLess(float(np.abs(fixed - true_tile(7, 58, 124)).max()), 30)
        self.assertTrue((Path(self.tmp.name) / "elevation_checked" / "7_58_124.lerc").exists())

    def test_wrong_parents_are_skipped_then_mola_is_the_last_resort(self):
        wrong = {(7, 58, 124), (6, 29, 62), (5, 14, 31)}
        with patch.object(murray, "_fetch", side_effect=self.fake_esri(wrong)):
            fixed = murray._decode_heights(murray.elevation_tile_bytes(7, 58, 124))
        self.assertLess(float(np.abs(fixed - true_tile(7, 58, 124)).max()), 30)
        everything = {(z, 60 >> (7 - z), 130 >> (7 - z)) for z in range(8)}
        with patch.object(murray, "_fetch", side_effect=self.fake_esri(everything)):
            fixed = murray._decode_heights(murray.elevation_tile_bytes(7, 60, 130))
        self.assertLess(float(np.abs(fixed - true_tile(7, 60, 130)).max()), 1)

    def test_upstream_error_is_rebuilt_but_not_kept(self):
        good = self.fake_esri()

        def flaky(url, timeout=600):
            if url.endswith("tile/7/58/124"):
                raise OSError("HTTP Error 500")
            return good(url)
        with patch.object(murray, "_fetch", side_effect=flaky):
            fixed = murray._decode_heights(murray.elevation_tile_bytes(7, 58, 124))
        self.assertLess(float(np.abs(fixed - true_tile(7, 58, 124)).max()), 30)
        self.assertFalse((Path(self.tmp.name) / "elevation_checked" / "7_58_124.lerc").exists())


if __name__ == "__main__":
    unittest.main()
