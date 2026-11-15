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
import os
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

from config import (MARS_LONLAT_CRS, MARS_RADIUS_M, MINERALS, REGION_SOURCES, REGIONS, SOURCES, mc_quadrangle,
                    region_box, themis_ti)

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "cubes"
CACHE = ROOT / "data" / "cache"         # downloaded pieces, so rebuilding doesn't download again
UA = {"User-Agent": "Mozilla/5.0 (compatible; mars-cube-builder)"}
WMS_MAX_PX = 2048  # request big areas in blocks so the server doesn't refuse


# ----------------------------------------------------------------- grid ----
def make_grid(region, px_per_deg=None):
    r = region_box(region)
    if r is None:
        raise ValueError(f"unknown region '{region}': use one of {list(REGIONS)}, a named site or site_<lat>_<lon>")
    if px_per_deg:
        r["px_per_deg"] = px_per_deg
    width = int(round((r["east"] - r["west"]) * r["px_per_deg"]))
    height = int(round((r["north"] - r["south"]) * r["px_per_deg"]))
    transform = from_bounds(r["west"], r["south"], r["east"], r["north"], width, height)
    return dict(bounds=(r["west"], r["south"], r["east"], r["north"]),
                width=width, height=height, transform=transform)


# -------------------------------------------------------------- readers ----
def read_raster_into_grid(path_or_url, grid, nodata=None, resampling="bilinear"):
    """Read a GeoTIFF (local file or remote URL) and resample onto our grid.
    nodata: extra value to treat as missing (e.g. 0). resampling: 'nearest' for class maps."""
    rs = Resampling.nearest if resampling == "nearest" else Resampling.bilinear
    src_path = path_or_url if not path_or_url.startswith("http") else "/vsicurl/" + path_or_url
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        with rasterio.open(src_path) as src:
            vrt_kw = {"src_nodata": nodata} if nodata is not None and src.nodata is None else {}
            with WarpedVRT(src, crs=MARS_LONLAT_CRS, resampling=rs, **vrt_kw) as vrt:
                w, s, e, n = grid["bounds"]
                win = window_from_bounds(w, s, e, n, transform=vrt.transform)
                data = vrt.read(1, window=win, out_shape=(grid["height"], grid["width"]),
                                resampling=rs, masked=True)
                arr = data.astype("float32").filled(np.nan)
                scale = (src.scales or [1.0])[0] or 1.0
                offset = (src.offsets or [0.0])[0] or 0.0
                arr = arr * scale + offset
                if nodata is not None:
                    arr[arr == nodata] = np.nan
                return arr


def read_table_into_grid(spec, grid):
    """Point table (lon, lat, value per row; CSV or whitespace) -> our grid by interpolation.
    spec: {"kind": "table", "path": ..., "lon_col": 0, "lat_col": 1, "value_col": 2}"""
    from scipy.interpolate import griddata
    path = Path(__file__).parent / spec["path"]
    if not path.exists():
        raise FileNotFoundError(f"{spec['path']} not downloaded")
    with open(path) as fh:
        head = [fh.readline() for _ in range(50)]
    delim = "," if sum("," in h for h in head) > 25 else None

    def numeric(line):
        try:
            [float(v) for v in (line.split(delim) if delim else line.split()) if v.strip()]
            return bool(line.strip())
        except ValueError:
            return False
    skip = next((i for i, h in enumerate(head) if numeric(h)), 0)
    data = np.genfromtxt(path, delimiter=delim, skip_header=skip, invalid_raise=False, comments="#")
    lon, lat, val = data[:, spec.get("lon_col", 0)], data[:, spec.get("lat_col", 1)], data[:, spec["value_col"]]
    lon = np.where(lon > 180, lon - 360, lon)                      # 0..360 -> -180..180
    ok = np.isfinite(lon) & np.isfinite(lat) & np.isfinite(val)
    if "valid_min" in spec:
        ok &= val >= spec["valid_min"]
    w, s, e, n = grid["bounds"]
    m = 1.5                                                         # margin in degrees
    sel = ok & (lon >= w - m) & (lon <= e + m) & (lat >= s - m) & (lat <= n + m)
    if sel.sum() < 4:
        raise RuntimeError("table has no points in this region")
    H, W = grid["height"], grid["width"]
    gx = w + (np.arange(W) + 0.5) * (e - w) / W
    gy = n - (np.arange(H) + 0.5) * (n - s) / H
    GX, GY = np.meshgrid(gx, gy)
    pts = np.column_stack([lon[sel], lat[sel]])
    out = griddata(pts, val[sel], (GX, GY), method="linear")
    gap = np.isnan(out)
    if gap.any():
        out[gap] = griddata(pts, val[sel], (GX[gap], GY[gap]), method="nearest")
    return out.astype("float32")


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


FIRMNESS_UNKNOWN = 0.5      # placeholder firmness where no thermal data exists
TERRAIN_LEVEL = 7            # MDEM200M level 7: 0.00275 deg (~160 m) per sample, 512 x 512 per tile


def terrain_into_grid(grid, level=TERRAIN_LEVEL):
    """Elevation from the globe's own 3D terrain (Esri MDEM200M: MOLA + HRSC, 200 m), so routes are planned on
    the surface the user sees. Tiles are LERC, 513 x 513 samples on a 512-step lat/lon lattice from (-180, 90)."""
    import lerc
    from scipy.ndimage import map_coordinates
    import murray
    w, s, e, n = grid["bounds"]
    res = 0.3515625 / 2 ** level
    tdeg = res * 512
    per_row = int(round(360 / tdeg))
    c0, c1 = int(math.floor((w + 180) / tdeg)), int(math.floor((e + 180 - 1e-9) / tdeg))
    r0, r1 = int(math.floor((90 - n) / tdeg)), int(math.floor((90 - s - 1e-9) / tdeg))
    mosaic = np.full(((r1 - r0 + 1) * 512 + 1, (c1 - c0 + 1) * 512 + 1), np.nan, "float32")

    def tile(rc):
        r, c = rc
        code, data, valid = lerc.decode(murray.elevation_tile_bytes(level, r, c % per_row))[:3]
        if code != 0:
            raise RuntimeError(f"LERC tile {level}/{r}/{c} failed to decode ({code})")
        data = np.asarray(data, "float32")
        if valid is not None:
            data = np.where(np.asarray(valid) > 0, data, np.nan)
        return r, c, data

    with ThreadPoolExecutor(8) as pool:
        for r, c, data in pool.map(tile, [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]):
            y, x = (r - r0) * 512, (c - c0) * 512
            h, wd = min(513, data.shape[0]), min(513, data.shape[1])
            mosaic[y:y + h, x:x + wd] = data[:h, :wd]
    H, W = grid["height"], grid["width"]
    lat = n - (np.arange(H) + 0.5) * (n - s) / H
    lon = w + (np.arange(W) + 0.5) * (e - w) / W
    rows = (90 - r0 * tdeg - lat) / res
    cols = (lon + 180 - c0 * tdeg) / res
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    return map_coordinates(mosaic, [rr, cc], order=1, mode="nearest", cval=np.nan).astype("float32")


def sources_for(region):
    """Region-specific sources first, then the global ones."""
    merged = {k: list(v) for k, v in SOURCES.items()}
    for name, specs in REGION_SOURCES.get(region, {}).items():
        merged[name] = list(specs) + merged.get(name, [])
    if region not in REGION_SOURCES and region != "global":     # anywhere else: its quadrangle's THEMIS TI tile
        b = region_box(region)
        mc = mc_quadrangle((b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2)
        if 2 <= mc <= 29:                                       # the Zenodo record covers MC-02..29 (35S-45N)
            merged["thermal_inertia"] = [themis_ti(mc)] + merged["thermal_inertia"]
        merged["elevation"] = [{"kind": "terrain"}] + merged["elevation"]   # the globe's 3D terrain first
    return merged


def load_band(name, grid, specs):
    errors = []
    for spec in specs:
        try:
            t0 = time.time()
            if spec["kind"] == "file":
                if not (Path(__file__).parent / spec["path"]).exists():
                    raise FileNotFoundError(f"{spec['path']} not downloaded")
                arr = read_raster_into_grid(str(Path(__file__).parent / spec["path"]), grid,
                                            spec.get("nodata"), spec.get("resampling", "bilinear"))
            elif spec["kind"] == "cog":
                arr = read_raster_into_grid(spec["url"], grid, spec.get("nodata"), spec.get("resampling", "bilinear"))
            elif spec["kind"] == "download":
                arr = read_raster_into_grid(str(download(spec["url"], spec["path"])), grid,
                                            spec.get("nodata"), spec.get("resampling", "bilinear"))
            elif spec["kind"] == "table":
                arr = read_table_into_grid(spec, grid)
            elif spec["kind"] == "terrain":
                arr = terrain_into_grid(grid)
            elif spec["kind"] == "wms":
                arr = fetch_wms(spec, grid)
            else:
                raise ValueError(f"unknown kind {spec['kind']}")
            if np.all(np.isnan(arr)):
                raise RuntimeError("source returned no data for this region")
            if spec["kind"] == "wms" and float(np.nanstd(arr)) < 1e-3:     # e.g. THEMIS poleward of ~60 deg: blank
                raise RuntimeError("source returned a blank image for this region (outside its coverage)")
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
        res = json.loads(_get(q)).get("ODEResults")
        prods = res.get("Products") if isinstance(res, dict) else None     # "No Products Found" is a string
        prods = (prods.get("Product") if isinstance(prods, dict) else None) or []
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
    """Ground firmness 0..1 from thermal inertia on a log scale matching the classes
    <150 fine dust (0) | 150-300 sand (0-0.5) | 300-600 coarse/crusted (0.5-1) | >600 bedrock (1).
    Local contrast within ~1 km is borrowed from the 100 m night-IR picture; night IR alone fills TI gaps.
    (A linear TI scale rated Jezero's sand looser and broke the gear tests' calibrated oxygen scenario.)"""
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
    """Build cubes/<region>.npz. The cube is saved twice: first without CRISM minerals (usable for planning in a
    minute or two), then again once the mineral maps are in, which can take several minutes."""
    grid = make_grid(region, px_per_deg)
    print(f"Region '{region}': {grid['width']} x {grid['height']} px, bounds {grid['bounds']}")
    cube, provenance = {}, {}
    srcs = sources_for(region)
    wanted = list(bands or srcs.keys())
    crism = [n for n in wanted if any(spec["kind"] == "crism" for spec in srcs[n])]
    for name in wanted:
        if name in crism:
            continue
        arr, spec = load_band(name, grid, srcs[name])
        if arr is not None:
            cube[name] = arr
            provenance[name] = spec
    if "elevation" not in cube:
        sys.exit("Elevation is required. Download a DEM GeoTIFF and set a 'file' source in config.py.")
    _derive(cube, grid)
    if crism:
        save(region, grid, cube, provenance)
        print("STAGE terrain ready; reading CRISM minerals next", flush=True)
    for name in crism:
        try:
            t0 = time.time()
            minerals, used = build_minerals(grid)
            cube.update(minerals)
            provenance[name] = (f"CRISM summary parameters (Viviano-Beck et al. 2014) from {len(used)} "
                                f"products via PDS Geosciences ODE: {', '.join(used)}")
            print(f"  [ok] {name:<13} {', '.join(minerals)} ({time.time() - t0:.1f}s)")
        except Exception as ex:
            print(f"  [--] {name:<13} skipped: {ex}")
    _derive(cube, grid)
    save(region, grid, cube, provenance)


def _derive(cube, grid):
    """Bands computed from the downloaded ones (terrain, radiation shielding, science, firmness)."""
    cube["slope"], cube["aspect"], cube["roughness"] = derive_terrain(cube["elevation"], grid)
    # Atmospheric shielding vs Gale crater (where Curiosity's RAD measured ~0.64 mSv/day).
    # Air column (pressure) scales as exp(-elevation / 11.1 km scale height); more air = more shielding.
    GALE_ELEV_M, SCALE_HEIGHT_M = -4500.0, 11100.0
    cube["air_column_vs_gale"] = np.exp(-(cube["elevation"] - GALE_ELEV_M) / SCALE_HEIGHT_M).astype("float32")
    if "minerals" in cube:
        # Science value: any CRISM mineral detection (clays, carbonates, ...) inside the mapped area
        cube["science"] = np.where(np.isfinite(cube["minerals"]) & (cube["minerals"] > 0), 1.0, 0.0).astype("float32")
    if "thermal_inertia" in cube:
        cube["firmness"] = firmness_from_ti(cube["thermal_inertia"], cube.get("themis_night"), grid)
    elif "themis_night" in cube:
        # 0 = coldest at night (loose sand/dust), 1 = warmest (bedrock)
        cube["firmness"] = normalize01(cube["themis_night"])
    else:
        # No thermal data (THEMIS stops near +-60 deg latitude): firmness unknown. A neutral 0.5 keeps the planner
        # working; mission.py tells the user (FIRMNESS_UNKNOWN) and the pixel panel shows no thermal inertia.
        cube["firmness"] = np.full_like(cube["elevation"], FIRMNESS_UNKNOWN)


# Mars-like colour ramp: shadow -> rust -> dusty tan (matches the Viking colour globe)
MARS_RAMP = np.array([[0.00, 38, 22, 16], [0.35, 112, 62, 38], [0.65, 176, 112, 72],
                      [0.85, 214, 160, 116], [1.00, 238, 206, 170]], dtype="float32")


def mars_tint(gray):
    """Turn a 0-1 greyscale image into Mars-coloured R, G, B (0-255)."""
    x = MARS_RAMP[:, 0]
    return [np.interp(gray, x, MARS_RAMP[:, i]) for i in (1, 2, 3)]


VIKING_LAYER = "Mars_Viking_MDIM21_ClrMosaic_global_232m"


def viking_color_patch(bounds, level=7):
    """Stitch NASA Trek Viking colour tiles covering bounds; return (rgb float array, (w, s, e, n))."""
    import io
    import urllib.request
    from PIL import Image
    w, s, e, n = bounds
    tdeg = 180.0 / 2 ** level                          # tile size in degrees (2^(z+1) x 2^z tiles)
    c0, c1 = int((w + 180) // tdeg), int((e + 180) // tdeg)
    r0, r1 = int((90 - n) // tdeg), int((90 - s) // tdeg)
    rows = []
    for r in range(r0, r1 + 1):
        row = []
        for c in range(c0, c1 + 1):
            url = (f"https://trek.nasa.gov/tiles/Mars/EQ/{VIKING_LAYER}/1.0.0/default/default028mm/"
                   f"{level}/{r}/{c}.jpg")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MarswalkPlanner)"})
            with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as resp:
                row.append(np.asarray(Image.open(io.BytesIO(resp.read())).convert("RGB"), dtype="float32"))
        rows.append(np.hstack(row))
    mosaic = np.vstack(rows)
    ext = (c0 * tdeg - 180, 90 - (r1 + 1) * tdeg, (c1 + 1) * tdeg - 180, 90 - r0 * tdeg)
    return mosaic, ext


def pansharpen_with_viking(gray, bounds):
    """Colour from the Viking global mosaic, sharp detail from CTX (luminance swap)."""
    from PIL import Image
    from scipy.ndimage import gaussian_filter
    try:
        mosaic, (mw, ms, me, mn) = viking_color_patch(bounds)
    except Exception as ex:
        print(f"      (Viking colour unavailable, using Mars tint: {ex})")
        return None
    w, s, e, n = bounds
    H, W = mosaic.shape[:2]
    x0, x1 = (w - mw) / (me - mw) * W, (e - mw) / (me - mw) * W
    y0, y1 = (mn - n) / (mn - ms) * H, (mn - s) / (mn - ms) * H
    crop = Image.fromarray(mosaic.astype("uint8")).crop((int(x0), int(y0), int(np.ceil(x1)), int(np.ceil(y1))))
    color = np.asarray(crop.resize((gray.shape[1], gray.shape[0]), Image.BICUBIC), dtype="float32")
    lum = color.mean(axis=2)
    # Match CTX brightness to Viking's overall brightness, then swap in CTX detail
    blur_sigma = max(gray.shape) / 150
    ctx_low = gaussian_filter(gray, blur_sigma)
    detail = (gray + 0.05) / (ctx_low + 0.05)
    out = color * np.clip(detail, 0.2, 3.0)[..., None]
    print("      (coloured with NASA Viking colour mosaic)")
    return [np.clip(out[..., i], 0, 255) for i in range(3)]


def feather_alpha(valid, edge_frac=0.08):
    """Alpha channel that fades to transparent near the image border and near no-data gaps."""
    from scipy.ndimage import distance_transform_edt
    pad = np.pad(valid, 1, constant_values=False)
    dist = distance_transform_edt(pad)[1:-1, 1:-1]
    ramp = max(3.0, edge_frac * max(valid.shape))
    a = np.clip(dist / ramp, 0, 1)
    a = a * a * (3 - 2 * a)            # smoothstep
    return (a * 255)


def build_hires_imagery(region, max_px=8192):
    """Save the photo layer at (near) native resolution as a JPEG overlay + bounds JSON,
    so the map shows real 6 m detail instead of the coarser analysis grid."""
    import json
    from PIL import Image
    from rasterio.warp import transform_bounds
    w, s, e, n = make_grid(region)["bounds"]
    for spec in sources_for(region).get("imagery", []):
        try:
            src_path = spec.get("path") or spec.get("url")
            if spec["kind"] == "file":
                if not (Path(__file__).parent / src_path).exists():
                    continue
                src_path = str(Path(__file__).parent / src_path)
            open_path = "/vsicurl/" + src_path if src_path.startswith("http") else src_path
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"), rasterio.open(open_path) as src:
                bw, bs, be, bn = transform_bounds(src.crs, MARS_LONLAT_CRS, *src.bounds)
                res_m = abs(src.transform.a)
            iw, is_, ie, in_ = max(w, bw), max(s, bs), min(e, be), min(n, bn)
            if iw >= ie or is_ >= in_:
                continue
            deg_m = math.pi / 180 * MARS_RADIUS_M
            ppd = min(deg_m / res_m, max_px / max(ie - iw, in_ - is_))
            g = dict(bounds=(iw, is_, ie, in_), width=int((ie - iw) * ppd), height=int((in_ - is_) * ppd))
            t0 = time.time()
            arr = read_raster_into_grid(src_path, g)
            ok = np.isfinite(arr) & (arr > 0)
            lo, hi = np.percentile(arr[ok], [1, 99]) if ok.any() else (0, 255)
            gray = np.clip((np.nan_to_num(arr, nan=lo) - lo) / max(hi - lo, 1e-6), 0, 1)
            rgb = pansharpen_with_viking(gray, (iw, is_, ie, in_))
            if rgb is None:
                rgb = mars_tint(gray)
            rgba = np.dstack([*rgb, feather_alpha(ok)]).astype("uint8")
            OUT_DIR.mkdir(exist_ok=True)
            Image.fromarray(rgba).save(OUT_DIR / f"{region}_imagery.webp", quality=82, method=4)
            meta = {"west": iw, "south": is_, "east": ie, "north": in_, "meters_per_px": round(deg_m / ppd, 1),
                    "source": src_path.split("/")[-1]}
            (OUT_DIR / f"{region}_imagery.json").write_text(json.dumps(meta))
            print(f"  [ok] hi-res image  {g['width']}x{g['height']} px at ~{meta['meters_per_px']} m/px "
                  f"({time.time() - t0:.1f}s)")
            return
        except Exception as ex:
            print(f"  [--] hi-res image  {spec['kind']} failed: {ex}")


def save(region, grid, cube, provenance):
    OUT_DIR.mkdir(exist_ok=True)
    names = list(cube.keys())
    coverage = np.stack([~np.isnan(cube[n]) for n in names])
    tmp = OUT_DIR / f".{region}.part.npz"       # write then rename: the server never reads a half-written cube
    np.savez_compressed(
        tmp,
        bands=np.stack([cube[n] for n in names]).astype("float32"),
        band_names=np.array(names),
        coverage_fraction=coverage.mean(axis=0).astype("float32"),
        bounds=np.array(grid["bounds"]),
        provenance=np.array([f"{k}: {v}" for k, v in provenance.items()]),
    )
    os.replace(tmp, OUT_DIR / f"{region}.npz")
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
    ap.add_argument("region", nargs="?", default="jezero",
                    help=f"{', '.join(REGIONS)}, a named site from config.SITES, or site_<lat>_<lon>")
    ap.add_argument("--px-per-deg", type=int, help="grid density (default: the region's value in config.py)")
    ap.add_argument("--imagery", action="store_true",
                    help="only (re)make the hi-res photo overlay cubes/<region>_imagery.webp")
    args = ap.parse_args()
    if region_box(args.region) is None:
        ap.error(f"unknown region '{args.region}'")
    if args.imagery:
        build_hires_imagery(args.region)
    else:
        build(args.region, px_per_deg=args.px_per_deg)
