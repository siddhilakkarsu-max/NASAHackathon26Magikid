"""Measured-height, coordinate, footprint, seam and cache regressions.

All raster fixtures are local analytic surfaces. These tests do not access the
network or equate a source's pixel spacing with its physical accuracy.
"""
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from affine import Affine
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rasterio.warp import transform

import global_terrain as terrain


RADIUS = 3396000
NATIVE_CRS = f"+proj=eqc +lat_ts=0 +lon_0=0 +R={RADIUS} +units=m +no_defs"
SHAPE = (terrain.GRID_SIZE, terrain.GRID_SIZE)


def rectangle(west, south, east, north):
    return dict(west=west, south=south, east=east, north=north)


def source(identifier, bounds, kind="ctx", spacing=20):
    return dict(id=identifier, kind=kind, title=identifier, rectangles=[rectangle(*bounds)],
                resolution_m=spacing, maximum_level=10 if kind == "hrsc" else 11,
                source_url="https://example.invalid/documentation")


def write_raster(path, values, affine, *, crs=NATIVE_CRS, scale=1, offset=0):
    with rasterio.open(path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
                       count=1, dtype="float32", crs=crs, transform=affine, nodata=-9999) as ds:
        ds.write(values.astype("float32"), 1)
        ds.scales = (scale,)
        ds.offsets = (offset,)


class GlobalTerrainTests(unittest.TestCase):
    def setUp(self):
        terrain._load_sources.cache_clear()
        terrain._source_index.cache_clear()
        terrain._metadata_bytes.cache_clear()
        with terrain._cache_lock:
            terrain._tile_cache.clear()

    def tearDown(self):
        self.setUp()

    def test_wrapped_and_positive_longitudes_preserve_angular_coverage(self):
        split = [rectangle(179, -1, 180, 1), rectangle(-180, -1, -179, 1)]
        self.assertEqual(terrain.normalize_rectangles([179, -1, -179, 1]), split)
        self.assertEqual(terrain.normalize_rectangles([179, -1, 181, 1]), split)
        self.assertEqual(terrain.normalize_rectangles([350, -1, 355, 1]), [rectangle(-10, -1, -5, 1)])
        for invalid in ([0, 0, 0, 1], [-180, -1, 180, 1], [0, -91, 1, 1],
                        [0, 2, 1, 1], [0, 0, float("nan"), 1], [0, 0, 1]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                terrain.normalize_rectangles(invalid)

    def test_catalog_source_urls_require_the_verified_archive_and_areoid_product(self):
        ctx = "https://astrogeo-ard.s3-us-west-2.amazonaws.com/mars/mro/ctx/controlled/usgs/a/dem.tif"
        hrsc = "https://hrscteam.dlr.de/public/data/HMC30/MC20E/HMC_20E10_da5.tif"
        self.assertTrue(terrain._trusted_url(ctx, "ctx"))
        self.assertTrue(terrain._trusted_url(hrsc, "hrsc"))
        for invalid in (ctx.replace("https:", "http:"), ctx + "?token=secret", ctx + "#part",
                        ctx.replace(".com/", ".com.evil.invalid/"), ctx.replace("https://", "https://user@"),
                        ctx.replace("/controlled/usgs/", "/unrelated/")):
            self.assertFalse(terrain._trusted_url(invalid, "ctx"), invalid)
        self.assertFalse(terrain._trusted_url(hrsc.replace("_da5", "_dt5"), "hrsc"),
                         "Sphere-relative elevations cannot replace areoid elevations")

    def test_bundled_catalog_is_metadata_only_and_has_no_false_global_dateline_bands(self):
        with patch.object(terrain.jezero, "jezero_metadata", return_value={"available": False}), \
                patch.object(terrain.rasterio, "open") as open_raster:
            sources = terrain._load_sources()
            metadata = terrain.detail_metadata()
        open_raster.assert_not_called()
        self.assertGreater(len(sources), 40000)
        self.assertEqual(metadata["source_count"], len(sources))
        self.assertEqual(metadata["source_counts"]["hrsc"], 20)
        self.assertEqual(len({item["id"] for item in sources}), len(sources))
        self.assertEqual(sources, sorted(sources, key=terrain._priority))
        crossing = [item for item in sources if len(item["rectangles"]) == 2]
        self.assertGreaterEqual(len(crossing), 16)
        for item in sources:
            self.assertEqual(item["maximum_level"], 10 if item["kind"] == "hrsc" else 11)
            for r in item["rectangles"]:
                self.assertTrue(-180 <= r["west"] < r["east"] <= 180)
                self.assertLess(r["east"] - r["west"], 180)
                self.assertTrue(-90 <= r["south"] < r["north"] <= 90)

    def test_malformed_catalog_source_is_rejected_before_any_raster_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "catalog.json.gz"
            item = dict(id="bad", bbox=[1, 1, 2, 2], resolution_m=20,
                        url="https://unverified.invalid/elevation.tif")
            path.write_bytes(gzip.compress(json.dumps({"items": [item]}).encode()))
            with patch.object(terrain, "CTX_CATALOG", path), \
                    patch.object(terrain.rasterio, "open") as open_raster, \
                    self.assertRaises(ValueError):
                terrain._load_sources()
            open_raster.assert_not_called()

    def test_candidate_index_matches_independent_inclusive_overlap_oracle_without_count_cap(self):
        # A deliberately dense stack ensures an arbitrary top-N limit cannot hide
        # valid data or select a different source on neighbouring tile edges.
        sources = [source(f"ctx:{i:03}", [10 + i * .001, 20, 12, 22]) for i in range(80)]
        sources += [source("ctx:edge", [11.25, 21, 11.4, 21.2]),
                    dict(source("ctx:dateline", [179.9, -1, 180, 1]),
                         rectangles=terrain.normalize_rectangles([179.9, -1, 180.1, 1]))]
        sources = sorted(sources, key=terrain._priority)
        with patch.object(terrain, "_load_sources", return_value=sources):
            for bounds in ([10.5, 20.5, 11.25, 21], [11.25, 21, 11.8, 21.5],
                           [179.95, -.5, 180, .5], [-180, -.5, -179.95, .5], [0, 0, .1, .1]):
                w, s, e, n = bounds
                expected = [item["id"] for item in sources if any(
                    w <= r["east"] and e >= r["west"] and s <= r["north"] and n >= r["south"]
                    for r in item["rectangles"])]
                actual = [item["id"] for item in terrain._candidates(bounds)]
                self.assertEqual(actual, expected, bounds)
            self.assertGreater(len(terrain._candidates([10.5, 20.5, 11.25, 21])), 64)

    def test_native_radius_pixel_centers_scale_and_offset_keep_physical_heights(self):
        bounds = (77.001, 18.001, 77.061, 18.041)
        scale = math.pi * RADIUS / 180
        left, top = 77 * scale - 1600, 18.05 * scale + 1600
        affine = Affine(20, 0, left, 0, -20, top)
        rows, cols = np.indices((500, 500))
        raw = -3000 + (cols + .5) * 1.0 + (rows + .5) * .8
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "native-radius.tif"
            write_raster(path, raw, affine, scale=2, offset=100)
            with rasterio.open(path) as ds:
                heights, alpha = terrain._sample_dataset(ds, bounds)
        longitude = np.linspace(bounds[0], bounds[2], terrain.GRID_SIZE)
        latitude = np.linspace(bounds[3], bounds[1], terrain.GRID_SIZE)
        expected = 2 * (-3000 + (longitude[None, :] * scale - left) * .05
                        + (top - latitude[:, None] * scale) * .04) + 100
        np.testing.assert_allclose(heights, expected, rtol=0, atol=.002)
        np.testing.assert_array_equal(alpha, np.ones(SHAPE, "float32"))
        self.assertEqual(heights.dtype, np.float32)

    def test_source_nodata_has_no_weight_and_does_not_become_zero_elevation(self):
        scale = math.pi * RADIUS / 180
        affine = Affine(20, 0, 77 * scale, 0, -20, 18.1 * scale)
        values = np.full((300, 300), -2500, "float32")
        values[140:160, 140:160] = -9999
        # Bounds are exact centres of outer pixels; a central source gap stays NaN.
        bounds = ((affine.c + 10) / scale, (affine.f - 5990) / scale,
                  (affine.c + 5990) / scale, (affine.f - 10) / scale)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nodata.tif"
            write_raster(path, values, affine)
            with rasterio.open(path) as ds:
                heights, alpha = terrain._sample_dataset(ds, bounds)
        self.assertTrue(np.isnan(heights[128, 128]))
        self.assertEqual(alpha[128, 128], 0)
        self.assertFalse(np.any(heights == 0))
        self.assertGreater(alpha[65, 65], .99)
        self.assertTrue(np.all(alpha[~np.isfinite(heights)] == 0))
        self.assertTrue((alpha >= 0).all() and (alpha <= 1).all())

    def test_nonzero_projection_origin_parallel_and_offsets_match_native_proj_transform(self):
        crs = "+proj=eqc +lat_ts=30 +lat_0=5 +lon_0=180 +x_0=1234 +y_0=-4321 +R=3396000 +units=m +no_defs"
        geographic = "+proj=longlat +R=3396000 +no_defs"
        bounds = (179.95, 24.95, 180.02, 25.02)
        x, y = transform(geographic, crs, [bounds[0], bounds[2]], [bounds[3], bounds[1]])
        affine = Affine(50, 0, x[0] - 1500, 0, -50, y[0] + 1500)
        rows, cols = np.indices((200, 200))
        values = -3000 + (cols + .5) * 2 + (rows + .5) * 3
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "offset-projection.tif"
            write_raster(path, values, affine, crs=crs)
            with rasterio.open(path) as ds:
                heights, alpha = terrain._sample_dataset(ds, bounds)
        expected_nw = -3000 + (x[0] - affine.c) * .04 + (affine.f - y[0]) * .06
        expected_se = -3000 + (x[1] - affine.c) * .04 + (affine.f - y[1]) * .06
        self.assertAlmostEqual(float(heights[0, 0]), expected_nw, delta=.002)
        self.assertAlmostEqual(float(heights[-1, -1]), expected_se, delta=.002)
        np.testing.assert_array_equal(alpha, np.ones(SHAPE, "float32"))

    def test_independently_sampled_neighbour_windows_share_identical_edge_and_blend_weights(self):
        west, south, east, north = terrain.jezero.tile_bounds(11, 814, 2929)
        scale = math.pi * RADIUS / 180
        affine = Affine(20, 0, west * scale - 1600, 0, -20, north * scale + 1600)
        rows, cols = np.indices((500, 800))
        values = -3000 + cols * .5 + rows * .3
        # Nodata straddles the shared edge, so both distance-field halos must agree.
        edge_col = int((east * scale - affine.c) / 20)
        values[180:190, edge_col - 3:edge_col + 4] = -9999
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "seams.tif"
            write_raster(path, values, affine)
            with rasterio.open(path) as ds:
                current, current_alpha = terrain._sample_dataset(ds, (west, south, east, north))
                right, right_alpha = terrain._sample_dataset(ds, terrain.jezero.tile_bounds(11, 814, 2930))
        np.testing.assert_array_equal(current[:, -1], right[:, 0])
        np.testing.assert_array_equal(current_alpha[:, -1], right_alpha[:, 0])
        self.assertTrue(np.any(current_alpha[:, -1] == 0))
        self.assertTrue(np.any(current_alpha[:, -1] == 1))

    def test_dateline_window_uses_source_continuous_longitude_domain(self):
        scale = math.pi * RADIUS / 180
        affine = Affine(50, 0, 179.9 * scale, 0, -50, .1 * scale)
        rows, cols = np.indices((300, 400))
        values = -1000 + cols + rows * .1
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "crosses-dateline.tif"
            write_raster(path, values, affine)
            with rasterio.open(path) as ds:
                positive, positive_alpha = terrain._sample_dataset(ds, (180.01, -.02, 180.04, .02))
                negative, negative_alpha = terrain._sample_dataset(ds, (-179.99, -.02, -179.96, .02))
        np.testing.assert_array_equal(positive, negative)
        np.testing.assert_array_equal(positive_alpha, negative_alpha)
        self.assertTrue(np.isfinite(negative).all())

    def test_unsupported_earth_coordinates_and_oversized_source_reads_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "earth.tif"
            write_raster(path, np.ones((10, 10)), Affine(.01, 0, 77, 0, -.01, 18.1), crs="EPSG:4326")
            with rasterio.open(path) as ds, self.assertRaises(ValueError):
                terrain._sample_dataset(ds, (77.01, 18.02, 77.05, 18.05))
            scale = math.pi * RADIUS / 180
            path = Path(temporary) / "mars.tif"
            write_raster(path, np.full((300, 300), -2500), Affine(20, 0, 77 * scale, 0, -20, 18.1 * scale))
            with rasterio.open(path) as ds, patch.object(terrain, "MAX_WINDOW_PIXELS", 100), self.assertRaises(ValueError):
                terrain._sample_dataset(ds, (77.01, 18.02, 77.05, 18.05))
            path = Path(temporary) / "no-crs.tif"
            write_raster(path, np.full((10, 10), -2500), Affine(20, 0, 10000, 0, -20, 10000), crs=None)
            with rasterio.open(path) as ds, self.assertRaises(ValueError):
                terrain._sample_dataset(ds, (77.01, 18.02, 77.05, 18.05))

    def test_overlap_uses_fixed_priority_and_real_fallback_in_source_holes(self):
        baseline = np.full(SHAPE, -3000, "float32")
        first = np.full(SHAPE, -2800, "float32")
        first[0, 0] = np.nan
        second = np.full(SHAPE, -2600, "float32")
        second[0, 0] = np.nan
        first_weight = np.full(SHAPE, .5, "float32")
        first_weight[1, 1] = 1
        candidates = [source("ctx:first", [0, 0, 1, 1]), source("hrsc:second", [0, 0, 1, 1], "hrsc", 50)]
        with patch.object(terrain, "_candidates", return_value=candidates), \
                patch.object(terrain, "_global_heights", return_value=baseline), \
                patch.object(terrain, "_sample_source", side_effect=[(first, first_weight), (second, np.ones(SHAPE))]):
            result = terrain._compose_tile(11, 814, 2929)
        self.assertEqual(result["heights"][0, 0], -3000)
        self.assertEqual(result["heights"][1, 1], -2800)
        self.assertEqual(result["heights"][2, 2], -2700)
        self.assertEqual(result["used"], ["ctx:first", "hrsc:second"])
        self.assertEqual(result["status"], "detail")
        self.assertTrue(np.isfinite(result["heights"]).all())

    def test_source_failure_preserves_global_height_and_reports_fallback(self):
        candidates = [source("ctx:unavailable", [0, 0, 1, 1])]
        baseline = np.full(SHAPE, -3175.25, "float32")
        with patch.object(terrain, "_candidates", return_value=candidates), \
                patch.object(terrain, "_global_heights", return_value=baseline), \
                patch.object(terrain, "_sample_source", side_effect=OSError("source unavailable")):
            result = terrain._compose_tile(11, 814, 2929)
        np.testing.assert_array_equal(result["heights"], baseline)
        self.assertEqual(result["used"], [])
        self.assertEqual(result["failed"], ["ctx:unavailable"])
        self.assertEqual(result["status"], "global-fallback")
        with patch.object(terrain, "_candidates", return_value=[]), \
                patch.object(terrain, "_global_heights", return_value=np.full(SHAPE, np.nan)), \
                self.assertRaises(ValueError):
            terrain._compose_tile(11, 814, 2929)

    def test_source_without_valid_pixels_keeps_real_global_fallback(self):
        baseline = np.full(SHAPE, -3175.25, "float32")
        with patch.object(terrain, "_candidates", return_value=[source("ctx:gap", [0, 0, 1, 1])]), \
                patch.object(terrain, "_global_heights", return_value=baseline), \
                patch.object(terrain, "_sample_source", return_value=(np.full(SHAPE, np.nan), np.zeros(SHAPE))):
            result = terrain._compose_tile(11, 814, 2929)
        np.testing.assert_array_equal(result["heights"], baseline)
        self.assertEqual(result["status"], "global-fallback")
        self.assertEqual(result["used"], [])

    def test_temporary_source_failure_cache_expires_and_recovers_without_restart(self):
        fallback = dict(heights=np.full(SHAPE, -3000, "<f4"), used=[], failed=["ctx:timeout"], status="global-fallback")
        success = dict(heights=np.full(SHAPE, -2800, "<f4"), used=["ctx:recovered"], failed=[], status="detail")
        clock = [100.0]
        with patch.object(terrain.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(terrain, "_compose_tile", side_effect=[fallback, success, success]) as compose:
            self.assertIs(terrain._cached_tile(11, 814, 2929), fallback)
            clock[0] += terrain.FALLBACK_TTL_S - .1
            self.assertIs(terrain._cached_tile(11, 814, 2929), fallback)
            self.assertEqual(compose.call_count, 1)
            clock[0] += .2
            self.assertIs(terrain._cached_tile(11, 814, 2929), success)
            clock[0] += terrain.SUCCESS_TTL_S - .1
            self.assertIs(terrain._cached_tile(11, 814, 2929), success)
            self.assertEqual(compose.call_count, 2)
            clock[0] += .2
            self.assertIs(terrain._cached_tile(11, 814, 2929), success)
            self.assertEqual(compose.call_count, 3)

    def test_tile_cache_has_bounded_lru_retention(self):
        tile = dict(heights=np.full(SHAPE, -3000, "<f4"), used=["ctx:test"], failed=[], status="detail")
        with patch.object(terrain, "TILE_CACHE_LIMIT", 3), patch.object(terrain, "_compose_tile", return_value=tile):
            for x in range(3):
                terrain._cached_tile(11, 1, x)
            terrain._cached_tile(11, 1, 0)
            terrain._cached_tile(11, 1, 3)
        self.assertEqual(len(terrain._tile_cache), 3)
        self.assertIn((11, 1, 0), terrain._tile_cache)
        self.assertNotIn((11, 1, 1), terrain._tile_cache)

    def test_concurrent_requests_share_one_source_read_and_failures_allow_retry(self):
        tile = dict(heights=np.full(SHAPE, -3000, "<f4"), used=["ctx:test"], failed=[], status="detail")
        ready = threading.Barrier(4)
        entered = threading.Event()
        release = threading.Event()
        duplicate = threading.Event()
        count_lock = threading.Lock()
        calls = [0]

        def compose(*args):
            with count_lock:
                calls[0] += 1
                if calls[0] > 1:
                    duplicate.set()
            entered.set()
            if not release.wait(3):
                raise AssertionError("Test did not release the source read")
            return tile

        def request():
            ready.wait(timeout=3)
            return terrain._cached_tile(11, 814, 2929)

        with patch.object(terrain, "_compose_tile", side_effect=compose), ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(request) for _ in range(4)]
            try:
                self.assertTrue(entered.wait(3), "No source read started")
                duplicate.wait(.2)
            finally:
                release.set()
            for future in futures:
                self.assertIs(future.result(timeout=3), tile)
        self.assertEqual(calls[0], 1, "Concurrent requests must not download the same source window repeatedly")
        with patch.object(terrain, "_compose_tile", side_effect=[ValueError("temporary source failure"), tile]) as compose:
            with self.assertRaises(ValueError):
                terrain._cached_tile(11, 814, 2930)
            self.assertIs(terrain._cached_tile(11, 814, 2930), tile)
            self.assertEqual(compose.call_count, 2)

    def test_binary_response_reports_source_provenance_and_rejects_invalid_native_tiles(self):
        app = FastAPI()
        app.include_router(terrain.router)
        client = TestClient(app)
        tile = dict(heights=np.full(SHAPE, -3000.5, "<f4"), used=["hrsc:actual-source"], failed=[], status="detail")
        with patch.object(terrain, "_cached_tile", return_value=tile) as get_tile:
            response = client.get("/terrain/detail/10/384/928.bin")
            self.assertEqual(response.status_code, 200)
            np.testing.assert_array_equal(np.frombuffer(response.content, "<f4").reshape(SHAPE), tile["heights"])
            self.assertEqual(response.headers["x-terrain-detail-status"], "detail")
            self.assertEqual(response.headers["x-terrain-source-ids"], "hrsc:actual-source")
            self.assertEqual(response.headers["x-terrain-grid-size"], "257")
            self.assertIn("max-age=3600", response.headers["cache-control"])
            for route in ("7/0/0", "12/0/0", "8/-1/0", "8/256/0", "8/0/512"):
                self.assertEqual(client.get(f"/terrain/detail/{route}.bin").status_code, 404)
            self.assertEqual(get_tile.call_count, 1)
        with patch.object(terrain, "_cached_tile", side_effect=ValueError("real samples unavailable")):
            response = client.get("/terrain/detail/10/384/928.bin")
            self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
