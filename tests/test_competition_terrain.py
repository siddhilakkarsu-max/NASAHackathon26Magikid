"""Measured crop provenance, metric geometry, and conservative gap checks."""
import copy
import json
import math
import shutil

import numpy as np
import pytest

import competition_terrain as terrain_module
from competition_terrain import Terrain, TerrainUnavailable, calculate_slope, load_terrain


def small_terrain(valid=None, slope=None, thermal_valid=None):
    """Analytic unit-test fixture only; production has no synthetic data path."""
    size = 6
    elevation = np.tile(np.arange(size, dtype=np.float32), (size, 1))
    valid = np.ones((size, size), bool) if valid is None else valid
    slope = np.zeros((size, size), np.float32) if slope is None else slope
    thermal_valid = np.ones((size, size), bool) if thermal_valid is None else thermal_valid
    manifest = {"grid": {"resolution_m": 20}, "dataset_version": "test-fixture",
                "artifact": {"sha256": "test"}, "projection": {"origin_easting_m": 0, "origin_northing_m": 0}}
    return Terrain(manifest, elevation, valid, slope,
                   np.where(thermal_valid, 300, np.nan).astype(np.float32), thermal_valid)


def test_packaged_real_crop_and_manifest_are_consistent():
    terrain = load_terrain()
    assert terrain.shape == (321, 321)
    assert terrain.width_m == terrain.height_m == 6400
    assert terrain.resolution_m == 20
    assert terrain.valid.sum() == 103041
    assert -2600 < terrain.elevation_m.min() < -2580
    assert -2400 < terrain.elevation_m.max() < -2380
    assert terrain.manifest["elevation"]["source_sha256"] == terrain_module.SOURCE_SHA256
    assert terrain.manifest["thermal_inertia"]["grid_resolution_degrees"] == 0.125
    assert len(terrain.manifest["thermal_inertia"]["cells"]) == 4
    assert terrain.manifest["artifact"]["size_bytes"] < 1_000_000
    assert not terrain.elevation_m.flags.writeable


def test_coordinate_round_trip_and_north_first_axes():
    terrain = load_terrain()
    bounds = terrain.metadata()["geographic_bounds"]
    assert terrain.local_to_geo(0, 0) == pytest.approx((bounds["west"], bounds["south"]))
    assert terrain.local_to_geo(6400, 6400) == pytest.approx((bounds["east"], bounds["north"]))
    for point in ((0, 0), (6400, 6400), (3153.2, 1457.6)):
        assert terrain.geo_to_local(*terrain.local_to_geo(*point)) == pytest.approx(point, abs=1e-8)
    assert terrain.sample(0, 6400)["elevation_m"] == terrain.elevation_m[0, 0]
    assert terrain.sample(6400, 0)["elevation_m"] == terrain.elevation_m[-1, -1]


def test_packaged_elevation_exactly_matches_source_pixels_when_installed():
    source = terrain_module.ROOT / "data" / "M20_JezeroCrater_CTXDEM_20m.tif"
    if not source.exists():
        pytest.skip("Large source is optional; portable crop is checked independently")
    import rasterio
    from rasterio.windows import Window
    terrain = load_terrain()
    window = terrain.manifest["grid"]["source_window"]
    with rasterio.open(source) as dataset:
        measured = dataset.read(1, window=Window(window["column"], window["row"], window["width"], window["height"]))
    np.testing.assert_array_equal(terrain.elevation_m, measured)


def test_central_difference_slope_uses_metric_spacing_and_masks_stencil():
    rows, cols = np.indices((7, 7))
    elevation = cols * 20 * 0.3 - rows * 20 * 0.4
    valid = np.ones(elevation.shape, bool)
    slopes, supported = calculate_slope(elevation, valid, 20)
    np.testing.assert_allclose(slopes[1:-1, 1:-1], math.degrees(math.atan(0.5)), rtol=1e-6)
    assert not supported[0].any()
    valid[3, 3] = False
    slopes, supported = calculate_slope(elevation, valid, 20)
    assert not supported[2:5, 2:5].any()
    assert np.isnan(slopes[2:5, 2:5]).all()


def test_bilinear_elevation_preserves_node_values_and_midpoint():
    terrain = small_terrain()
    assert terrain.sample(20, 40)["elevation_m"] == 1
    assert terrain.sample(30, 50)["elevation_m"] == 1.5
    assert terrain.sample(100, 0)["elevation_m"] == 5


@pytest.mark.parametrize("point", [(-0.001, 30), (101, 50), (30, 101), (math.nan, 20), (30, math.inf)])
def test_outside_or_nonfinite_points_are_rejected(point):
    terrain = small_terrain()
    assert not terrain.valid_point(*point)
    assert not terrain.segment_is_valid((10, 10), point)
    with pytest.raises(ValueError):
        terrain.sample(*point)


def test_segment_cannot_jump_a_missing_node_or_touch_its_corner():
    valid = np.ones((6, 6), bool)
    valid[2, 2] = False
    terrain = small_terrain(valid=valid)
    # Safe endpoints alone are not sufficient for a valid segment.
    assert terrain.valid_point(1, 50) and terrain.valid_point(99, 50)
    assert not terrain.segment_is_valid((1, 50), (99, 50))
    # Along a shared cell edge, both sides must be supported.
    assert not terrain.segment_is_valid((20, 1), (20, 99))
    # A diagonal through a cell corner must include the corner-touching cells.
    assert not terrain.segment_is_valid((1, 1), (99, 99))
    assert terrain.segment_is_valid((1, 1), (99, 1))


def test_segment_rejects_steep_node_even_when_endpoints_are_safe():
    slope = np.zeros((6, 6), np.float32)
    slope[2, 2] = 30
    terrain = small_terrain(slope=slope)
    assert terrain.segment_is_valid((1, 50), (99, 50))
    assert not terrain.segment_is_valid((1, 50), (99, 50), max_slope_degrees=25)


def test_unknown_thermal_does_not_invent_a_value_or_forbid_measured_elevation():
    terrain = small_terrain(thermal_valid=np.zeros((6, 6), bool))
    assert terrain.segment_is_valid((1, 1), (99, 99))
    assert terrain.sample(50, 50)["thermal_inertia"] is None
    assert all(value is None for row in terrain.public_grid(step=1)["thermal_inertia"] for value in row)


def test_thermal_sampling_keeps_coarse_boundaries_without_bilinear_blend():
    terrain = load_terrain()
    for longitude, expected in ((77.374999, 284.9), (77.375001, 323.2)):
        x, y = terrain.geo_to_local(longitude, 18.45)
        assert terrain.sample(x, y)["thermal_inertia"] == expected
    grid = terrain.public_grid()
    represented = {round(value, 1) for row in grid["thermal_inertia"] for value in row if value is not None}
    assert represented == {284.9, 289.3, 316.4, 323.2}
    assert grid["shape"] == [161, 161]
    assert grid["source_resolution_m"] == 20
    assert grid["resolution_m"] == 40
    json.dumps(grid, allow_nan=False)


def test_suggested_reference_route_is_supported_and_below_slope_limit():
    terrain = load_terrain()
    points = terrain.metadata()["suggested_reference_route_m"]
    assert len(points) == 4
    assert all(terrain.segment_is_valid(a, b, max_slope_degrees=25) for a, b in zip(points, points[1:]))
    length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    assert 300 <= length <= 800


def test_missing_or_corrupt_data_is_unavailable_without_fallback(tmp_path):
    with pytest.raises(TerrainUnavailable, match="Measured Jezero competition terrain is unavailable"):
        load_terrain(tmp_path)
    manifest = copy.deepcopy(load_terrain().manifest)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / manifest["artifact"]["filename"]).write_bytes(b"corrupt source")
    with pytest.raises(TerrainUnavailable):
        load_terrain(tmp_path)


def test_semantic_identity_binds_coordinate_units_and_not_editorial_dates():
    terrain = load_terrain()
    manifest = copy.deepcopy(terrain.manifest)
    manifest["retrieved_at"] = "2099-01-01"
    manifest["name"] = "Editorial display name"
    assert terrain_module.semantic_identity(manifest) == terrain.dataset_sha256
    manifest["grid"]["resolution_m"] = 40
    assert terrain_module.semantic_identity(manifest) != terrain.dataset_sha256
    assert terrain.metadata()["artifact_sha256"] == terrain.manifest["artifact"]["sha256"]
    assert terrain.dataset_sha256 != terrain.artifact_sha256


@pytest.mark.parametrize("section,key,value", [
    ("projection", "origin_easting_m", 1),
    ("projection", "radius_m", 3396160),
    ("grid", "resolution_m", 40),
    ("geographic_bounds", "west", 77),
])
def test_inconsistent_projection_or_bounds_fail_closed(tmp_path, section, key, value):
    manifest = copy.deepcopy(load_terrain().manifest)
    manifest[section][key] = value
    artifact = manifest["artifact"]["filename"]
    shutil.copyfile(terrain_module.DATA_DIRECTORY / artifact, tmp_path / artifact)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TerrainUnavailable):
        load_terrain(tmp_path)
