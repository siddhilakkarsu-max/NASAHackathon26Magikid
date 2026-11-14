"""
Back end: holds the Mars data cube(s) and does all the math.
The Cesium front end only displays what this returns.

Run:   uvicorn app:app --reload --port 8000
Open:  http://localhost:8000
"""
import base64
import io
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from matplotlib import colormaps
from PIL import Image
from pydantic import BaseModel, Field

import physics
from config import MARS_RADIUS_M, SCIENCE_TARGETS, VEHICLES

ROOT = Path(__file__).parent
app = FastAPI(title="Mars Marswalk Planner")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------- cube I/O ----
class Cube:
    def __init__(self, region):
        path = ROOT / "cubes" / f"{region}.npz"
        if not path.exists():
            raise HTTPException(404, f"No cube for '{region}'. Run: python build_cube.py {region}")
        z = np.load(path, allow_pickle=False)
        self.region = region
        self.names = [str(n) for n in z["band_names"]]
        self.bands = {n: z["bands"][i] for i, n in enumerate(self.names)}
        self.coverage = z["coverage_fraction"]
        self.w, self.s, self.e, self.n = [float(v) for v in z["bounds"]]
        self.H, self.W = self.bands["elevation"].shape
        self.provenance = [str(p) for p in z["provenance"]]
        mid = math.radians((self.s + self.n) / 2)
        self.pixel_m = ((self.n - self.s) / self.H * math.pi / 180 * MARS_RADIUS_M,
                        (self.e - self.w) / self.W * math.pi / 180 * MARS_RADIUS_M * math.cos(mid))

    def rc(self, lat, lon):
        r = int((self.n - lat) / (self.n - self.s) * self.H)
        c = int((lon - self.w) / (self.e - self.w) * self.W)
        if not (0 <= r < self.H and 0 <= c < self.W):
            raise HTTPException(400, f"({lat:.4f}, {lon:.4f}) is outside the {self.region} cube")
        return r, c

    def latlon(self, r, c):
        return (self.n - (r + 0.5) * (self.n - self.s) / self.H,
                self.w + (c + 0.5) * (self.e - self.w) / self.W)

    @property
    def rect(self):
        return {"west": self.w, "south": self.s, "east": self.e, "north": self.n}


@lru_cache(maxsize=4)
def get_cube(region):
    return Cube(region)


# -------------------------------------------------------------- helpers ----
def to_png(arr, cmap="viridis", vmin=None, vmax=None, alpha=0.65, max_px=1600):
    a = np.array(arr, dtype="float64")
    step = max(1, int(np.ceil(max(a.shape) / max_px)))   # keep overlays light for the browser
    a = a[::step, ::step]
    bad = ~np.isfinite(a)
    lo = np.nanpercentile(a[~bad], 2) if vmin is None else vmin
    hi = np.nanpercentile(a[~bad], 98) if vmax is None else vmax
    norm = np.clip((np.where(bad, lo, a) - lo) / max(hi - lo, 1e-9), 0, 1)
    rgba = (colormaps[cmap](norm) * 255).astype("uint8")
    rgba[..., 3] = np.where(bad, 0, int(alpha * 255))
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def legend(name, unit, lo, hi, cmap):
    return {"name": name, "unit": unit, "min": round(float(lo), 2), "max": round(float(hi), 2), "cmap": cmap}


class Point(BaseModel):
    lat: float
    lon: float


class Conditions(BaseModel):
    region: str = "jezero"
    vehicle: str = "astronaut"
    local_hour: float = Field(11.0, ge=0, le=24, description="Mars local solar time")
    ls: float = Field(90.0, ge=0, le=360, description="Season, solar longitude")
    budget_hours: float = Field(4.0, gt=0, description="EVA time budget (stands in for O2 budget)")
    reserve: float = Field(0.25, ge=0, lt=1, description="Fraction of budget held back for emergencies")
    min_sun_elev: float = 10.0
    weights: dict = {}


class PlanRequest(Conditions):
    base: Point
    target: Point


def conditions_layers(cube, cond):
    v = VEHICLES.get(cond.vehicle)
    if v is None:
        raise HTTPException(400, f"vehicle must be one of {list(VEHICLES)}")
    b = cube.bands
    lat_c = (cube.s + cube.n) / 2
    sun_e, sun_az = physics.sun_position(lat_c, cond.local_hour, cond.ls)
    illum = physics.illumination(b["slope"], b["aspect"], sun_e, sun_az)
    temp = physics.surface_temp_k(illum, b.get("firmness"), sun_e, b.get("albedo"))
    cost = physics.cost_seconds_per_meter(b, v, cond.weights)
    return v, sun_e, sun_az, illum, temp, cost


def suitability(c, v, cost):
    """Decision layer: where is it safe AND worthwhile to go? (0 = poor, 1 = best)
    safety   : gentle slope + firm ground          (weight 0.45)
    science  : CRISM mineral detections           (weight 0.35, only where mapped)
    shielding: more air above = less radiation    (weight 0.20)"""
    b = c.bands
    slope_ok = 1 - np.clip(b["slope"] / v["max_slope"], 0, 1)
    firm = b.get("firmness", np.full_like(b["slope"], 0.5))
    safety = 0.6 * slope_ok + 0.4 * np.nan_to_num(firm, nan=0.5)
    sci = b.get("science")
    sci = np.zeros_like(safety) if sci is None else np.nan_to_num(sci)
    shield = np.clip((b["air_column_vs_gale"] - 0.7) / 0.5, 0, 1) if "air_column_vs_gale" in b else 0.5
    score = 0.45 * safety + 0.35 * sci + 0.20 * shield
    return np.where(np.isfinite(cost), score, np.nan)


# ------------------------------------------------------------ endpoints ----
@app.get("/api/regions")
def regions():
    out = []
    for p in sorted((ROOT / "cubes").glob("*.npz")):
        c = get_cube(p.stem)
        out.append({"region": c.region, "rect": c.rect, "size": [c.W, c.H], "bands": c.names,
                    "pixel_m": [round(c.pixel_m[0]), round(c.pixel_m[1])], "provenance": c.provenance,
                    "targets": SCIENCE_TARGETS.get(c.region, [])})
    return {"regions": out, "vehicles": {k: v["label"] for k, v in VEHICLES.items()}}


@app.get("/api/imagery/{region}")
def hires_imagery(region: str):
    """High-resolution photo overlay for a region, if build_cube.py made one."""
    import json
    meta = ROOT / "cubes" / f"{region}_imagery.json"
    if not meta.exists():
        return {"available": False}
    return {"available": True, "url": f"/cubes/{region}_imagery.webp", **json.loads(meta.read_text())}


GLOBAL_DEM = "https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif"
_ds_cache = {}


def _open(path):
    import rasterio
    if path not in _ds_cache:
        p = "/vsicurl/" + path if path.startswith("http") else path
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            _ds_cache[path] = rasterio.open(p)
    return _ds_cache[path]


def _sample(path, lat, lon, half=3):
    """Read a small (2*half+1)^2 window around lat/lon from a Mars equirectangular GeoTIFF."""
    from rasterio.windows import Window
    from rasterio.warp import transform as warp_transform
    ds = _open(path)
    xs, ys = warp_transform("+proj=longlat +R=3396190 +no_defs", ds.crs, [lon], [lat])
    row, col = ds.index(xs[0], ys[0])
    win = Window(col - half, row - half, 2 * half + 1, 2 * half + 1)
    arr = ds.read(1, window=win, boundless=True, fill_value=np.nan).astype("float64")
    if ds.nodata is not None:
        arr[arr == ds.nodata] = np.nan
    res = abs(ds.transform.a)
    if ds.crs.is_geographic:                       # degrees -> metres
        res = res * np.pi / 180 * MARS_RADIUS_M
    return arr, res


def _wms_point(layer, lat, lon, d=0.01):
    """Average value of a USGS WMS layer in a tiny box around the point."""
    url = (f"https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl.map&SERVICE=WMS"
           f"&VERSION=1.1.1&REQUEST=GetMap&SRS=EPSG:4326&STYLES=&LAYERS={layer}&FORMAT=image/png"
           f"&BBOX={lon - d},{lat - d},{lon + d},{lat + d}&WIDTH=4&HEIGHT=4")
    img = np.asarray(Image.open(io.BytesIO(_get(url))).convert("L"), dtype="float64")
    return float(img.mean())


@app.get("/api/point")
def point_query(lat: float, lon: float):
    """Live lookup anywhere on Mars (no cube needed). Lower resolution than the Jezero cubes."""
    vals, notes = {}, []
    try:
        z, res = _sample(GLOBAL_DEM, lat, lon)
        if np.isfinite(z[3, 3]):
            vals["elevation"] = round(float(z[3, 3]), 1)
            dx = res * (np.cos(np.radians(lat)) if _open(GLOBAL_DEM).crs.is_geographic else 1.0)
            gy, gx = np.gradient(z, res, dx)
            vals["slope"] = round(float(np.degrees(np.arctan(np.hypot(gx[3, 3], gy[3, 3])))), 2)
            vals["roughness"] = round(float(np.nanstd(z[2:5, 2:5])), 2)
            air = float(np.exp(-(vals["elevation"] + 4500.0) / 11100.0))
            vals["air_column_vs_gale"] = round(air, 3)
            notes.append(f"air column {air * 100:.0f}% of Gale crater (Curiosity RAD there: ~0.64 mSv/day); "
                         + ("more shielding" if air > 1.03 else "less shielding" if air < 0.97 else "about the same"))
    except Exception as ex:
        notes.append(f"elevation unavailable ({type(ex).__name__})")
    tes = ROOT / "data" / "Mars_MGS_TES_Albedo_mosaic_global_7410m.tif"
    try:
        a, _ = _sample(str(tes) if tes.exists() else
                       "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif", lat, lon, 0)
        if np.isfinite(a[0, 0]) and 0 < a[0, 0] < 1:
            vals["albedo"] = round(float(a[0, 0]), 3)
            notes.append(f"albedo {vals['albedo']:.2f} - " + ("bright, likely dusty" if vals["albedo"] > 0.26
                                                                 else "dark, less dust"))
    except Exception:
        pass
    for band, layer in (("themis_night", "THEMIS_night"), ("themis_day", "THEMIS")):
        try:
            vals[band] = round(_wms_point(layer, lat, lon), 1)
        except Exception:
            pass
    ground = None
    if "themis_night" in vals:   # relative proxy: warm at night = rock, cold = loose
        n = vals["themis_night"]
        ground = ("probably loose dust/sand (cold at night)" if n < 90 else
                  "mixed ground" if n < 150 else "probably rocky / firm (warm at night)") + " - THEMIS estimate"
    return {"lat": lat, "lon": lon, "values": vals, "ground": ground, "notes": notes,
            "confidence": "live lookup (~200 m elevation, ~7 km albedo)", "source": "global"}


@app.get("/api/pixel")
def pixel(lat: float, lon: float, region: str = "jezero"):
    """Values stored in a cube pixel. Falls back to other regions, then a live global lookup."""
    candidates = [region] + [p.stem for p in sorted((ROOT / "cubes").glob("*.npz")) if p.stem != region]
    c = None
    for reg in candidates:
        try:
            cc = get_cube(reg)
        except HTTPException:
            continue
        if cc.s <= lat <= cc.n and cc.w <= lon <= cc.e:
            c = cc
            break
    if c is None:
        return point_query(lat, lon)
    r, col = c.rc(lat, lon)
    vals = {n: (None if not np.isfinite(c.bands[n][r, col]) else round(float(c.bands[n][r, col]), 3))
            for n in c.names}
    firm, ti = vals.get("firmness"), vals.get("thermal_inertia")
    if ti is not None:   # team reference table (J m-2 K-1 s-1/2)
        ground = (f"TI {ti:.0f}: " + ("fine dust - very loose" if ti < 150 else "sand - loose, slip risk" if ti < 300
                  else "coarse sand / crusted soil / mixed rocks" if ti < 600 else "bedrock / rock-rich - firm"))
    else:
        ground = None if firm is None else ("loose sand/dust - slip risk" if firm < 0.3
                                            else "mixed" if firm < 0.6 else "firm / bedrock")
    air = vals.get("air_column_vs_gale")
    notes = []
    if air is not None:
        notes.append(f"air column {air * 100:.0f}% of Gale crater (Curiosity RAD there: ~0.64 mSv/day); "
                     + ("more shielding" if air > 1.03 else "less shielding" if air < 0.97 else "about the same"))
    if vals.get("science"):
        notes.append(f"CRISM mineral detection (class {vals.get('minerals'):.0f}) - science target")
    alb = vals.get("albedo")
    if alb is not None:
        notes.append(f"albedo {alb:.2f} - " + ("bright, likely dusty" if alb > 0.26 else "dark, less dust"))
    return {"lat": lat, "lon": lon, "values": vals, "ground": ground, "notes": notes,
            "confidence": round(float(c.coverage[r, col]), 2), "source": c.region}


@app.post("/api/layer/{name}")
def layer(name: str, cond: Conditions):
    """Coloured overlay of one band or one computed layer, for the current conditions."""
    c = get_cube(cond.region)
    v, sun_e, sun_az, illum, temp, cost = conditions_layers(c, cond)
    if name in c.bands:
        arr, unit, cmap = c.bands[name], "", "viridis"
        if name == "slope":
            arr, unit, cmap = arr, "deg", "magma"
        if name == "firmness":
            cmap = "cividis"
        if name == "albedo":
            cmap = "gray"
        if name == "thermal_inertia":
            arr, unit, cmap = arr, "J m-2 K-1 s-1/2", "plasma"
        if name == "minerals":
            cmap, unit = "tab20", "CRISM class"
        if name == "science":
            arr, cmap, unit = np.where(arr > 0, 1.0, np.nan), "Greens", "mineral detected"
        if name == "air_column_vs_gale":
            cmap, unit = "Blues", "x Gale air column"
        if name == "imagery":
            finite = arr[np.isfinite(arr)]
            lo, hi = (np.percentile(finite, 1), np.percentile(finite, 99)) if finite.size else (0, 1)
            return {"image": to_png(arr, "gray", lo, hi, alpha=1.0), "rect": c.rect,
                    "legend": legend(name, "brightness", lo, hi, "gray"),
                    "sun": {"elevation": round(sun_e, 1), "azimuth": round(sun_az, 1)}}
    elif name == "illumination":
        arr, unit, cmap = np.clip(illum, 0, 1), "cos(i)", "inferno"
    elif name == "temperature":
        arr, unit, cmap = temp, "K (approx.)", "coolwarm"
    elif name == "cost":
        arr, unit, cmap = cost, "s/m", "RdYlGn_r"
    elif name == "suitability":
        arr, unit, cmap = suitability(c, v, cost), "0 poor - 1 best", "RdYlGn"
    elif name == "shelter":
        passable = np.isfinite(cost)
        seeds = physics.shelter_seeds(c.bands["slope"], passable, steep_deg=v["max_slope"] + 2)
        t = physics.travel_time_from(cost, seeds, c.pixel_m) / 60
        arr, unit, cmap = np.where(passable, t, np.nan), "min to cover", "RdYlGn_r"
    else:
        raise HTTPException(404, f"unknown layer {name}")
    finite = np.asarray(arr)[np.isfinite(arr)]
    lo, hi = (np.percentile(finite, 2), np.percentile(finite, 98)) if finite.size else (0, 1)
    return {"image": to_png(arr, cmap, lo, hi), "rect": c.rect, "legend": legend(name, unit, lo, hi, cmap),
            "sun": {"elevation": round(sun_e, 1), "azimuth": round(sun_az, 1)}}


@app.post("/api/plan")
def plan(req: PlanRequest):
    c = get_cube(req.region)
    v, sun_e, sun_az, illum, temp, cost = conditions_layers(c, req)
    start, goal = c.rc(req.base.lat, req.base.lon), c.rc(req.target.lat, req.target.lon)
    warnings = []
    if 180 <= req.ls <= 330:
        warnings.append(f"Season Ls {req.ls:.0f}: dusty season (Ls ~180-330), when regional/global dust storms "
                        "usually occur. Check dust forecasts; EVAs are cancelled during storms.")
    if sun_e < req.min_sun_elev:
        warnings.append(f"Sun is {sun_e:.0f} deg above the horizon (minimum {req.min_sun_elev:.0f}). "
                        "Walks are restricted near dawn/dusk.")
    for name, (r, col) in (("Base", start), ("Target", goal)):
        if not np.isfinite(cost[r, col]):
            warnings.append(f"{name} is on terrain too steep for {v['label']} "
                            f"({c.bands['slope'][r, col]:.0f} deg > {v['max_slope']} deg).")

    # Walk-back zone: places you can reach AND return from within the budget minus reserve
    t_from_base = physics.travel_time_from(cost, [start], c.pixel_m)
    usable_s = req.budget_hours * 3600 * (1 - req.reserve)
    walkback = np.where(2 * t_from_base <= usable_s, 1.0, np.nan)
    walkback_t = np.where(np.isfinite(walkback), t_from_base / 60, np.nan)

    path, seconds = physics.best_route(cost, start, goal, c.pixel_m)
    result = {"warnings": warnings, "sun": {"elevation": round(sun_e, 1), "azimuth": round(sun_az, 1)},
              "rect": c.rect,
              "walkback_image": to_png(walkback_t, "YlGn_r", 0, usable_s / 120, alpha=0.45)}
    if path is None:
        result["route"] = None
        result["explanation"] = "No safe route exists under these limits. Try another vehicle, time, or target."
        return result

    coords = [c.latlon(r, col) for r, col in path]
    seg = np.array([[(r2 - r1) * c.pixel_m[0], (c2 - c1) * c.pixel_m[1]]
                    for (r1, c1), (r2, c2) in zip(path[:-1], path[1:])])
    dist_m = float(np.hypot(seg[:, 0], seg[:, 1]).sum()) if len(seg) else 0.0
    rr, cc = np.array(path).T
    route_slope = c.bands["slope"][rr, cc]
    firm = c.bands.get("firmness")

    # Compare with the straight line to explain WHY this route
    n = max(abs(goal[0] - start[0]), abs(goal[1] - start[1]), 1) + 1
    lr = np.linspace(start[0], goal[0], n).round().astype(int)
    lc = np.linspace(start[1], goal[1], n).round().astype(int)
    straight_dist = math.hypot((goal[0] - start[0]) * c.pixel_m[0], (goal[1] - start[1]) * c.pixel_m[1])
    blocked = int((~np.isfinite(cost[lr, lc])).sum())
    reasons = []
    if blocked:
        reasons.append(f"the straight line crosses {blocked} pixels steeper than {v['max_slope']:.0f} deg")
    if firm is not None:
        sl, rt = float(np.nanmean(firm[lr, lc])), float(np.nanmean(firm[rr, cc]))
        if sl < rt - 0.03:
            reasons.append(f"it stays on firmer ground (firmness {rt:.2f} vs {sl:.2f} on the straight line)")
    if np.nanmean(c.bands["slope"][lr, lc]) > np.nanmean(route_slope) + 0.5:
        reasons.append(f"average slope {np.nanmean(route_slope):.1f} deg instead of "
                       f"{np.nanmean(c.bands['slope'][lr, lc]):.1f} deg")
    round_trip_h = 2 * seconds / 3600
    within = round_trip_h <= req.budget_hours * (1 - req.reserve)
    if not within:
        warnings.append(f"Round trip needs {round_trip_h:.1f} h but only "
                        f"{req.budget_hours * (1 - req.reserve):.1f} h is usable after the reserve.")
    explanation = (f"{v['label']}: {dist_m / 1000:.2f} km route, about {seconds / 3600:.1f} h one way "
                   f"({round_trip_h:.1f} h round trip). Straight line would be {straight_dist / 1000:.2f} km. ")
    explanation += ("Detour chosen because " + "; ".join(reasons) + ".") if reasons else \
        "The direct path is already the safest."
    result.update({
        "route": [{"lat": a, "lon": b} for a, b in coords[:: max(1, len(coords) // 400)]] + [
            {"lat": coords[-1][0], "lon": coords[-1][1]}],
        "stats": {"distance_km": round(dist_m / 1000, 2), "one_way_h": round(seconds / 3600, 2),
                  "round_trip_h": round(round_trip_h, 2), "max_slope_deg": round(float(np.nanmax(route_slope)), 1),
                  "mean_slope_deg": round(float(np.nanmean(route_slope)), 1), "within_budget": within},
        "explanation": explanation,
    })
    return result


# ------------------------------------------------- NASA Trek tile proxy ----
_tile_cache = {}


@app.get("/tiles/{layer}/{z}/{y}/{x}.jpg")
def trek_tile(layer: str, z: int, y: int, x: int):
    """Relay Mars Trek WMTS tiles so the browser can use them (Trek sends no CORS header)."""
    import urllib.request
    from fastapi.responses import Response
    key = (layer, z, y, x)
    if key not in _tile_cache:
        url = (f"https://trek.nasa.gov/tiles/Mars/EQ/{layer}/1.0.0/default/default028mm/{z}/{y}/{x}.jpg")
        try:
            import ssl
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                ctx = ssl.create_default_context()
            req = urllib.request.Request(url, headers={"User-Agent": "MarswalkPlanner/0.1"})
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                _tile_cache[key] = r.read()
        except Exception as ex:
            raise HTTPException(404, f"no tile: {ex}")
        if len(_tile_cache) > 5000:
            _tile_cache.pop(next(iter(_tile_cache)))
    return Response(_tile_cache[key], media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------- global 5 m CTX mosaic, colourised ----
CTX_TILES = "https://astro.arcgis.com/arcgis/rest/services/OnMars/CTX1/MapServer/tile"   # Murray Lab, Caltech
VIKING = "Mars_Viking_MDIM21_ClrMosaic_global_232m"
VIKING_LEVEL = 7                     # Trek's deepest Viking level (~1.4 deg tiles, 256 px)
_ctx_cache = {}


_session = None
TILE_DIR = ROOT / "cubes" / "tilecache"          # tiles saved to disk: instant on the next run


def _get(url):
    """HTTP GET with a shared keep-alive connection pool (avoids a new TLS handshake per tile)."""
    global _session
    try:
        import requests  # noqa: F401
    except ImportError:                      # fallback if 'requests' isn't installed
        import ssl
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MarswalkPlanner)"})
        with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
            return r.read()
    if _session is None:
        import requests
        from requests.adapters import HTTPAdapter
        _session = requests.Session()
        _session.headers["User-Agent"] = "Mozilla/5.0 (MarswalkPlanner)"
        _session.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=32))
    r = _session.get(url, timeout=20)
    r.raise_for_status()
    return r.content


def _fast_lowpass(img, factor=16):
    """Cheap large blur: shrink, then enlarge (much faster than a big Gaussian)."""
    h, w = img.shape
    small = Image.fromarray((img * 255).astype("uint8")).resize((max(1, w // factor), max(1, h // factor)), Image.BILINEAR)
    return np.asarray(small.resize((w, h), Image.BILINEAR), dtype="float32") / 255.0


@lru_cache(maxsize=256)
def _viking_tile(row, col):
    url = (f"https://trek.nasa.gov/tiles/Mars/EQ/{VIKING}/1.0.0/default/default028mm/"
           f"{VIKING_LEVEL}/{row}/{col}.jpg")
    return np.asarray(Image.open(io.BytesIO(_get(url))).convert("RGB"), dtype="float32")


_missing = set()


@app.get("/ctxtiles/{z}/{y}/{x}.jpg")
def ctx_tile(z: int, y: int, x: int):
    """Global 5 m CTX tile (geographic, 512 px, same grid as Viking) coloured with Viking colours."""
    from fastapi.responses import Response
    key = (z, y, x)
    headers = {"Cache-Control": "public, max-age=604800"}
    if key in _missing:
        raise HTTPException(404, "no CTX tile")
    if key in _ctx_cache:
        return Response(_ctx_cache[key], media_type="image/jpeg", headers=headers)
    disk = TILE_DIR / f"{z}_{y}_{x}.jpg"
    if disk.exists():
        data = disk.read_bytes()
        _ctx_cache[key] = data
        return Response(data, media_type="image/jpeg", headers=headers)
    try:
        gray = np.asarray(Image.open(io.BytesIO(_get(f"{CTX_TILES}/{z}/{y}/{x}"))).convert("L"),
                          dtype="float32") / 255.0
    except Exception:
        _missing.add(key)
        raise HTTPException(404, "no CTX tile")
    out = None
    if z >= VIKING_LEVEL:
        try:
            f = 2 ** (z - VIKING_LEVEL)                 # CTX tile nests inside one Viking tile
            vik = _viking_tile(y // f, x // f)
            s = 256 / f
            x0, y0 = int((x % f) * s), int((y % f) * s)
            crop = Image.fromarray(vik.astype("uint8")).crop((x0, y0, max(int((x % f + 1) * s), x0 + 1),
                                                               max(int((y % f + 1) * s), y0 + 1)))
            color = np.asarray(crop.resize(gray.shape[::-1], Image.BILINEAR), dtype="float32")
            detail = (gray + 0.04) / (_fast_lowpass(gray) + 0.04)
            out = np.clip(color * np.clip(detail, 0.3, 2.2)[..., None], 0, 255).astype("uint8")
        except Exception:
            out = None
    if out is None:                                   # fallback: greyscale
        g = (gray * 255).astype("uint8")
        out = np.dstack([g, g, g])
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=82)
    data = buf.getvalue()
    _ctx_cache[key] = data
    if len(_ctx_cache) > 3000:
        _ctx_cache.pop(next(iter(_ctx_cache)))
    try:
        TILE_DIR.mkdir(parents=True, exist_ok=True)
        disk.write_bytes(data)
    except Exception:
        pass
    return Response(data, media_type="image/jpeg", headers=headers)


class Box(BaseModel):
    west: float
    south: float
    east: float
    north: float
    max_level: int = 12


_prefetch = {"done": 0, "total": 0, "running": False}


@app.post("/api/prefetch")
def prefetch(box: Box):
    """Download + colour every CTX tile inside the box (levels 8..max_level) in the background,
    so that area is instant later (e.g. before recording the demo)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    tiles = []
    for z in range(8, box.max_level + 1):
        t = 180.0 / 2 ** z
        for y in range(int((90 - box.north) // t), int((90 - box.south) // t) + 1):
            for x in range(int((box.west + 180) // t), int((box.east + 180) // t) + 1):
                tiles.append((z, y, x))
    if len(tiles) > 4000:
        raise HTTPException(400, f"Box too big ({len(tiles)} tiles). Draw a smaller box (about 1 degree).")
    _prefetch.update(done=0, total=len(tiles), running=True)

    def one(t):
        try:
            ctx_tile(*t)
        except Exception:
            pass
        _prefetch["done"] += 1

    def run():
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(one, tiles))
        _prefetch["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return {"tiles": len(tiles)}


@app.get("/api/prefetch")
def prefetch_status():
    return _prefetch


(ROOT / "cubes").mkdir(exist_ok=True)
app.mount("/cubes", StaticFiles(directory=ROOT / "cubes"), name="cubes")

# Serve the front end from the same server (one command = whole app)
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
