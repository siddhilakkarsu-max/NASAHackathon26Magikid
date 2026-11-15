"""Real USGS 20 m Jezero terrain, blended into the existing MOLA/HRSC globe.

Run ``python jezero_terrain.py --download`` once on each installation. The 86 MiB
source and derived validity feather are ignored by git. Requests never initiate
a large source download. Tiles contain metre-valued heights, never exaggerated.
"""
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import threading
import urllib.request

import lerc
import numpy as np
import rasterio
from affine import Affine
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from scipy.ndimage import distance_transform_edt, map_coordinates

import murray

ROOT = Path(__file__).resolve().parent
LOCAL_DEM = ROOT / "data" / "M20_JezeroCrater_CTXDEM_20m.tif"
SOURCE_URL = "https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/ScienceInvestigationMaps_JPL/M20_JezeroCrater_CTXDEM_20m.tif"
DOCUMENTATION_URL = "https://astrogeology.usgs.gov/search/map/mars_2020_science_investigation_ctx_dem_mosaic"
# Recorded from the verified USGS download, rather than a publisher-supplied checksum.
SOURCE_SHA256 = "ba7f706ea1b5d63a562f28a7dcf7a7f3c79bce7f048e6974b57e8a33c30d1ba2"
MARS_CRS = "+proj=longlat +R=3396190 +no_defs"
GRID_SIZE = 257
MIN_LEVEL, MAX_LEVEL = 8, 11
GLOBAL_LEVEL = 7
RESOLUTION_M = 20
BLEND_MARGIN_M = 1000
router = APIRouter()
_prepare_lock = threading.RLock()


def _signature(path):
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _feather_path(path):
    return path.with_name(path.stem + "_validity_feather.tif")


def _prepare_feather(path, signature):
    """A cached, bounded byte weight; zero at source edges and no-data holes."""
    feather = _feather_path(path)
    with _prepare_lock:
        if feather.exists():
            try:
                with rasterio.open(feather) as ds:
                    if (ds.tags().get("SOURCE_SIGNATURE") == signature
                            and ds.tags().get("BLEND_MARGIN_M") == str(BLEND_MARGIN_M)):
                        return feather
            except rasterio.errors.RasterioError:
                pass
        with rasterio.open(path) as ds:
            # This one-time local-mosaic mask is ~23 MB, not a global Mars grid.
            valid = np.pad(ds.read_masks(1) > 0, 1, constant_values=False)
            distance = distance_transform_edt(valid, sampling=(abs(ds.res[1]), abs(ds.res[0])))
            distance = distance[1:-1, 1:-1]
            weights = np.rint(np.clip((distance - max(ds.res)) / BLEND_MARGIN_M, 0, 1) * 255).astype("uint8")
            profile = ds.profile.copy()
            profile.update(dtype="uint8", count=1, nodata=None, compress="deflate", tiled=True,
                           blockxsize=256, blockysize=256)
            temporary = feather.with_suffix(".part.tif")
            with rasterio.open(temporary, "w", **profile) as dst:
                dst.write(weights, 1)
                dst.update_tags(SOURCE_SIGNATURE=signature, BLEND_MARGIN_M=str(BLEND_MARGIN_M))
            temporary.replace(feather)
    return feather


@lru_cache(maxsize=4)
def _source_info(path_string, signature):
    path = Path(path_string)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != SOURCE_SHA256:
        raise ValueError("The local raster differs from the verified USGS source")
    minimum, maximum, valid_count = math.inf, -math.inf, 0
    with rasterio.open(path) as ds:
        bounds = transform_bounds(ds.crs, MARS_CRS, *ds.bounds, densify_pts=21)
        for _, window in ds.block_windows(1):
            values = ds.read(1, window=window, masked=True)
            if values.count():
                minimum = min(minimum, float(values.min()))
                maximum = max(maximum, float(values.max()))
                valid_count += int(values.count())
        if not valid_count:
            raise ValueError("The local elevation mosaic contains no valid heights")
    _prepare_feather(path, signature)
    return {"rectangle": dict(zip(("west", "south", "east", "north"), bounds)),
            "minimum_elevation_m": minimum, "maximum_elevation_m": maximum,
            "valid_samples": valid_count}


@router.get("/api/terrain/jezero")
def jezero_metadata():
    common = {"resolution_m": RESOLUTION_M, "grid_size": GRID_SIZE,
              "minimum_level": MIN_LEVEL, "maximum_level": MAX_LEVEL,
              "tile_url": "/terrain/jezero/{z}/{y}/{x}.bin", "blend_margin_m": BLEND_MARGIN_M,
              "source_url": SOURCE_URL, "documentation_url": DOCUMENTATION_URL,
              "source_sha256": SOURCE_SHA256,
              "credit": "Jezero elevation: NASA/JPL/USGS, Fred Calef, CTX science-investigation DEM (2021)",
              "vertical_datum": "MOLA-controlled topographic elevations in metres",
              "blend_note": "Within 1 km of coverage edges or data gaps, display heights blend with the real 200 m MOLA/HRSC terrain. Source heights are unmodified in the interior."}
    if not LOCAL_DEM.exists():
        return {**common, "available": False, "message": "20 m Jezero terrain is not installed; using global terrain. Run python jezero_terrain.py --download to install it."}
    try:
        info = _source_info(str(LOCAL_DEM), _signature(LOCAL_DEM))
        return {**common, **info, "available": True}
    except (OSError, ValueError, rasterio.errors.RasterioError) as error:
        return {**common, "available": False, "message": f"Local Jezero elevation could not load ({type(error).__name__}); using global terrain."}


def tile_bounds(z, y, x):
    if not (MIN_LEVEL <= z <= MAX_LEVEL and 0 <= y < 2 ** z and 0 <= x < 2 ** (z + 1)):
        raise ValueError("Outside the supported Jezero geographic tile grid")
    width = 180 / 2 ** z
    west, north = -180 + x * width, 90 - y * width
    return west, north - width, west + width, north


def _sample_raster(path, bounds, *, nodata=np.nan):
    """Bilinear warp whose pixel centres are exactly the requested tile vertices."""
    west, south, east, north = bounds
    dx, dy = (east - west) / (GRID_SIZE - 1), (north - south) / (GRID_SIZE - 1)
    target = np.full((GRID_SIZE, GRID_SIZE), nodata, dtype="float32")
    # Half-pixel expansion is essential: adjacent tile edges sample the same locations.
    transform = Affine(dx, 0, west - dx / 2, 0, -dy, north + dy / 2)
    with rasterio.open(path) as ds:
        reproject(source=rasterio.band(ds, 1), destination=target, src_transform=ds.transform,
                  src_crs=ds.crs, src_nodata=ds.nodata, dst_transform=transform,
                  dst_crs=MARS_CRS, dst_nodata=nodata, resampling=Resampling.bilinear,
                  num_threads=1, warp_mem_limit=16, init_dest_nodata=True)
    return target


@lru_cache(maxsize=16)
def _global_tile(y, x):
    code, data, valid = lerc.decode(murray.elevation_tile_bytes(GLOBAL_LEVEL, y, x, timeout=10))[:3]
    if code:
        raise ValueError(f"The global elevation tile failed to decode ({code})")
    data = np.asarray(data, dtype="float32")
    if data.shape != (513, 513):
        raise ValueError("Unexpected global elevation tile dimensions")
    if valid is not None:
        data = np.where(np.asarray(valid) > 0, data, np.nan).astype("float32")
    return data


def _sample_global(z, y, x):
    # Every finer tile nests inside exactly one native level-7 tile. Include both
    # endpoint vertices; the source's last row/column overlaps its neighbours.
    factor = 2 ** (z - GLOBAL_LEVEL)
    parent_y, parent_x = y // factor, x // factor
    source = _global_tile(parent_y, parent_x)
    row0, col0 = (y % factor) * 512 / factor, (x % factor) * 512 / factor
    rows = np.linspace(row0, row0 + 512 / factor, GRID_SIZE)
    cols = np.linspace(col0, col0 + 512 / factor, GRID_SIZE)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    return map_coordinates(source, [rr, cc], order=1, mode="nearest", prefilter=False).astype("float32")


def _blend(local, global_heights, feather):
    weight = np.clip(feather / 255, 0, 1)
    weight[~np.isfinite(local)] = 0
    # Avoid NaN * 0 leaking missing local samples into real global fallback data.
    safe_local = np.where(np.isfinite(local), local, global_heights)
    heights = np.where(weight >= 1, safe_local, global_heights + weight * (safe_local - global_heights))
    if not np.isfinite(heights).all():
        raise ValueError("Required real terrain samples are unavailable")
    return heights.astype("<f4")


@lru_cache(maxsize=64)
def _tile_bytes(z, y, x, path_string, signature):
    path = Path(path_string)
    bounds = tile_bounds(z, y, x)
    local = _sample_raster(path, bounds)
    feather = _sample_raster(_prepare_feather(path, signature), bounds, nodata=0)
    if np.isfinite(local).all() and (feather >= 255).all():
        return local.astype("<f4").tobytes(order="C")
    return _blend(local, _sample_global(z, y, x), feather).tobytes(order="C")


@router.get("/terrain/jezero/{z}/{y}/{x}.bin")
def jezero_tile(z: int, y: int, x: int):
    try:
        bounds = tile_bounds(z, y, x)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    meta = jezero_metadata()
    if not meta["available"]:
        raise HTTPException(503, meta["message"])
    r = meta["rectangle"]
    if bounds[2] <= r["west"] or bounds[0] >= r["east"] or bounds[3] <= r["south"] or bounds[1] >= r["north"]:
        raise HTTPException(404, "Outside Jezero's measured elevation coverage")
    try:
        body = _tile_bytes(z, y, x, str(LOCAL_DEM), _signature(LOCAL_DEM))
    except (OSError, ValueError, rasterio.errors.RasterioError) as error:
        raise HTTPException(503, "Real elevation samples could not load; retry the terrain service") from error
    return Response(body, media_type="application/octet-stream",
                    headers={"Cache-Control": "public, max-age=604800", "X-Terrain-Grid-Size": str(GRID_SIZE),
                             "X-Terrain-Source": "USGS-CTX-20m-with-MOLA-HRSC-boundary-blend"})


def download_source():
    LOCAL_DEM.parent.mkdir(parents=True, exist_ok=True)
    if not LOCAL_DEM.exists():
        temporary = LOCAL_DEM.with_suffix(".part")
        digest = hashlib.sha256()
        request = urllib.request.Request(SOURCE_URL, headers=murray.UA)
        with urllib.request.urlopen(request, timeout=120, context=murray._ssl_ctx()) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != SOURCE_SHA256:
            raise ValueError("USGS download checksum changed; inspect the source before installing it")
        with rasterio.open(temporary) as ds:
            if ds.shape != (5067, 4456) or ds.res != (20, 20) or ds.dtypes != ("float32",):
                raise ValueError("USGS elevation raster layout does not match the verified product")
        temporary.replace(LOCAL_DEM)
    meta = jezero_metadata()
    if not meta["available"]:
        raise ValueError(meta["message"])
    return meta


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Install the verified USGS Jezero elevation raster")
    options = parser.parse_args()
    print(json.dumps(download_source() if options.download else jezero_metadata(), indent=2))
