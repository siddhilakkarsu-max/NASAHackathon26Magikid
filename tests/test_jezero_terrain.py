"""Georeferencing, source gaps, native resolution and service failure regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from affine import Affine
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rasterio.warp import transform

import jezero_terrain as terrain


CRS = "+proj=eqc +lat_ts=0 +lon_0=0 +R=3396190 +units=m +no_defs"


def write_raster(path, data, affine, nodata=-9999):
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0],
                       count=1, dtype="float32", crs=CRS, transform=affine, nodata=nodata) as ds:
        ds.write(data.astype("float32"), 1)


class JezeroTerrainTests(unittest.TestCase):
    def setUp(self):
        terrain._tile_bytes.cache_clear()
        terrain._source_info.cache_clear()
        terrain._global_tile.cache_clear()

    def test_native_grid_preserves_global_transition_and_reaches_twenty_meters(self):
        start = np.pi * 3396190 / (2 ** terrain.MIN_LEVEL * (terrain.GRID_SIZE - 1))
        end = np.pi * 3396190 / (2 ** terrain.MAX_LEVEL * (terrain.GRID_SIZE - 1))
        self.assertAlmostEqual(start, 162.8, delta=0.1)
        self.assertAlmostEqual(end, 20.35, delta=0.1)
        self.assertEqual(terrain.MIN_LEVEL, terrain.GLOBAL_LEVEL + 1)

    def test_invalid_tiles_rejected_before_reading_source(self):
        for args in ((7, 0, 0), (12, 0, 0), (8, -1, 0), (8, 256, 0), (8, 0, 512)):
            with self.assertRaises(ValueError):
                terrain.tile_bounds(*args)
        with patch.object(terrain, "jezero_metadata") as metadata:
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as error:
                terrain.jezero_tile(12, 0, 0)
            self.assertEqual(error.exception.status_code, 404)
            metadata.assert_not_called()

    def test_missing_source_does_not_download_or_claim_high_resolution_coverage(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(terrain, "LOCAL_DEM", Path(temporary) / "missing.tif"), \
                patch.object(terrain.urllib.request, "urlopen") as download:
            result = terrain.jezero_metadata()
            self.assertFalse(result["available"])
            self.assertNotIn("rectangle", result)
            self.assertIn("--download", result["message"])
            download.assert_not_called()

    def test_vertex_sampling_uses_pixel_centers_and_identical_shared_edges(self):
        bounds = terrain.tile_bounds(11, 814, 2929)
        west, south, east, north = bounds
        (xs, ys) = transform(terrain.MARS_CRS, CRS, [west, east], [north, south])
        left, top = xs[0] - 500, ys[0] + 500
        affine = Affine(20, 0, left, 0, -20, top)
        yy, xx = np.indices((512, 1024))
        values = 100 + (xx + 0.5) * 0.4 + (yy + 0.5) * 0.6
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "plane.tif"
            write_raster(source, values, affine)
            tile = terrain._sample_raster(source, bounds)
            neighbour = terrain._sample_raster(source, terrain.tile_bounds(11, 814, 2930))
            self.assertTrue(np.isfinite(tile).all())
            self.assertTrue(np.isfinite(neighbour).all())
            np.testing.assert_allclose(tile[:, -1], neighbour[:, 0], rtol=0, atol=0.001)
            expected_nw = 100 + (xs[0] - left) * 0.02 + (top - ys[0]) * 0.03
            expected_se = 100 + (xs[1] - left) * 0.02 + (top - ys[1]) * 0.03
            self.assertAlmostEqual(float(tile[0, 0]), expected_nw, delta=0.02)
            self.assertAlmostEqual(float(tile[-1, -1]), expected_se, delta=0.02)
            self.assertLess(tile[0, 0], tile[-1, 0], "Row order is north to south")

    def test_validity_feather_excludes_nodata_and_has_zero_weight_at_edges(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "masked.tif"
            data = np.full((30, 30), -2500, dtype="float32")
            data[15, 15] = -9999
            write_raster(source, data, Affine(20, 0, 10000, 0, -20, 20000))
            feather = terrain._prepare_feather(source, terrain._signature(source))
            with rasterio.open(feather) as ds:
                weight = ds.read(1)
                self.assertEqual(ds.dtypes, ("uint8",))
            self.assertEqual(weight[15, 15], 0)
            self.assertEqual(weight[15, 14], 0)
            self.assertTrue((weight[0] == 0).all())
            self.assertTrue((weight[:, -1] == 0).all())
            self.assertGreater(weight[6, 6], 0)
            self.assertEqual(terrain._prepare_feather(source, terrain._signature(source)), feather)

    def test_global_sampling_keeps_exact_edges_and_lerc_node_order(self):
        def global_plane(y, x):
            rows, cols = np.indices((513, 513))
            return (100 + (x * 512 + cols) * 0.01 + (y * 512 + rows) * 0.02).astype("float32")
        with patch.object(terrain, "_global_tile", side_effect=global_plane):
            for level in (8, 11):
                y, x = 100, 100
                current = terrain._sample_global(level, y, x)
                right = terrain._sample_global(level, y, x + 1)
                below = terrain._sample_global(level, y + 1, x)
                np.testing.assert_array_equal(current[:, -1], right[:, 0])
                np.testing.assert_array_equal(current[-1, :], below[0, :])
                self.assertLess(current[0, 0], current[-1, -1])

    def test_blending_uses_only_real_samples_and_keeps_local_interior_unmodified(self):
        local = np.array([[100, 200, np.nan, 300]], dtype="float32")
        global_ = np.array([[10, 20, 30, np.nan]], dtype="float32")
        feather = np.array([[0, 127.5, 255, 255]], dtype="float32")
        result = terrain._blend(local, global_, feather)
        np.testing.assert_allclose(result, [[10, 110, 30, 300]])
        self.assertEqual(result.dtype, np.dtype("<f4"))
        with self.assertRaises(ValueError):
            terrain._blend(np.array([[np.nan]]), np.array([[np.nan]]), np.array([[0]]))

    def test_tile_endpoint_binary_layout_and_no_coverage_status(self):
        app = FastAPI()
        app.include_router(terrain.router)
        client = TestClient(app)
        bounds = terrain.tile_bounds(11, 814, 2929)
        rectangle = dict(zip(("west", "south", "east", "north"), bounds))
        raw = np.arange(terrain.GRID_SIZE ** 2, dtype="<f4").tobytes()
        with patch.object(terrain, "jezero_metadata", return_value={"available": True, "rectangle": rectangle}), \
                patch.object(terrain, "_signature", return_value="fixture"), \
                patch.object(terrain, "_tile_bytes", return_value=raw) as fetch:
            response = client.get("/terrain/jezero/11/814/2929.bin")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.content), terrain.GRID_SIZE ** 2 * 4)
            self.assertEqual(response.content, raw)
            self.assertEqual(response.headers["x-terrain-grid-size"], "257")
            response = client.get("/terrain/jezero/11/814/2931.bin")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(fetch.call_count, 1)

    def test_source_failure_is_unavailable_not_fake_flat_heights(self):
        app = FastAPI()
        app.include_router(terrain.router)
        client = TestClient(app)
        rectangle = dict(zip(("west", "south", "east", "north"), terrain.tile_bounds(11, 814, 2929)))
        with patch.object(terrain, "jezero_metadata", return_value={"available": True, "rectangle": rectangle}), \
                patch.object(terrain, "_signature", return_value="fixture"), \
                patch.object(terrain, "_tile_bytes", side_effect=ValueError("missing real data")):
            response = client.get("/terrain/jezero/11/814/2929.bin")
            self.assertEqual(response.status_code, 503)
            self.assertIn("Real elevation samples", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
