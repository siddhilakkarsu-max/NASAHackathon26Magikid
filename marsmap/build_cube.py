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


def _ssl_ctx():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


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
                arr = read_raster_into_grid(str(Path(__file__).parent / spec["path"]), grid,
                                            spec.get("nodata"), spec.get("resampling", "bilinear"))
            elif spec["kind"] == "cog":
                arr = read_raster_into_grid(spec["url"], grid, spec.get("nodata"), spec.get("resampling", "bilinear"))
            elif spec["kind"] == "wms":
                arr = fetch_wms(spec, grid)
            elif spec["kind"] == "table":
                arr = read_table_into_grid(spec, grid)
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
    # Atmospheric shielding vs Gale crater (where Curiosity's RAD measured ~0.64 mSv/day).
    # Air column (pressure) scales as exp(-elevation / 11.1 km scale height); more air = more shielding.
    GALE_ELEV_M, SCALE_HEIGHT_M = -4500.0, 11100.0
    cube["air_column_vs_gale"] = np.exp(-(cube["elevation"] - GALE_ELEV_M) / SCALE_HEIGHT_M).astype("float32")
    if "minerals" in cube:
        # Science value: any CRISM mineral detection (clays, carbonates, ...) inside the mapped area
        cube["science"] = np.where(np.isfinite(cube["minerals"]) & (cube["minerals"] > 0), 1.0, 0.0).astype("float32")
    if "thermal_inertia" in cube:
        # Calibrated thermal inertia (team reference table): <150 dust, 150-300 sand,
        # 300-600 coarse/crusted, >600 bedrock.  Map 100 -> 0 (loose) ... 600 -> 1 (firm),
        # then add THEMIS night-time detail for local variation (TI table is only 0.5 deg).
        ti_firm = np.clip((cube["thermal_inertia"] - 100) / 500, 0, 1)
        local = (normalize01(cube["themis_night"]) - 0.5) * 0.35 if "themis_night" in cube else 0
        cube["firmness"] = np.clip(ti_firm + local, 0, 1).astype("float32")
    elif "themis_night" in cube:
        # 0 = coldest at night (loose sand/dust), 1 = warmest (bedrock)
        cube["firmness"] = normalize01(cube["themis_night"])
    save(region, grid, cube, provenance)


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
