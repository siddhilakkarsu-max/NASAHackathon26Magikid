"""Portable, measured Jezero terrain for the route-planning competition.

The bundled crop contains native 20 m CTX elevation samples. Local coordinates
are metres east/north from the southwestern sample, in the source projection.
Missing or corrupt data is an error: this module never creates substitute terrain.
"""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
DATA_DIRECTORY = ROOT / "data" / "competition"
DATASET_VERSION = "jezero-west-delta-ctx20-v1"
SOURCE_URL = "https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/ScienceInvestigationMaps_JPL/M20_JezeroCrater_CTXDEM_20m.tif"
SOURCE_DOCUMENTATION = "https://astrogeology.usgs.gov/search/map/mars_2020_science_investigation_ctx_dem_mosaic"
SOURCE_SHA256 = "ba7f706ea1b5d63a562f28a7dcf7a7f3c79bce7f048e6974b57e8a33c30d1ba2"
THERMAL_SHA256 = "eaa0f4f6fc2830268d26d9c7cdd7ee690a29deb403907f0a5e883103400c1ef0"
MARS_RADIUS_M = 3396190.0
STANDARD_PARALLEL_DEGREES = 18.4663
NATIVE_SOURCE_TRANSFORM = (20.0, 0.0, 4329000.0, 0.0, -20.0, 1143420.0)
NATIVE_CROP = {"row": 2309, "column": 985, "height": 321, "width": 321}


class TerrainUnavailable(RuntimeError):
    """The competition's measured dataset is missing, corrupt, or incompatible."""


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_identity(manifest):
    """Bind measured bytes and their interpretation, excluding prose/dates."""
    identity = {"dataset_version": manifest["dataset_version"],
                "artifact_sha256": manifest["artifact"]["sha256"]}
    keys = {
        "grid": ("shape", "resolution_m", "row_order", "column_order", "sample_location", "source_window", "source_transform"),
        "projection": ("radius_m", "standard_parallel_degrees", "central_meridian_degrees", "origin_easting_m", "origin_northing_m",
                       "origin_longitude", "origin_latitude", "x_axis", "y_axis", "latitude_type", "longitude_direction"),
        "geographic_bounds": ("west", "south", "east", "north"),
        "elevation": ("units", "resolution_m", "source_sha256", "vertical_reference"),
        "slope": ("units", "resolution_m", "derivative_baseline_m", "required_stencil_nodes"),
        "thermal_inertia": ("units", "available", "grid_resolution_degrees", "original_product_grid_degrees",
                            "source_dataset_id", "source_derived_sha256", "cells"),
    }
    for section, fields in keys.items():
        source = manifest.get(section, {})
        identity[section] = {field: source.get(field) for field in fields}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def calculate_slope(elevation_m, valid, resolution_m):
    """Central differences; require the entire surrounding 3×3 measured stencil.

    The outermost ring is invalid. The builder reads a halo then discards it,
    so the competition boundary retains independently supported slope values.
    """
    elevation = np.asarray(elevation_m, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool) & np.isfinite(elevation)
    if elevation.ndim != 2 or valid.shape != elevation.shape or resolution_m <= 0:
        raise ValueError("Slope requires a 2D elevation grid and positive spacing")
    supported = np.zeros(elevation.shape, dtype=bool)
    inner = np.ones((max(0, elevation.shape[0] - 2), max(0, elevation.shape[1] - 2)), dtype=bool)
    for row in range(3):
        for col in range(3):
            inner &= valid[row:row + inner.shape[0], col:col + inner.shape[1]]
    supported[1:-1, 1:-1] = inner
    slopes = np.full(elevation.shape, np.nan, dtype=np.float32)
    dz_dx = (elevation[1:-1, 2:] - elevation[1:-1, :-2]) / (2 * resolution_m)
    dz_dy = (elevation[:-2, 1:-1] - elevation[2:, 1:-1]) / (2 * resolution_m)
    slopes[1:-1, 1:-1] = np.where(inner, np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))), np.nan)
    return slopes, supported


class Terrain:
    """An immutable measured node grid; array row zero is the northern edge."""

    def __init__(self, manifest, elevation_m, valid, slope_degrees, thermal_inertia, thermal_valid):
        self.manifest = manifest
        self.elevation_m = np.asarray(elevation_m, dtype=np.float32)
        self.valid = np.asarray(valid, dtype=bool)
        self.slope_degrees = np.asarray(slope_degrees, dtype=np.float32)
        self.thermal_inertia = np.asarray(thermal_inertia, dtype=np.float32)
        self.thermal_valid = np.asarray(thermal_valid, dtype=bool)
        self.shape = self.elevation_m.shape
        if len(self.shape) != 2 or min(self.shape) < 2:
            raise ValueError("Terrain must have at least two nodes per axis")
        arrays = (self.valid, self.slope_degrees, self.thermal_inertia, self.thermal_valid)
        if any(array.shape != self.shape for array in arrays):
            raise ValueError("Terrain layers must be aligned")
        if not np.isfinite(self.elevation_m[self.valid]).all() or not np.isfinite(self.slope_degrees[self.valid]).all():
            raise ValueError("Valid elevation and slope nodes must be finite")
        if not np.isfinite(self.thermal_inertia[self.thermal_valid]).all():
            raise ValueError("Valid thermal inertia nodes must be finite")
        self.resolution_m = float(manifest["grid"]["resolution_m"])
        if not math.isfinite(self.resolution_m) or self.resolution_m <= 0:
            raise ValueError("Invalid grid resolution")
        self.width_m = (self.shape[1] - 1) * self.resolution_m
        self.height_m = (self.shape[0] - 1) * self.resolution_m
        self.x_min = self.y_min = 0.0
        self.x_max, self.y_max = self.width_m, self.height_m
        self.dataset_version = manifest["dataset_version"]
        self.artifact_sha256 = manifest["artifact"]["sha256"]
        self.dataset_sha256 = semantic_identity(manifest)
        self._origin_easting = float(manifest["projection"]["origin_easting_m"])
        self._origin_northing = float(manifest["projection"]["origin_northing_m"])
        self._longitude_scale = MARS_RADIUS_M * math.cos(math.radians(STANDARD_PARALLEL_DEGREES))
        for array in (self.elevation_m, *arrays):
            array.flags.writeable = False

    def local_to_geo(self, x, y):
        """Return east-positive planetocentric (longitude, latitude), in degrees."""
        return (math.degrees((float(x) + self._origin_easting) / self._longitude_scale),
                math.degrees((float(y) + self._origin_northing) / MARS_RADIUS_M))

    def geo_to_local(self, longitude, latitude):
        return (math.radians(float(longitude)) * self._longitude_scale - self._origin_easting,
                math.radians(float(latitude)) * MARS_RADIUS_M - self._origin_northing)

    def _inside(self, x, y):
        return (math.isfinite(x) and math.isfinite(y)
                and 0 <= x <= self.width_m and 0 <= y <= self.height_m)

    def _touching_cells(self, x, y):
        """Include both cells at an exact edge and all four at a corner."""
        col = x / self.resolution_m
        row = (self.height_m - y) / self.resolution_m
        cols = {math.floor(col)}
        rows = {math.floor(row)}
        if abs(col - round(col)) < 1e-9:
            cols = {round(col) - 1, round(col)}
        if abs(row - round(row)) < 1e-9:
            rows = {round(row) - 1, round(row)}
        return {(r, c) for r in rows for c in cols
                if 0 <= r < self.shape[0] - 1 and 0 <= c < self.shape[1] - 1}

    def _cells_valid(self, cells, max_slope_degrees=None):
        if not cells:
            return False
        rows, cols = np.asarray(tuple(cells), dtype=int).T
        for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)):
            if not self.valid[rows + dr, cols + dc].all():
                return False
            if max_slope_degrees is not None and np.any(self.slope_degrees[rows + dr, cols + dc] > max_slope_degrees):
                return False
        return True

    def valid_point(self, x, y, max_slope_degrees=None):
        try:
            x, y = float(x), float(y)
        except (TypeError, ValueError):
            return False
        return self._inside(x, y) and self._cells_valid(self._touching_cells(x, y), max_slope_degrees)

    def segment_is_valid(self, start_xy, end_xy, max_slope_degrees=None):
        """Check every interpolation cell touched, including edge/corner contacts.

        Subdividing at all grid crossings prevents short no-data or steep cells
        from being skipped by long segments. No-data cells remain impassable.
        """
        try:
            x0, y0 = map(float, start_xy)
            x1, y1 = map(float, end_xy)
        except (TypeError, ValueError):
            return False
        if not self._inside(x0, y0) or not self._inside(x1, y1):
            return False
        cuts = [0.0, 1.0]
        for start, end in ((x0, x1), (y0, y1)):
            if end != start:
                first = math.floor(min(start, end) / self.resolution_m) + 1
                last = math.ceil(max(start, end) / self.resolution_m)
                cuts.extend((index * self.resolution_m - start) / (end - start)
                            for index in range(first, last))
        cuts = sorted(set(cuts))
        checks = cuts + [(a + b) / 2 for a, b in zip(cuts, cuts[1:])]
        cells = set()
        for fraction in checks:
            cells.update(self._touching_cells(x0 + fraction * (x1 - x0), y0 + fraction * (y1 - y0)))
        return self._cells_valid(cells, max_slope_degrees)

    def _bilinear(self, values, x, y):
        col, row = x / self.resolution_m, (self.height_m - y) / self.resolution_m
        c, r = min(int(col), self.shape[1] - 2), min(int(row), self.shape[0] - 2)
        fx, fy = col - c, row - r
        return float((1 - fy) * ((1 - fx) * values[r, c] + fx * values[r, c + 1])
                     + fy * ((1 - fx) * values[r + 1, c] + fx * values[r + 1, c + 1]))

    def sample(self, x, y):
        x, y = float(x), float(y)
        if not self.valid_point(x, y):
            raise ValueError("Point lies outside measured competition terrain or touches a data gap")
        # Thermal cells are deliberately not bilinearly interpolated. Preserve
        # their coarse geographic boundaries instead of creating fine structure.
        longitude, latitude = self.local_to_geo(x, y)
        inertia = None
        for cell in self.manifest.get("thermal_inertia", {}).get("cells", []):
            bounds = cell["geographic_bounds"]
            if bounds["west"] <= longitude < bounds["east"] and bounds["south"] < latitude <= bounds["north"]:
                inertia = cell["value"] if cell["valid"] else None
                break
        return {"elevation_m": self._bilinear(self.elevation_m, x, y),
                "slope_degrees": self._bilinear(self.slope_degrees, x, y),
                "thermal_inertia": inertia}

    def metadata(self):
        return {"available": True, "dataset_version": self.dataset_version,
                "dataset_sha256": self.dataset_sha256, "artifact_sha256": self.artifact_sha256,
                "name": self.manifest["name"],
                "width_m": self.width_m, "height_m": self.height_m,
                "resolution_m": self.resolution_m, "shape": list(self.shape),
                "metric_bounds": {"x_min": 0, "y_min": 0, "x_max": self.width_m, "y_max": self.height_m},
                "geographic_bounds": self.manifest["geographic_bounds"],
                "boundary_m": [[0, 0], [self.width_m, 0], [self.width_m, self.height_m], [0, self.height_m], [0, 0]],
                "projection": self.manifest["projection"], "elevation": self.manifest["elevation"],
                "slope": self.manifest["slope"], "thermal_inertia": self.manifest["thermal_inertia"],
                "limitations": self.manifest["limitations"],
                "suggested_reference_route_m": self.manifest.get("suggested_reference_route_m", [])}

    def public_grid(self, step=2):
        if not isinstance(step, int) or step < 1 or (self.shape[0] - 1) % step or (self.shape[1] - 1) % step:
            raise ValueError("Display grid step must divide both terrain dimensions")
        def values(array, mask):
            small, supported = array[::step, ::step], mask[::step, ::step]
            return np.where(supported & np.isfinite(small), small.astype(object), None).tolist()
        return {"elevation_m": values(self.elevation_m, self.valid),
                "slope_degrees": values(self.slope_degrees, self.valid),
                "thermal_inertia": values(self.thermal_inertia, self.thermal_valid),
                "valid": self.valid[::step, ::step].tolist(),
                "thermal_valid": self.thermal_valid[::step, ::step].tolist(),
                "width_m": self.width_m, "height_m": self.height_m,
                "shape": list(self.elevation_m[::step, ::step].shape),
                "resolution_m": self.resolution_m * step, "source_resolution_m": self.resolution_m,
                "row_order": "north_to_south", "column_order": "west_to_east",
                "dataset_version": self.dataset_version, "dataset_sha256": self.dataset_sha256}


def _validate_manifest(manifest, terrain):
    """Reject coordinate metadata that contradicts the fixed native crop."""
    from rasterio.crs import CRS
    grid, projection = manifest["grid"], manifest["projection"]
    if (grid["shape"] != [321, 321] or terrain.resolution_m != 20
            or grid["source_window"] != NATIVE_CROP
            or grid["row_order"] != "north_to_south" or grid["column_order"] != "west_to_east"
            or not np.allclose(grid["source_transform"], NATIVE_SOURCE_TRANSFORM, rtol=0, atol=1e-6)):
        raise ValueError("Competition grid differs from the verified native source window")
    expected = {"radius_m": MARS_RADIUS_M, "standard_parallel_degrees": STANDARD_PARALLEL_DEGREES,
                "central_meridian_degrees": 0, "x_axis": "east", "y_axis": "north",
                "latitude_type": "planetocentric", "longitude_direction": "east"}
    if any(projection[key] != value for key, value in expected.items()):
        raise ValueError("Competition projection differs from the source projection")
    source_crs = CRS.from_wkt(projection["source_wkt"])
    expected_crs = CRS.from_string(f"+proj=eqc +lat_ts={STANDARD_PARALLEL_DEGREES} +lon_0=0 +R={MARS_RADIUS_M} +units=m +no_defs")
    if source_crs != expected_crs:
        raise ValueError("Source WKT conflicts with the metric coordinate definition")
    expected_easting = NATIVE_SOURCE_TRANSFORM[2] + (NATIVE_CROP["column"] + 0.5) * 20
    expected_northing = NATIVE_SOURCE_TRANSFORM[5] - (NATIVE_CROP["row"] + NATIVE_CROP["height"] - 0.5) * 20
    if (not math.isclose(terrain._origin_easting, expected_easting, rel_tol=0, abs_tol=1e-6)
            or not math.isclose(terrain._origin_northing, expected_northing, rel_tol=0, abs_tol=1e-6)):
        raise ValueError("Local origin does not match source pixel centres")
    west, south = terrain.local_to_geo(0, 0)
    east, north = terrain.local_to_geo(terrain.width_m, terrain.height_m)
    if any(not math.isclose(manifest["geographic_bounds"][key], value, rel_tol=0, abs_tol=1e-9)
           for key, value in zip(("west", "south", "east", "north"), (west, south, east, north))):
        raise ValueError("Geographic bounds contradict local projection")
    if (not math.isclose(projection["origin_longitude"], west, abs_tol=1e-9)
            or not math.isclose(projection["origin_latitude"], south, abs_tol=1e-9)
            or manifest["elevation"]["source_sha256"] != SOURCE_SHA256):
        raise ValueError("Source provenance or geographic origin is inconsistent")


def load_terrain(directory=None):
    """Load and verify the portable crop; no network or synthetic fallback."""
    directory = Path(directory) if directory is not None else DATA_DIRECTORY
    try:
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        filename = manifest["artifact"]["filename"]
        if Path(filename).name != filename or manifest["dataset_version"] != DATASET_VERSION:
            raise ValueError("Unexpected terrain artifact or version")
        artifact = directory / filename
        return _load_verified(str(manifest_path), manifest_path.stat().st_mtime_ns,
                              str(artifact), artifact.stat().st_mtime_ns, artifact.stat().st_size)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TerrainUnavailable("Measured Jezero competition terrain is unavailable. Restore data/competition or run python tools/build_competition_terrain.py with the verified USGS DEM installed.") from error


@lru_cache(maxsize=2)
def _load_verified(manifest_path, manifest_mtime, artifact_path, artifact_mtime, artifact_size):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if sha256_file(artifact_path) != manifest["artifact"]["sha256"]:
        raise ValueError("Competition terrain checksum mismatch")
    with np.load(artifact_path, allow_pickle=False) as archive:
        terrain = Terrain(manifest, *(archive[key] for key in
                          ("elevation_m", "valid", "slope_degrees", "thermal_inertia", "thermal_valid")))
    if list(terrain.shape) != manifest["grid"]["shape"] or not terrain.valid.any():
        raise ValueError("Competition terrain dimensions or coverage differ from the manifest")
    _validate_manifest(manifest, terrain)
    return terrain
