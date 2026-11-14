"""
Build the Mars "data cube": one grid where every pixel holds a vector of values
(elevation, slope, aspect, roughness, thermal proxies, ... + a coverage mask per band).

Same idea as co-registering MRI sequences and building a parametric map:
every source is resampled onto ONE lat/lon grid, then derived bands are computed per pixel.

Usage:
    python build_cube.py jezero          # small high-res box (do this first)
    python build_cube.py jezero --px-per-deg 512   # same box, coarser grid (smaller file, faster app)
    python build_cube.py global          # whole planet, low res
Output:
    cubes/<region>.npz   (used by the back end)
    cubes/<region>.tif   (multi-band GeoTIFF: open in QGIS to check)
"""
import hashlib
import io
import json
import math
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds as window_from_bounds

from config import MARS_LONLAT_CRS, MARS_RADIUS_M, MINERALS, REGION_SOURCES, REGIONS, SOURCES

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "cubes"
CACHE = ROOT / "data" / "cache"         # downloaded pieces, so rebuilding doesn't download again
UA = {"User-Agent": "Mozilla/5.0 (compatible; mars-cube-builder)"}
WMS_MAX_PX = 2048  # request big areas in blocks so the server doesn't refuse


# ----------------------------------------------------------------- grid ----
def make_grid(region, px_per_deg=None):
    r = dict(REGIONS[region])
    if px_per_deg:
        r["px_per_deg"] = px_per_deg
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
            elif spec["kind"] == "download":
                arr = read_raster_into_grid(str(download(spec["url"], spec["path"])), grid)
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


def _get(url, timeout=120):
    import urllib.request
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
        return resp.read()


def download(url, rel_path):
    """Fetch a file into data/ once; later builds reuse it."""
    path = ROOT / rel_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(_get(url, timeout=600))
        tmp.rename(path)
    return path


# ---------------------------------------------------------------- CRISM ----
ODE = "https://oderest.rsl.wustl.edu/live2/"


def crism_labels(bounds):
    """PDS3 labels of every CRISM summary-parameter product over the region, best first:
    targeted full resolution (FRT, ~18 m), other targeted (HRL/HRS, ~36 m), multispectral tiles (MRDR, ~180 m)."""
    w, s, e, n = bounds
    if (e - w) * (n - s) > 25:
        raise RuntimeError("region is too large for CRISM (thousands of products); use a smaller region")
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"crism_labels_{w}_{s}_{e}_{n}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    urls = []
    for pt in ("MTRDR", "MRDR4"):
        q = (f"{ODE}?query=product&results=fp&output=JSON&target=mars&ihid=MRO&iid=CRISM&pt={pt}"
             f"&westlon={w % 360}&eastlon={e % 360 or 360}&minlat={s}&maxlat={n}&limit=1000")
        res = json.loads(_get(q))["ODEResults"]
        prods = (res.get("Products") or {}).get("Product") or []
        for prod in [prods] if isinstance(prods, dict) else prods:
            files = prod["Product_files"]["Product_file"]
            for f in [files] if isinstance(files, dict) else files:
                if re.search(r"(_su\d|mrrsu)[^/]*\.lbl$", f["URL"].lower()):
                    urls.append(f["URL"])
    urls = sorted(set(urls), key=lambda u: (0 if "/frt" in u else 1 if "/mtrdr/" in u else 2, u))
    cache.write_text(json.dumps(urls))
    return urls


def crism_read(label_url, params, grid):
    """Read some summary parameters of one CRISM product onto the grid (NaN outside its footprint).
    Only the needed bytes are fetched (HTTP range requests); the result is cached in data/cache."""
    key = hashlib.sha1(f"{label_url}|{params}|{grid['bounds']}|{grid['width']}x{grid['height']}".encode())
    cache = CACHE / f"crism_{key.hexdigest()[:16]}.npz"
    if cache.exists():
        return cache
    label = _get(label_url).decode("latin-1")
    names = re.findall(r'"([^"]+)"', re.search(r"BAND_NAME\s*=\s*\((.*?)\)", label, re.S).group(1))
    idx = [names.index(p) + 1 for p in params]
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open("/vsicurl/" + label_url) as src:
            with WarpedVRT(src, crs=MARS_LONLAT_CRS, transform=grid["transform"], width=grid["width"],
                           height=grid["height"], src_nodata=65535, nodata=np.nan,
                           resampling=Resampling.average) as vrt:
                data = vrt.read(idx).astype("float32")
    data[~np.isfinite(data) | (np.abs(data) > 10)] = np.nan
    tmp = cache.with_name(cache.stem + ".part.npz")         # write then rename: no half-written cache
    np.savez_compressed(tmp, **{p: data[i] for i, p in enumerate(params)})
    tmp.rename(cache)
    return cache


def _km_corr(a, b, k):
    """Correlation of two maps after averaging over k x k pixels (ignores NaNs)."""
    from scipy.ndimage import uniform_filter

    def smooth(x):
        ok = np.isfinite(x)
        num, den = uniform_filter(np.where(ok, x, 0.0), k), uniform_filter(ok.astype(float), k)
        return np.where(den > 0.8, num / np.maximum(den, 1e-9), np.nan)
    sa, sb = smooth(a), smooth(b)
    ok = np.isfinite(sa) & np.isfinite(sb)
    return float(np.corrcoef(sa[ok], sb[ok])[0, 1]) if ok.sum() > 100 else 0.0


def build_minerals(grid):
    """One band per MINERALS entry: CRISM products mosaicked best-first, then the strongest of each
    mineral's parameters. Returns ({band: array}, [products used])."""
    params = sorted({p for m in MINERALS.values() for p in m["params"]})
    labels = crism_labels(grid["bounds"])
    print(f"  CRISM: {len(labels)} products over the region, reading {len(params)} parameters from each")
    done = {}
    with ThreadPoolExecutor(6) as pool:
        jobs = {pool.submit(crism_read, u, params, grid): u for u in labels}
        for job in as_completed(jobs):
            name = jobs[job].rsplit("/", 1)[-1]
            try:
                done[jobs[job]] = job.result()
                print(f"    [ok] {name}")
            except Exception as ex:
                print(f"    [--] {name}: {ex}")
    mosaic = {p: np.full((grid["height"], grid["width"]), np.nan, "float32") for p in params}
    used = []
    targeted = [u for u in labels if "/mtrdr/" in u and u in done]
    tiles = [u for u in labels if "/mtrdr/" not in u and u in done]
    for u in targeted:                                 # best first: only fill pixels that are still empty
        z = np.load(done[u])
        for p in params:
            hole = np.isnan(mosaic[p])
            mosaic[p][hole] = z[p][hole]
        used.append(u.rsplit("/", 1)[-1].split(".")[0])
    from_targeted = np.isfinite(np.stack([mosaic[p] for p in params])).any(axis=0)
    # The multispectral map tile is noisier and offset from the targeted data (e.g. OLINDEX3 ~+0.1 at Jezero).
    # It fills gaps only for parameters where it agrees with the targeted data at ~1 km, offset removed.
    dx, dy = pixel_size_m(grid)
    k = max(3, int(round(1000 / math.sqrt(float(np.mean(dx)) * dy))) | 1)
    for u in tiles:
        z = np.load(done[u])
        for p in params:
            t, a = mosaic[p], z[p].copy()
            overlap = np.isfinite(t) & np.isfinite(a)
            if overlap.sum() >= 2000:
                r = _km_corr(a, t, k)
                if r < 0.5:
                    print(f"    tile not used for {p}: agrees poorly with the targeted data (r={r:.2f} at ~1 km)")
                    continue
                a -= np.median(a[overlap] - t[overlap])
            hole = np.isnan(t) & np.isfinite(a)
            t[hole] = a[hole]
        used.append(u.rsplit("/", 1)[-1].split(".")[0])
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN pixels outside CRISM coverage
        for name, m in MINERALS.items():
            out[name] = np.nanmax(np.stack([mosaic[p] for p in m["params"]]), axis=0).astype("float32")
    # where each pixel's minerals come from: 1 = targeted observation (18-36 m), 2 = map tile (~180 m)
    any_data = np.isfinite(np.stack([mosaic[p] for p in params])).any(axis=0)
    out["crism_source"] = np.where(from_targeted, 1.0, np.where(any_data, 2.0, np.nan)).astype("float32")
    return out, used


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


def firmness_from_ti(ti, night, grid):
    """Ground firmness 0..1 from THEMIS thermal inertia on a log scale matching the classes
    <150 fine dust (0) | 150-300 sand (0-0.5) | 300-600 coarse/crusted (0.5-1) | >600 bedrock (1).
    The TI map is 1 km, so sub-km contrast is borrowed from the 100 m night-IR picture."""
    from scipy.ndimage import uniform_filter
    firm = (np.log(np.maximum(ti, 1)) - np.log(150)) / (np.log(600) - np.log(150))
    if night is not None:
        n = normalize01(night)
        dx, dy = pixel_size_m(grid)
        k = max(3, int(round(1000 / math.sqrt(float(np.mean(dx)) * dy))) | 1)
        filled = np.where(np.isnan(n), np.nanmean(n), n)
        firm = firm + (filled - uniform_filter(filled, k))      # local night-IR anomaly
        firm = np.where(np.isnan(firm), n, firm)                 # TI gaps: night IR alone
    return np.clip(firm, 0, 1).astype("float32")


def normalize01(a):
    lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1).astype("float32")


# ----------------------------------------------------------------- main ----
def build(region, bands=None, px_per_deg=None):
    grid = make_grid(region, px_per_deg)
    print(f"Region '{region}': {grid['width']} x {grid['height']} px, bounds {grid['bounds']}")
    cube, provenance = {}, {}
    srcs = sources_for(region)
    for name in (bands or srcs.keys()):
        if any(spec["kind"] == "crism" for spec in srcs[name]):
            try:
                t0 = time.time()
                minerals, used = build_minerals(grid)
                cube.update(minerals)
                provenance[name] = (f"CRISM summary parameters (Viviano-Beck et al. 2014) from {len(used)} "
                                    f"products via PDS Geosciences ODE: {', '.join(used)}")
                print(f"  [ok] {name:<13} {', '.join(minerals)} ({time.time() - t0:.1f}s)")
            except Exception as ex:
                print(f"  [--] {name:<13} skipped: {ex}")
            continue
        arr, spec = load_band(name, grid, srcs[name])
        if arr is not None:
            cube[name] = arr
            provenance[name] = spec
    if "elevation" not in cube:
        sys.exit("Elevation is required. Download a DEM GeoTIFF and set a 'file' source in config.py.")
    cube["slope"], cube["aspect"], cube["roughness"] = derive_terrain(cube["elevation"], grid)
    if "thermal_inertia" in cube:
        cube["firmness"] = firmness_from_ti(cube["thermal_inertia"], cube.get("themis_night"), grid)
    elif "themis_night" in cube:
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
    import argparse
    ap = argparse.ArgumentParser(description="Build the Mars data cube for one region.")
    ap.add_argument("region", nargs="?", default="jezero", choices=list(REGIONS))
    ap.add_argument("--px-per-deg", type=int, help="grid density (default: the region's value in config.py)")
    args = ap.parse_args()
    build(args.region, px_per_deg=args.px_per_deg)
