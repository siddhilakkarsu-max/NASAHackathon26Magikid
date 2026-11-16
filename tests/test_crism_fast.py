"""CRISM fast path: one HTTP range per band for band-sequential images gives the same grid as reading it all."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject
from rasterio.enums import Resampling

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_cube as bc  # noqa: E402
from config import MARS_LONLAT_CRS  # noqa: E402

LABEL = '''BAND_STORAGE_TYPE = BAND_SEQUENTIAL
SAMPLE_TYPE = PC_REAL
SAMPLE_BITS = 32
^IMAGE = "TILE.IMG"
'''
BANDS, LINES, SAMPLES = 5, 300, 250


class FakeSource:
    """The parts of a rasterio dataset the fast path uses, over an in-memory image."""
    def __init__(self, ds):
        self.ds, self.crs, self.height, self.width = ds, ds.crs, ds.height, ds.width
        self.files = ["/vsicurl/https://example.test/tile.lbl", "/vsicurl/https://example.test/TILE.IMG"]

    def window(self, *bounds):
        return self.ds.window(*bounds)

    def window_transform(self, window):
        return self.ds.window_transform(window)


class CrismFastPath(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.cube = rng.random((BANDS, LINES, SAMPLES), dtype="float32")
        self.cube[:, 40:60, 30:50] = 65535                          # CRISM no-data
        self.raw = self.cube.astype("<f4").tobytes()                 # band-sequential, as on PDS
        self.transform = from_bounds(100, -32.5, 105, -27.5, SAMPLES, LINES)
        self.mem = MemoryFile()
        self.ds = self.mem.open(driver="GTiff", width=SAMPLES, height=LINES, count=BANDS, dtype="float32",
                                crs=MARS_LONLAT_CRS, transform=self.transform)
        self.ds.write(self.cube)
        b = (100.7, -31.6, 101.5, -30.8)
        self.grid = {"bounds": b, "width": 120, "height": 110, "transform": from_bounds(*b, 120, 110)}
        self.requests = []

    def tearDown(self):
        self.ds.close(); self.mem.close()

    def fake_range(self, url, start, length, timeout=120):
        self.assertEqual(url, "https://example.test/TILE.IMG")
        self.requests.append((start, length))
        return self.raw[start:start + length]

    def test_matches_a_full_read_with_one_request_per_band(self):
        idx = [2, 5, 1]
        with patch.object(bc, "_get_range", side_effect=self.fake_range):
            fast = bc._crism_read_bsq(FakeSource(self.ds), LABEL, idx, self.grid)
        full = np.full((len(idx), 110, 120), np.nan, "float32")
        reproject(source=self.cube[[i - 1 for i in idx]], destination=full, src_transform=self.transform,
                  src_crs=MARS_LONLAT_CRS, src_nodata=65535, dst_transform=self.grid["transform"],
                  dst_crs=MARS_LONLAT_CRS, dst_nodata=np.nan, resampling=Resampling.average)
        np.testing.assert_allclose(fast, full, rtol=0, atol=1e-6, equal_nan=True)
        self.assertEqual(len(self.requests), len(idx))
        self.assertLess(sum(n for _, n in self.requests), len(self.raw) * len(idx) / BANDS / 3)  # only the rows needed

    def test_other_layouts_use_the_general_reader(self):
        for change in ("BAND_SEQUENTIAL", "PC_REAL", '"TILE.IMG"'):
            other = LABEL.replace(change, {"BAND_SEQUENTIAL": "LINE_INTERLEAVED", "PC_REAL": "MSB_INTEGER",
                                           '"TILE.IMG"': '("TILE.IMG", 512 <BYTES>)'}[change])
            with patch.object(bc, "_get_range", side_effect=AssertionError("no fast read expected")):
                self.assertIsNone(bc._crism_read_bsq(FakeSource(self.ds), other, [1], self.grid))


if __name__ == "__main__":
    unittest.main()
