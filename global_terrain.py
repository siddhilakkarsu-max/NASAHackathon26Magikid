"""On-demand measured Mars elevation from bundled authoritative footprints.

The catalogue is metadata only. Remote CTX COGs and HRSC rasters are read through
bounded HTTP ranges; no complete multi-gigabyte elevation archive is downloaded.
"""
from collections import Counter, OrderedDict
from concurrent.futures import Future
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import urlparse

import certifi
import numpy as np
import rasterio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from rasterio.windows import Window
from scipy.ndimage import distance_transform_edt, map_coordinates

import jezero_terrain as jezero

ROOT = Path(__file__).resolve().parent
CTX_CATALOG = ROOT / "terrain_catalog" / "ctx_dtms.json.gz"
HRSC_CATALOG = ROOT / "docs" / "planner" / "hrsc50m_sources.json"
CTX_DOCUMENTATION = "https://stac.astrogeology.usgs.gov/docs/data/mars/ctxdtms/"
HRSC_DOCUMENTATION = "https://hrscteam.dlr.de/public/data/regionaldtms.php"
GRID_SIZE, MIN_LEVEL, MAX_LEVEL = 257, 8, 11
BLEND_MARGIN_M = 1000
MAX_WINDOW_PIXELS = 8_000_000
SOURCE_TIMEOUT_S = 8
TILE_BUDGET_S = 25
QUEUE_TIMEOUT_S = 20
SUCCESS_TTL_S, FALLBACK_TTL_S = 3600, 30
TILE_CACHE_LIMIT = 128
_tile_cache = OrderedDict()
_pending_tiles = {}
_cache_lock = threading.Lock()
_read_slots = threading.BoundedSemaphore(4)
_compose_slots = threading.BoundedSemaphore(4)
router = APIRouter()


def normalize_rectangles(bbox):
    if len(bbox) != 4 or not all(math.isfinite(float(value)) for value in bbox):
        raise ValueError("Invalid geographic footprint")
    west, south, east, north = map(float, bbox)
    if not -90 <= south < north <= 90:
        raise ValueError("Invalid footprint latitudes")
    width = (east - west) % 360
    if not 0 < width < 180:
        raise ValueError("Ambiguous or degenerate regional footprint")
    west = (west + 180) % 360 - 180
    east = west + width
    if east <= 180:
        return [dict(west=west, south=south, east=east, north=north)]
    return [dict(west=west, south=south, east=180, north=north),
            dict(west=-180, south=south, east=east - 360, north=north)]


def _priority(source):
    return ({"jezero": 0, "ctx": 1, "hrsc": 2}[source["kind"]], source["resolution_m"], source["id"])


def _trusted_url(url, kind):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    if kind == "ctx":
        return (parsed.hostname in ("astrogeo-ard.s3-us-west-2.amazonaws.com", "astrogeo-ard.s3.amazonaws.com")
                and parsed.path.startswith("/mars/mro/ctx/controlled/usgs/") and parsed.path.lower().endswith(".tif"))
    return (kind == "hrsc" and parsed.hostname == "hrscteam.dlr.de"
            and parsed.path.startswith("/public/data/HMC30/") and parsed.path.lower().endswith("_da5.tif"))


@lru_cache(maxsize=1)
def _load_sources():
    sources = []
    if CTX_CATALOG.exists():
        catalog = json.loads(gzip.decompress(CTX_CATALOG.read_bytes()))
        for item in catalog["items"]:
            spacing = float(item["resolution_m"])
            if not 0 < spacing <= 100 or not _trusted_url(item["url"], "ctx"):
                raise ValueError("Invalid CTX catalogue source")
            rectangles = normalize_rectangles(item["bbox"])
            sources.append({"id": "ctx:" + item["id"], "kind": "ctx", "title": "USGS CTX stereo DTM",
                            "url": item["url"], "rectangles": rectangles, "resolution_m": spacing,
                            "maximum_level": 11, "source_url": CTX_DOCUMENTATION})
    if HRSC_CATALOG.exists():
        for item in json.loads(HRSC_CATALOG.read_text())["sources"]:
            if not _trusted_url(item["url"], "hrsc"):
                raise ValueError("Invalid HRSC catalogue source")
            r = item["rectangle"]
            sources.append({"id": "hrsc:" + item["id"], "kind": "hrsc", "title": "HRSC " + item["quadrangle"],
                            "url": item["url"], "rectangles": normalize_rectangles([r[k] for k in ("west", "south", "east", "north")]),
                            "resolution_m": float(item["resolution_m"]), "maximum_level": 10,
                            "source_url": item["source_page"], "native_geographic_wkt": item.get("native_geographic_wkt")})
    local = jezero.jezero_metadata()
    if local["available"]:
        sources.append({"id": "jezero", "kind": "jezero", "title": "Jezero crater survey",
                        "url": str(jezero.LOCAL_DEM), "rectangles": [local["rectangle"]],
                        "resolution_m": 20, "maximum_level": 11, "source_url": local["documentation_url"]})
    if len({source["id"] for source in sources}) != len(sources):
        raise ValueError("Duplicate elevation source IDs")
    return sorted(sources, key=_priority)


def _overlaps(bounds, rectangle):
    w, s, e, n = bounds
    # Include touching edges so neighbours apply the same source ordering there.
    epsilon = 1e-10
    return (w <= rectangle["east"] + epsilon and e >= rectangle["west"] - epsilon
            and s <= rectangle["north"] + epsilon and n >= rectangle["south"] - epsilon)


@lru_cache(maxsize=1)
def _source_index():
    index = {}
    width = 180 / 2 ** 7
    sources = _load_sources()
    for number, source in enumerate(sources):
        for r in source["rectangles"]:
            x0, x1 = max(0, math.floor((r["west"] + 180) / width)), min(255, math.floor((r["east"] + 180) / width))
            y0, y1 = max(0, math.floor((90 - r["north"]) / width)), min(127, math.floor((90 - r["south"]) / width))
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    index.setdefault((y, x), set()).add(number)
    return index


def _candidates(bounds):
    width = 180 / 2 ** 7
    west, south, east, north = bounds
    indexes = set()
    for y in range(max(0, math.floor((90 - north) / width) - 1), min(127, math.floor((90 - south) / width)) + 1):
        for x in range(max(0, math.floor((west + 180) / width) - 1), min(255, math.floor((east + 180) / width)) + 1):
            indexes.update(_source_index().get((y, x), ()))
    sources = _load_sources()
    return [sources[i] for i in sorted(indexes) if any(_overlaps(bounds, r) for r in sources[i]["rectangles"])]


def detail_metadata():
    sources = _load_sources()
    regions = []
    for source in sources:
        for rectangle in source["rectangles"]:
            regions.append({key: source[key] for key in ("id", "title", "kind", "resolution_m", "maximum_level", "source_url")}
                           | {"rectangle": rectangle})
    counts = dict(Counter(source["kind"] for source in sources))
    return {"available": bool(regions), "minimum_level": MIN_LEVEL, "maximum_level": MAX_LEVEL,
            "grid_size": GRID_SIZE, "tile_url": "/terrain/detail/{z}/{y}/{x}.bin", "regions": regions,
            "source_count": len(sources), "source_counts": counts, "blend_margin_m": BLEND_MARGIN_M,
            "credit": "Elevation: NASA/USGS CTX stereo DTMs; ESA/DLR/FU Berlin HRSC; NASA/USGS Jezero survey",
            "notes": ["Footprints indicate catalogued data, not guaranteed complete valid pixels.",
                      "20–36 m CTX and 50 m HRSC grid spacing is not equivalent to effective feature resolution or vertical accuracy.",
                      "Source gaps and unavailable tiles use real global MOLA/HRSC heights. Display blending occurs within 1 km of source edges and gaps.",
                      "Automated CTX DTMs may contain jitter, registration errors and artefacts. This is a visual terrain layer, not a certified navigation survey."],
            "examples": [{"id": source["id"], "title": source["title"], "rectangle": source["rectangles"][0]}
                         for source in sources if source["id"] in ("jezero", "hrsc:HMC_20E10_da5", "hrsc:HMC_11W10_da5")]}


@lru_cache(maxsize=1)
def _metadata_bytes():
    raw = json.dumps(detail_metadata(), separators=(",", ":")).encode()
    return raw, gzip.compress(raw, compresslevel=6, mtime=0)


@router.get("/api/terrain/detail")
def detail_metadata_response(request: Request):
    raw, compressed = _metadata_bytes()
    headers = {"Cache-Control": "public, max-age=3600", "Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        raw = compressed
    return Response(raw, media_type="application/json", headers=headers)


def _native_coordinates(ds, bounds):
    """Preserve native geographic angles; never rescale them to another radius."""
    if ds.crs is None or not ds.crs.is_projected:
        raise ValueError("Elevation source has no supported projected CRS")
    params = ds.crs.to_dict()
    if params.get("proj") != "eqc" or ds.crs.linear_units != "metre":
        raise ValueError("Unsupported projected elevation grid")
    radius = float(params.get("R") or params.get("a") or 0)
    if not 3_300_000 < radius < 3_500_000:
        raise ValueError("Elevation source is not a supported spherical Mars CRS")
    if abs(ds.transform.b) > 1e-8 or abs(ds.transform.d) > 1e-8:
        raise ValueError("Rotated terrain raster requires a separate projection adapter")
    west, south, east, north = bounds
    lon = np.linspace(west, east, GRID_SIZE)
    lat = np.linspace(north, south, GRID_SIZE)
    scale = radius * math.pi / 180
    longitude_origin = float(params.get("lon_0", 0))
    parallel = math.radians(float(params.get("lat_ts", 0)))
    # Shift a dateline tile into the raster's own continuous longitude domain.
    center_x = (ds.bounds.left + ds.bounds.right) / 2
    center_lon = (center_x - float(params.get("x_0", 0))) / (scale * math.cos(parallel)) + longitude_origin
    lon += 360 * round((center_lon - (west + east) / 2) / 360)
    xs = (lon - longitude_origin) * scale * math.cos(parallel) + float(params.get("x_0", 0))
    ys = (lat - float(params.get("lat_0", 0))) * scale + float(params.get("y_0", 0))
    cols = (xs - ds.transform.c) / ds.transform.a - 0.5
    rows = (ys - ds.transform.f) / ds.transform.e - 0.5
    return np.meshgrid(rows, cols, indexing="ij")


def _sample_dataset(ds, bounds):
    rr, cc = _native_coordinates(ds, bounds)
    output = np.full(rr.shape, np.nan, "float32")
    alpha = np.zeros(rr.shape, "float32")
    inside = (rr >= -0.5) & (cc >= -0.5) & (rr <= ds.height - 0.5) & (cc <= ds.width - 0.5)
    if not inside.any():
        return output, alpha
    halo_y = math.ceil(BLEND_MARGIN_M / abs(ds.res[1])) + 3
    halo_x = math.ceil(BLEND_MARGIN_M / abs(ds.res[0])) + 3
    y0 = max(0, math.floor(float(rr[inside].min())) - halo_y)
    y1 = min(ds.height, math.ceil(float(rr[inside].max())) + halo_y + 2)
    x0 = max(0, math.floor(float(cc[inside].min())) - halo_x)
    x1 = min(ds.width, math.ceil(float(cc[inside].max())) + halo_x + 2)
    if (y1 - y0) * (x1 - x0) > MAX_WINDOW_PIXELS:
        raise ValueError("Requested source window exceeds the bounded streaming budget")
    window = ds.read(1, window=Window(x0, y0, x1 - x0, y1 - y0), masked=True).astype("float32").filled(np.nan)
    window = window * float(ds.scales[0]) + float(ds.offsets[0])
    valid = np.isfinite(window) & (window > -20000) & (window < 40000)
    window[~valid] = np.nan
    distance = distance_transform_edt(np.pad(valid, 1, constant_values=False), sampling=(abs(ds.res[1]), abs(ds.res[0])))[1:-1, 1:-1]
    feather = np.clip((distance - max(ds.res)) / BLEND_MARGIN_M, 0, 1).astype("float32")
    coords = [rr - y0, cc - x0]
    output = map_coordinates(window, coords, order=1, mode="constant", cval=np.nan, prefilter=False).astype("float32")
    alpha = map_coordinates(feather, coords, order=1, mode="constant", cval=0, prefilter=False).astype("float32")
    alpha[~np.isfinite(output)] = 0
    return output, alpha


def _sample_source(source, bounds):
    if source["kind"] == "jezero":
        local = jezero._sample_raster(jezero.LOCAL_DEM, bounds)
        feather = jezero._sample_raster(jezero._prepare_feather(jezero.LOCAL_DEM, jezero._signature(jezero.LOCAL_DEM)), bounds, nodata=0) / 255
        feather[~np.isfinite(local)] = 0
        return local, feather
    if not _trusted_url(source["url"], source["kind"]):
        raise ValueError("Untrusted elevation asset")
    if not _read_slots.acquire(timeout=QUEUE_TIMEOUT_S):
        raise OSError("Elevation range-read queue is busy; retry this tile")
    try:
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT=SOURCE_TIMEOUT_S,
                                  GDAL_HTTP_CONNECTTIMEOUT=5, GDAL_HTTP_MAX_RETRY=0,
                                  GDAL_HTTP_CA_BUNDLE=certifi.where(), CURL_CA_BUNDLE=certifi.where(),
                                  CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF", GDAL_HTTP_MULTIRANGE="YES",
                                  GDAL_CACHEMAX=32 * 1024 * 1024, CPL_VSIL_CURL_CACHE_SIZE=64 * 1024 * 1024):
            with rasterio.open("/vsicurl/" + source["url"]) as ds:
                if ds.count != 1 or ds.dtypes[0] not in ("int16", "float32", "float64"):
                    raise ValueError("Source asset is not a supported elevation band")
                return _sample_dataset(ds, bounds)
    finally:
        _read_slots.release()


def _global_heights(z, y, x):
    return jezero._sample_global(z, y, x)


def _compose_tile(z, y, x):
    deadline = time.monotonic() + TILE_BUDGET_S
    bounds = jezero.tile_bounds(z, y, x)
    candidates = _candidates(bounds)
    global_heights = _global_heights(z, y, x)
    if not np.isfinite(global_heights).all():
        raise ValueError("Real global fallback heights are unavailable")
    result = global_heights.astype("float32").copy()
    remaining = np.ones(result.shape, "float32")
    used, failed = [], []
    for source in candidates:
        if float(remaining.max()) <= 1e-6:
            break
        if time.monotonic() >= deadline:
            failed.append(source["id"])
            continue
        try:
            local, alpha = _sample_source(source, bounds)
            alpha = np.clip(alpha, 0, 1)
            alpha[~np.isfinite(local)] = 0
            weight = remaining * alpha
            if np.any(weight > 0):
                result += weight * (np.where(np.isfinite(local), local, global_heights) - global_heights)
                remaining *= 1 - alpha
                used.append(source["id"])
        except (OSError, ValueError, rasterio.errors.RasterioError):
            failed.append(source["id"])
    if not np.isfinite(result).all():
        raise ValueError("Composed real terrain samples are not finite")
    return {"heights": result.astype("<f4"), "used": used, "failed": failed,
            "status": "partial" if used and failed else "detail" if used else "global-fallback"}


def _cached_tile(z, y, x):
    key = (z, y, x)
    now = time.monotonic()
    with _cache_lock:
        entry = _tile_cache.get(key)
        if entry and entry[0] > now:
            _tile_cache.move_to_end(key)
            return entry[1]
        _tile_cache.pop(key, None)
        pending = _pending_tiles.get(key)
        owner = pending is None
        if owner:
            pending = _pending_tiles[key] = Future()
    if not owner:
        return pending.result(timeout=QUEUE_TIMEOUT_S + TILE_BUDGET_S + 2 * SOURCE_TIMEOUT_S)
    try:
        # Admit whole compositions, so a normal burst of visible tiles waits its
        # turn instead of caching coarse fallback because all I/O slots are busy.
        if not _compose_slots.acquire(timeout=QUEUE_TIMEOUT_S):
            raise OSError("Terrain request queue is busy; retry this tile")
        try:
            result = _compose_tile(z, y, x)
        finally:
            _compose_slots.release()
        ttl = FALLBACK_TTL_S if result["failed"] or result["status"] == "global-fallback" else SUCCESS_TTL_S
        with _cache_lock:
            _tile_cache[key] = (time.monotonic() + ttl, result)
            while len(_tile_cache) > TILE_CACHE_LIMIT:
                _tile_cache.popitem(last=False)
        pending.set_result(result)
        return result
    except BaseException as error:
        pending.set_exception(error)
        raise
    finally:
        with _cache_lock:
            _pending_tiles.pop(key, None)


@router.get("/terrain/detail/{z}/{y}/{x}.bin")
def detail_tile(z: int, y: int, x: int):
    try:
        jezero.tile_bounds(z, y, x)
    except ValueError as error:
        raise HTTPException(404, "Outside the native detailed terrain grid") from error
    try:
        result = _cached_tile(z, y, x)
    except (OSError, ValueError, rasterio.errors.RasterioError) as error:
        raise HTTPException(503, "Real terrain heights could not load") from error
    transient = result["failed"] or result["status"] == "global-fallback"
    return Response(result["heights"].tobytes(order="C"), media_type="application/octet-stream", headers={
        "Cache-Control": f"public, max-age={FALLBACK_TTL_S if transient else SUCCESS_TTL_S}",
        "X-Terrain-Grid-Size": str(GRID_SIZE), "X-Terrain-Detail-Status": result["status"],
        "X-Terrain-Source-Count": str(len(result["used"])), "X-Terrain-Failed-Count": str(len(result["failed"])),
        "X-Terrain-Source-Ids": ",".join(result["used"])[:1500],
    })
