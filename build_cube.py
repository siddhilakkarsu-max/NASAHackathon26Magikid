"""
Build the Mars "data cube": one grid where every pixel holds a vector of values
(elevation, slope, aspect, roughness, thermal proxies, ... + a coverage mask per band).

Same idea as co-registering MRI sequences and building a parametric map:
every source is resampled onto ONE lat/lon grid, then derived bands are computed per pixel.

Usage:
    python build_cube.py jezero          # small high-res box (do this first)
    python build_cube.py global          # whole planet, low res
Output:
    cubes/<region>.npz   (used by the back end)
    cubes/<region>.tif   (multi-band GeoTIFF: open in QGIS to check)
"""
import io
import math
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds as window_from_bounds

from config import MARS_LONLAT_CRS, MARS_RADIUS_M, REGION_SOURCES, REGIONS, SOURCES

OUT_DIR = Path(__file__).parent / "cubes"
WMS_MAX_PX = 2048  # request big areas in blocks so the server doesn't refuse


# ----------------------------------------------------------------- grid ----
def make_grid(region):
    r = REGIONS[region]
    width = int(round((r["east"] - r["west"]) * r["px_per_deg"]))
    height = int(round((r["north"] - r["south"]) * r["px_per_deg"]))
    transform = from_bounds(r["west"], r["south"], r["east"], r["north"], width, height)
    return dict(bounds=(r["west"], r["south"], r["east"], r["north"]),
                width=width, height=height, transform=transform)


# -------------------------------------------------------------- readers ----
def read_raster_into_grid(path_or_url, grid):
    """Read a GeoTIFF (local file or remote URL) and resample onto our grid."""
    src_path = path_or_url if not path_or_url.startswith("http") else "/vsicurl/" + path_or_url
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        with rasterio.open(src_path) as src:
            with WarpedVRT(src, crs=MARS_LONLAT_CRS, resampling=Resampling.bilinear) as vrt:
                w, s, e, n = grid["bounds"]
                win = window_from_bounds(w, s, e, n, transform=vrt.transform)
                data = vrt.read(1, window=win, out_shape=(grid["height"], grid["width"]),
                                resampling=Resampling.bilinear, masked=True)
                arr = data.astype("float32").filled(np.nan)
                scale = (src.scales or [1.0])[0] or 1.0
                offset = (src.offsets or [0.0])[0] or 0.0
                return arr * scale + offset


def _ssl_ctx():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def wms_layer_names(server):
    """Ask the WMS server which layers it has (GetCapabilities)."""
    import re
    import urllib.request
    url = f"{server}&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MarswalkPlanner; NASA Space Apps)"})
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as resp:
        xml = resp.read().decode("utf-8", "ignore")
    return re.findall(r"<Name>([^<]+)</Name>", xml)


def resolve_wms_layer(spec):
    """Use spec['layer'] if the server has it, else the first layer whose name contains all spec['match'] words."""
    names = wms_layer_names(spec["server"])
    if spec["layer"] in names:
        return spec["layer"]
    words = [w.lower() for w in spec.get("match", [])]
    hits = [n for n in names if words and all(w in n.lower() for w in words)]
    if hits:
        print(f"      (layer '{spec['layer']}' not found; using '{hits[0]}')")
        return hits[0]
    raise RuntimeError(f"layer '{spec['layer']}' not on server. Available: {', '.join(names)}")


def fetch_wms(spec, grid):
    """Request a USGS WMS layer block by block for exactly our grid."""
    import urllib.request
    spec = dict(spec, layer=resolve_wms_layer(spec))
    w, s, e, n = grid["bounds"]
    H, W = grid["height"], grid["width"]
    out = np.full((H, W), np.nan, dtype="float32")
    dlon = (e - w) / W
    dlat = (n - s) / H
    for r0 in range(0, H, WMS_MAX_PX):
        for c0 in range(0, W, WMS_MAX_PX):
            h = min(WMS_MAX_PX, H - r0)
            wd = min(WMS_MAX_PX, W - c0)
            bw, be = w + c0 * dlon, w + (c0 + wd) * dlon
            bn, bs = n - r0 * dlat, n - (r0 + h) * dlat
            url = (f"{spec['server']}&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&SRS=EPSG:4326&STYLES="
                   f"&LAYERS={spec['layer']}&FORMAT={spec.get('format', 'image/png')}"
                   f"&BBOX={bw},{bs},{be},{bn}&WIDTH={wd}&HEIGHT={h}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MarswalkPlanner; NASA Space Apps)"})
            with urllib.request.urlopen(req, timeout=120, context=_ssl_ctx()) as resp:
                ctype = resp.headers.get("Content-Type", "")
                blob = resp.read()
            if "xml" in ctype or blob[:5] == b"<?xml":
                raise RuntimeError(f"WMS returned an error: {blob[:300]!r}")
            with MemoryFile(blob) as mf, mf.open() as ds:
                block = ds.read(1).astype("float32")
                if ds.nodata is not None:
                    block[block == ds.nodata] = np.nan
            out[r0:r0 + h, c0:c0 + wd] = block[:h, :wd]
    return out


def sources_for(region):
    """Region-specific sources first, then the global ones."""
    merged = {k: list(v) for k, v in SOURCES.items()}
    for name, specs in REGION_SOURCES.get(region, {}).items():
        merged[name] = list(specs) + merged.get(name, [])
    return merged


def load_band(name, grid, specs):
    errors = []
    for spec in specs:
        try:
            t0 = time.time()
            if spec["kind"] == "file":
                if not (Path(__file__).parent / spec["path"]).exists():
                    raise FileNotFoundError(f"{spec['path']} not downloaded")
                arr = read_raster_into_grid(str(Path(__file__).parent / spec["path"]), grid)
            elif spec["kind"] == "cog":
                arr = read_raster_into_grid(spec["url"], grid)
            elif spec["kind"] == "wms":
                arr = fetch_wms(spec, grid)
            else:
                raise ValueError(f"unknown kind {spec['kind']}")
            if np.all(np.isnan(arr)):
                raise RuntimeError("source returned no data for this region")
            print(f"  [ok] {name:<13} from {spec['kind']} ({time.time() - t0:.1f}s)")
            return arr, spec
        except Exception as ex:  # try the next source
            errors.append(f"{spec['kind']}: {ex}")
    print(f"  [--] {name:<13} skipped. Tried: " + " | ".join(errors))
    return None, None


# -------------------------------------------------------- derived bands ----
def pixel_size_m(grid):
    """Meters per pixel in x (varies with latitude) and y."""
    w, s, e, n = grid["bounds"]
    H, W = grid["height"], grid["width"]
    deg = math.pi / 180
    dy = (n - s) / H * deg * MARS_RADIUS_M
    lats = n - (np.arange(H) + 0.5) * (n - s) / H
    dx = (e - w) / W * deg * MARS_RADIUS_M * np.cos(lats * deg)
    return np.maximum(dx, 1.0)[:, None], dy


def derive_terrain(elev, grid):
    dx, dy = pixel_size_m(grid)
    z = np.where(np.isnan(elev), np.nanmean(elev), elev)
    dz_dy, dz_dx = np.gradient(z)          # rows go north->south
    gx = dz_dx / dx
    gy = -dz_dy / dy                       # north-positive
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = (np.degrees(np.arctan2(-gx, -gy)) + 360) % 360   # direction the slope faces, 0 = N
    # roughness: local std of elevation residual in a 3x3 window (m)
    from scipy.ndimage import uniform_filter
    mean = uniform_filter(z, 3)
    rough = np.sqrt(np.maximum(uniform_filter(z * z, 3) - mean * mean, 0))
    for a in (slope, aspect, rough):
        a[np.isnan(elev)] = np.nan
    return slope.astype("float32"), aspect.astype("float32"), rough.astype("float32")


def normalize01(a):
    lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1).astype("float32")


# ----------------------------------------------------------------- main ----
def build(region, bands=None):
    grid = make_grid(region)
    print(f"Region '{region}': {grid['width']} x {grid['height']} px, bounds {grid['bounds']}")
    cube, provenance = {}, {}
    srcs = sources_for(region)
    for name in (bands or srcs.keys()):
        arr, spec = load_band(name, grid, srcs[name])
        if arr is not None:
            cube[name] = arr
            provenance[name] = spec
    if "elevation" not in cube:
        sys.exit("Elevation is required. Download a DEM GeoTIFF and set a 'file' source in config.py.")
    cube["slope"], cube["aspect"], cube["roughness"] = derive_terrain(cube["elevation"], grid)
    if "themis_night" in cube:
        # 0 = coldest at night (loose sand/dust), 1 = warmest (bedrock)
        cube["firmness"] = normalize01(cube["themis_night"])
    save(region, grid, cube, provenance)


def save(region, grid, cube, provenance):
    OUT_DIR.mkdir(exist_ok=True)
    names = list(cube.keys())
    coverage = np.stack([~np.isnan(cube[n]) for n in names])
    np.savez_compressed(
        OUT_DIR / f"{region}.npz",
        bands=np.stack([cube[n] for n in names]).astype("float32"),
        band_names=np.array(names),
        coverage_fraction=coverage.mean(axis=0).astype("float32"),
        bounds=np.array(grid["bounds"]),
        provenance=np.array([f"{k}: {v}" for k, v in provenance.items()]),
    )
    profile = dict(driver="GTiff", width=grid["width"], height=grid["height"], count=len(names),
                   dtype="float32", crs=MARS_LONLAT_CRS, transform=grid["transform"],
                   nodata=np.nan, compress="deflate")
    with rasterio.open(OUT_DIR / f"{region}.tif", "w", **profile) as dst:
        for i, n in enumerate(names, 1):
            dst.write(cube[n], i)
            dst.set_band_description(i, n)
    print(f"Saved cubes/{region}.npz and cubes/{region}.tif with bands: {', '.join(names)}")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "jezero")
