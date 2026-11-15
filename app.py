"""
Back end: holds the Mars data cube(s) and does all the math.
The Cesium front end only displays what this returns.

Run:   uvicorn app:app --reload --port 8000
Open:  http://localhost:8000
"""
import base64
import io
import json
import math
import uuid
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from matplotlib import colormaps
from matplotlib.colors import LinearSegmentedColormap, to_hex
from PIL import Image
from pydantic import BaseModel, Field

import mission
import murray
import physics
import search
from config import (CONSUMABLE_SOURCES, MARS_RADIUS_M, MATRIX_CRITERIA, MINERALS, MISSION_VEHICLES,
                    PRIORITIES, SCIENCE_TARGETS, SEARCH_ZONES, SEASONS, VEHICLES)
from mars_weather import GLOBAL_RECT, WEATHER_LAYERS, weather_layer, wind_components
from surface_temperature import temperature_overlay
from thermal_detail import DETAIL_STEP, detail_overlay, detail_sample

ROOT = Path(__file__).parent
app = FastAPI(title="Mars Marswalk Planner")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Violet shadows, icy blues, cream, and copper inspired by false-color imagery.
THERMAL_PALETTE = LinearSegmentedColormap.from_list("mars_thermal", [
    (0.00, "#291444"), (0.18, "#4d3690"), (0.32, "#6b9dcc"),
    (0.43, "#aed3df"), (0.51, "#f4e6db"), (0.65, "#eaba99"),
    (0.78, "#c26d52"), (1.00, "#641a34"),
])
THERMAL_SCALE = (145, 315, "mars_thermal")


def layer_palette(name):
    return THERMAL_PALETTE if name == "mars_thermal" else colormaps[name]

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
    valid = a[~bad]
    lo = (np.percentile(valid, 2) if valid.size else 0.0) if vmin is None else vmin
    hi = (np.percentile(valid, 98) if valid.size else 1.0) if vmax is None else vmax
    norm = np.clip((np.where(bad, lo, a) - lo) / max(hi - lo, 1e-9), 0, 1)
    rgba = (layer_palette(cmap)(norm) * 255).astype("uint8")
    rgba[..., 3] = np.where(bad, 0, int(alpha * 255))
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def interpolate_display(arr, factor, wrap_longitude=False):
    """Densify only the display, keeping each missing source cell transparent."""
    height, width = arr.shape
    valid = np.isfinite(arr)
    values = np.where(valid, arr, 0)
    weights = valid.astype("float32")
    if wrap_longitude:
        values = np.pad(values, ((0, 0), (1, 1)), mode="wrap")
        weights = np.pad(weights, ((0, 0), (1, 1)), mode="wrap")
    size = (values.shape[1] * factor, height * factor)

    def resize(data):
        raster = Image.fromarray(data.astype("float32")).resize(size, Image.Resampling.BILINEAR)
        if wrap_longitude:
            raster = raster.crop((factor, 0, (width + 1) * factor, height * factor))
        return np.asarray(raster)

    weight = resize(weights)
    display = resize(values) / np.maximum(weight, np.finfo("float32").eps)
    mask = valid.repeat(factor, axis=0).repeat(factor, axis=1)
    return np.where(mask, display, np.nan)


def legend(name, unit, lo, hi, cmap):
    return {"name": name, "unit": unit, "min": float(f"{lo:.3g}"), "max": float(f"{hi:.3g}"), "cmap": cmap,
            "colors": [to_hex(layer_palette(cmap)(fraction)) for fraction in np.linspace(0, 1, 17)]}


class Point(BaseModel):
    lat: float
    lon: float


class Conditions(BaseModel):
    region: str = "jezero"
    vehicle: str = "astronaut"
    local_hour: float = Field(11.0, ge=0, le=24, description="Mars local solar time")
    ls: float = Field(90.0, ge=0, le=360, description="Season, solar longitude")
    budget_hours: float = Field(4.0, gt=0, description="Requested trip time budget in hours before reserve")
    reserve: float = Field(0.25, ge=0, lt=1, description="Fraction of budget held back for emergencies")
    min_sun_elev: float = 10.0
    weights: dict = {}


class PlanRequest(Conditions):
    base: Point
    target: Point


class LayerSample(Conditions):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    detail: bool = False


class ThermalView(Conditions):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)


@lru_cache(maxsize=1)
def season_calendar():
    return json.loads((ROOT / "thermal_data" / "season_calendar.json").read_text(encoding="utf-8"))


def global_cell(lat, lon, shape):
    height, width = shape
    return (min(int((90 - lat) * height / 180), height - 1),
            int(((lon + 180) % 360) * width / 360))


class MissionRequest(BaseModel):
    region: str = "jezero"
    goal: str = Field(..., min_length=1, max_length=300, description='e.g. "sample clay where water once flowed"')
    vehicle: str = "on_foot"
    season: str = "northern_summer"
    priority: str = "safety"
    green_only: bool = Field(False, description="stick to green, rover-verified tracks where possible")


class FindRequest(Conditions):
    query: str = Field(..., min_length=1, max_length=300, description='e.g. "valley with clay"')
    base: Point | None = None
    focus: Point | None = Field(None, description="centre of the user's view; breaks ties between equal matches")
    count: int = Field(5, ge=1, le=10)


def conditions_layers(cube, cond):
    v = VEHICLES.get(cond.vehicle)
    if v is None:
        raise HTTPException(400, f"vehicle must be one of {list(VEHICLES)}")
    b = cube.bands
    lat_c = (cube.s + cube.n) / 2
    sun_e, sun_az = physics.sun_position(lat_c, cond.local_hour, cond.ls)
    illum = physics.illumination(b["slope"], b["aspect"], sun_e, sun_az)
    cost = physics.cost_seconds_per_meter(b, v, cond.weights)
    return v, sun_e, sun_az, illum, cost


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


# ---------------------------------------------------------- consumables ----
BINDING_LABEL = {"oxygen": "The suit's O2", "energy": "On-board energy", "rated": "Rated endurance"}


def vehicle_spec(v):
    """Public description of one vehicle's limits, so the front end never hardcodes a constant."""
    c = v.get("consumables") or {}
    return {"label": v["label"], "max_slope": v["max_slope"], "rated_hours": v.get("rated_hours"),
            "o2_rate_kg_per_h": c.get("o2_rate_kg_per_h"), "o2_capacity_kg": c.get("o2_capacity_kg"),
            "energy_capacity_kwh": c.get("energy_capacity_kwh"), "energy_idle_kw": c.get("energy_idle_kw"),
            "energy_per_km_kwh": c.get("energy_per_km_kwh"),
            "source": CONSUMABLE_SOURCES.get(v.get("consumable_source", ""), "")}


def consumables_block(v, seconds, distance_m, veh_key=""):
    """Round-trip O2 / energy against what the vehicle carries, and which of ITS limits binds first.

    The round trip is twice the outward leg, matching how the walk-back zone already assumes
    the return costs what the outbound leg cost. limiting_factor deliberately compares only the
    vehicle's own limits (O2, energy, rated endurance) - whether the user's time budget allows
    the trip at all is reported separately, as within_budget.
    """
    e = physics.endurance(v, seconds, distance_m)
    trip_h = 2 * seconds / 3600.0

    stats = {"endurance_h": round(e["endurance_h"], 1),
             "max_range_km": round(e["max_range_km"], 2),
             "o2_used_kg": None, "o2_max_kg": None, "o2_pct": None,
             "energy_used_kwh": None, "energy_max_kwh": None, "energy_pct": None}
    warnings = []

    if e["o2_kg"] is not None:
        o2, cap = 2 * e["o2_kg"], e["o2_capacity_kg"]
        stats.update(o2_used_kg=round(o2, 2), o2_max_kg=round(cap, 2), o2_pct=int(round(100 * o2 / cap)))
        if o2 > cap:
            warnings.append(f"Round trip needs {o2:.2f} kg of O2 but the suit carries {cap:.2f} kg "
                            f"({stats['o2_pct']}%). Shorten the route or send a rover.")
    if e["energy_kwh"] is not None:
        kwh, cap = 2 * e["energy_kwh"], e["energy_capacity_kwh"]
        stats.update(energy_used_kwh=round(kwh, 2), energy_max_kwh=round(cap, 2),
                     energy_pct=int(round(100 * kwh / cap)))
        if kwh > cap:
            hint = "" if veh_key == "pressurized_rover" else \
                " The pressurized rover has more headroom."
            warnings.append(f"Round trip needs {kwh:.2f} kWh but {v['label']} carries only {cap:.2f} kWh "
                            f"({stats['energy_pct']}%).{hint}")

    # Which limit actually runs out first: a consumable with the highest fraction used. The
    # rated endurance only wins when nothing is consumed over its limit but the trip outlasts
    # the vehicle's rating, so a bar at 1061% is never labelled "rated endurance".
    limits = e["limits_hours"] or {}
    fractions = {k: trip_h / limits[k] for k in ("oxygen", "energy")
                 if k in limits and limits[k] > 0}
    binding = max(fractions, key=fractions.get) if fractions else None
    outlasts_rating = trip_h > limits.get("rated", math.inf)
    if outlasts_rating and (binding is None or fractions[binding] <= 1.0):
        binding = "rated"
    stats["limiting_factor"] = binding
    return {"stats": stats, "warnings": warnings,
            "binding_label": BINDING_LABEL.get(binding, "No rated limit")}


# ------------------------------------------------------------ endpoints ----
@app.get("/api/regions")
def regions():
    out = []
    for p in sorted((ROOT / "cubes").glob("*.npz")):
        c = get_cube(p.stem)
        out.append({"region": c.region, "rect": c.rect, "size": [c.W, c.H], "bands": c.names,
                    "pixel_m": [round(c.pixel_m[0]), round(c.pixel_m[1])], "provenance": c.provenance,
                    "targets": SCIENCE_TARGETS.get(c.region, []),
                    "minerals": {n: m["label"] for n, m in MINERALS.items() if n in c.bands}})
    return {"regions": out, "vehicles": {k: v["label"] for k, v in VEHICLES.items()},
            "vehicle_specs": {k: vehicle_spec(v) for k, v in VEHICLES.items()}}


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
    minerals = [f"{m['label']}: {search.mineral_strength(n, c.bands[n][r, col])}"
                for n, m in MINERALS.items() if n in c.bands and np.isfinite(c.bands[n][r, col])
                and c.bands[n][r, col] >= m["detect"]]
    return {"lat": lat, "lon": lon, "values": vals, "ground": ground, "minerals": minerals, "notes": notes,
            "confidence": round(float(c.coverage[r, col]), 2), "source": c.region}


@app.get("/api/weather/calendar")
def weather_calendar():
    return {"sols": list(range(1, len(season_calendar()) + 1)), "ls": season_calendar()}


@app.get("/api/weather/sources", response_class=FileResponse)
def weather_sources():
    return FileResponse(ROOT / "weather_sources.csv", media_type="text/csv",
                        filename="mars_weather_sources.csv")


@lru_cache(maxsize=8)
def temperature_image(west, south, east, north, local_hour, ls):
    arr, rect = detail_overlay(west, south, east, north, local_hour, ls)
    lo, hi, cmap = THERMAL_SCALE
    display = interpolate_display(arr, factor=2)
    finite = arr[np.isfinite(arr)]
    return {"image": to_png(display, cmap, lo, hi, alpha=0.88), "rect": rect,
            "grid_step_deg": DETAIL_STEP, "source_cells": int(arr.size),
            "temperature_range": [round(float(finite.min()), 1), round(float(finite.max()), 1)] if finite.size else None}


@app.post("/api/weather/temperature-detail")
def temperature_detail(view: ThermalView):
    if view.west >= view.east or view.south >= view.north:
        raise HTTPException(422, "Use an ordered viewport within one side of the longitude seam")
    try:
        return temperature_image(view.west, view.south, view.east, view.north, view.local_hour, view.ls)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/layer/{name}/sample")
def sample_layer(name: str, cond: LayerSample):
    """Read the native model cell under the mouse, independently of PNG colors."""
    lat, lon = cond.lat, cond.lon
    extra = {}
    if name in ("temperature", "global_temperature"):
        if name == "temperature":
            cube = get_cube(cond.region)
            if not (cube.s <= lat <= cube.n and cube.w <= lon <= cube.e):
                return {"value": None, "unit": "K", "label": "Ground temperature"}
        if name == "global_temperature" and cond.detail:
            value = detail_sample(lat, lon, cond.local_hour, cond.ls)
            extra["grid_step_deg"] = DETAIL_STEP
        else:
            row, col = global_cell(lat, lon, (360, 720))
            north, west = 90 - row * 0.5, -180 + col * 0.5
            cell = {"north": north, "south": north - 0.5, "west": west, "east": west + 0.5}
            value = temperature_overlay(cell, (1, 1), cond.local_hour, cond.ls)[0, 0]
            extra["grid_step_deg"] = 0.5
        unit, label = "K", "Ground temperature"
    elif name in WEATHER_LAYERS:
        extra["grid_step_deg"] = 5
        if name in ("wind_speed", "wind_direction"):
            east, north = wind_components(cond.local_hour, cond.ls)
            row, col = global_cell(lat, lon, east.shape)
            u, v = east[row, col], north[row, col]
            value = np.hypot(u, v)
            if value >= 0.1:
                extra["toward_deg"] = round(float(np.degrees(np.arctan2(u, v)) % 360)) % 360
            unit, label = "m/s", "Wind speed"
        else:
            arr = weather_layer(name, cond.local_hour, cond.ls)
            label, unit, *_ = WEATHER_LAYERS[name]
            value = arr[global_cell(lat, lon, arr.shape)]
    else:
        raise HTTPException(404, "No hover values for this layer")
    return {"value": round(float(value), 2) if np.isfinite(value) else None,
            "unit": unit, "label": label, **extra}


@app.post("/api/layer/{name}")
def layer(name: str, cond: Conditions):
    """Coloured overlay of one band or one computed layer, for the current conditions."""
    if name in WEATHER_LAYERS:
        title, unit, lo, hi, cmap = WEATHER_LAYERS[name]
        wind = None
        field = None
        if name == "wind_direction":
            east, north = wind_components(cond.local_hour, cond.ls)
            arr = np.hypot(east, north)
            field = {"east_ms": np.round(east, 3).tolist(), "north_ms": np.round(north, 3).tolist(), **GLOBAL_RECT}
            # Space glyphs on a regular 10° display grid and omit calm samples.
            wind = [{"lat": 87.5 - r * 5, "lon": -177.5 + c * 5,
                     "east_ms": round(float(east[r, c]), 3),
                     "north_ms": round(float(north[r, c]), 3)}
                    for r in range(1, 36, 2) for c in range(0, 72, 2)
                    if np.isfinite(arr[r, c]) and arr[r, c] >= 0.1]
        else:
            arr = weather_layer(name, cond.local_hour, cond.ls)
        finite = arr[np.isfinite(arr)]
        display = interpolate_display(arr, factor=4, wrap_longitude=True)
        return {"image": to_png(display, cmap, lo, hi, alpha=0.75), "rect": GLOBAL_RECT,
                "legend": legend(title, unit, lo, hi, cmap),
                "weather": True,
                "grid_step_deg": 5,
                "wind_vectors": wind,
                "wind_field": field,
                "data_range": [round(float(finite.min()), 2), round(float(finite.max()), 2)] if finite.size else None}
    c = None if name == "global_temperature" else get_cube(cond.region)
    if name in ("temperature", "global_temperature"):
        rect, shape = (GLOBAL_RECT, (360, 720)) if c is None else (c.rect, (c.H, c.W))
        arr = temperature_overlay(rect, shape, cond.local_hour, cond.ls)
        lo, hi, cmap = THERMAL_SCALE
        sun_e, sun_az = physics.sun_position((rect["south"] + rect["north"]) / 2, cond.local_hour, cond.ls)
        valid = arr[np.isfinite(arr)]
        observed_range = [round(float(valid.min()), 1), round(float(valid.max()), 1)] if valid.size else None
        display = interpolate_display(arr, factor=2, wrap_longitude=True) if c is None else arr
        return {"image": to_png(display, cmap, lo, hi, alpha=0.88), "rect": rect,
                "legend": legend("Simulated surface temperature", "K", lo, hi, cmap),
                "grid_step_deg": 0.5,
                "temperature_range": observed_range,
                "sun": {"elevation": round(sun_e, 1), "azimuth": round(sun_az, 1)}}
    v, sun_e, sun_az, illum, cost = conditions_layers(c, cond)
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
        if name in MINERALS:   # show only real detections: transparent below the detection limit
            m = MINERALS[name]
            shown = np.where(arr >= m["detect"], arr, np.nan)
            return {"image": to_png(shown, "YlOrRd", m["detect"], m["strong"], alpha=0.8), "rect": c.rect,
                    "legend": legend(m["label"], "CRISM " + "/".join(m["params"]), m["detect"], m["strong"], "YlOrRd"),
                    "sun": {"elevation": round(sun_e, 1), "azimuth": round(sun_az, 1)}}
        if name == "imagery":
            finite = arr[np.isfinite(arr)]
            lo, hi = (np.percentile(finite, 1), np.percentile(finite, 99)) if finite.size else (0, 1)
            return {"image": to_png(arr, "gray", lo, hi, alpha=1.0), "rect": c.rect,
                    "legend": legend(name, "brightness", lo, hi, "gray"),
                    "sun": {"elevation": round(sun_e, 1), "azimuth": round(sun_az, 1)}}
    elif name == "suitability":
        arr, unit, cmap = suitability(c, v, cost), "0 poor - 1 best", "RdYlGn"
    elif name == "illumination":
        arr, unit, cmap = np.clip(illum, 0, 1), "cos(i)", "inferno"
    elif name == "cost":
        arr, unit, cmap = cost, "s/m", "RdYlGn_r"
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
    v, sun_e, sun_az, illum, cost = conditions_layers(c, req)
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
    rated_hours = v.get("rated_hours") or math.inf
    budget_hours = min(req.budget_hours, rated_hours)
    if req.budget_hours > rated_hours:
        warnings.append(f"Time budget capped at the {v['label']} rating of {rated_hours:g} h.")
    usable_s = budget_hours * 3600 * (1 - req.reserve)
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
    within = 2 * seconds <= usable_s
    if not within:
        warnings.append(f"Round trip needs {round_trip_h:.1f} h but only "
                        f"{usable_s / 3600:.1f} h is usable after the reserve.")

    # O2 / energy for the round trip, against what this vehicle actually carries
    cons = consumables_block(v, seconds, dist_m, req.vehicle)
    warnings.extend(cons["warnings"])

    explanation = (f"{v['label']}: {dist_m / 1000:.2f} km route, about {seconds / 3600:.1f} h one way "
                   f"({round_trip_h:.1f} h round trip). Straight line would be {straight_dist / 1000:.2f} km. ")
    explanation += ("Detour chosen because " + "; ".join(reasons) + ".") if reasons else \
        "The direct path is already the safest."
    spent = []
    if cons["stats"]["o2_used_kg"] is not None:
        spent.append(f"{cons['stats']['o2_used_kg']:.2f} kg of O2 (of {cons['stats']['o2_max_kg']:.2f} kg)")
    if cons["stats"]["energy_used_kwh"] is not None:
        spent.append(f"{cons['stats']['energy_used_kwh']:.2f} kWh (of {cons['stats']['energy_max_kwh']:.2f} kWh)")
    if spent:
        explanation += (f" Round trip uses {' and '.join(spent)}. "
                        f"{cons['binding_label']} is the tightest vehicle limit")
        explanation += ", and the EVA time budget is already exceeded." if not within else "."
    result.update({
        "route": [{"lat": a, "lon": b} for a, b in coords[:: max(1, len(coords) // 400)]] + [
            {"lat": coords[-1][0], "lon": coords[-1][1]}],
        "stats": {"distance_km": round(dist_m / 1000, 2), "one_way_h": round(seconds / 3600, 2),
                  "round_trip_h": round(round_trip_h, 2), "max_slope_deg": round(float(np.nanmax(route_slope)), 1),
                  "mean_slope_deg": round(float(np.nanmean(route_slope)), 1), "within_budget": within,
                  **cons["stats"]},
        "explanation": explanation,
    })
    return result


@app.post("/api/find")
def find(req: FindRequest):
    """Turn a text description ("valley with clay") into the best matching target pixels."""
    c = get_cube(req.region)
    v, sun_e, sun_az, illum, cost = conditions_layers(c, req)
    temp = physics.surface_temp_k(illum, c.bands.get("firmness"), sun_e, c.bands.get("albedo"))
    t_base, notes = None, []
    focus = (req.focus.lat, req.focus.lon) if req.focus else ((c.s + c.n) / 2, (c.w + c.e) / 2)
    usable_s = min(req.budget_hours, v.get("rated_hours") or math.inf) * 3600 * (1 - req.reserve)
    if req.base:
        try:
            t_base = physics.travel_time_from(cost, [c.rc(req.base.lat, req.base.lon)], c.pixel_m)
            focus = (req.base.lat, req.base.lon)
        except HTTPException:
            notes.append("The base is outside this region, so distance from base was ignored.")
    ctx = search.Ctx(c, v, sun_e, illum, temp, cost, t_base=t_base, usable_s=usable_s,
                     zones=SEARCH_ZONES.get(c.region, []))
    ctx.notes.extend(notes)
    try:
        res = search.find(ctx, req.query, count=req.count, focus=focus)
    except ValueError as e:
        raise HTTPException(400, str(e))
    score = res.pop("score")
    res.update(rect=c.rect, heatmap=to_png(score, "plasma", 0, 1, alpha=0.55),
               sun={"elevation": round(sun_e, 1), "azimuth": round(sun_az, 1)})
    return res


_missions = {}   # mission id -> facts for the explanation (last 50)


@app.get("/api/mission/options")
def mission_options():
    return {"vehicles": {k: {"label": v["label"], "max_slope": v["max_slope"], "range_km": v["range_km"]}
                         for k, v in MISSION_VEHICLES.items()},
            "seasons": {k: v["label"] for k, v in SEASONS.items()},
            "priorities": {k: v["label"] for k, v in PRIORITIES.items()},
            "criteria": {k: {"label": v[0], "weight": v[1]} for k, v in MATRIX_CRITERIA.items()}}


@app.post("/api/mission")
def plan_mission(req: MissionRequest):
    """Goal + vehicle + season + priority -> 3 candidate missions, the decision matrix and the winner."""
    c = _mission_cube(req)
    try:
        res = mission.plan(c, req.goal, req.vehicle, req.season, req.priority, req.green_only)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _finish_mission(res)


def _mission_cube(req):
    for name, value, allowed in (("vehicle", req.vehicle, MISSION_VEHICLES), ("season", req.season, SEASONS),
                                 ("priority", req.priority, PRIORITIES)):
        if value not in allowed:
            raise HTTPException(400, f"{name} must be one of {list(allowed)}")
    return get_cube(req.region)


def _finish_mission(res):
    """Give the plan an id (for the explanation) and turn its maps into PNG overlays."""
    score, red = res.pop("_score"), res.pop("_red")
    res["id"] = uuid.uuid4().hex[:12]
    _missions[res["id"]] = mission.explain_facts(res)
    while len(_missions) > 50:
        _missions.pop(next(iter(_missions)))
    res["science_image"] = to_png(np.where(score >= 0.15, score, np.nan), "plasma", 0.15, 1, alpha=0.55)
    res["offlimits_image"] = to_png(np.where(red, 0.8, np.nan), "Reds", 0, 1, alpha=0.45)
    return res


@app.post("/api/mission/stream")
def plan_mission_stream(req: MissionRequest):
    """The same plan as /api/mission, as a stream of server-sent events, with the AI model's thinking live:
    {"type": "status"|"ai"|"result"|"explanation"|"note"|"error"|"done", ...}
    "ai" events carry phase ("goal" = reading the goal, "explain" = explaining the choice), kind ("reasoning" =
    the model's thinking, "content" = its answer) and a piece of text."""
    c = _mission_cube(req)

    def event(**data):
        return f"data: {json.dumps(data, default=lambda o: o.item() if hasattr(o, 'item') else str(o))}\n\n"

    def events():
        spec, parser, notes = search.keyword_parse(req.goal), "keywords", []
        if spec["unknown"] or not spec["criteria"]:
            yield event(type="status", text="The AI model is reading the goal…")
            for kind, *rest in search.ai_parse_stream(req.goal):
                if kind in ("reasoning", "content"):
                    yield event(type="ai", phase="goal", kind=kind, text=rest[0])
                elif kind == "spec" and rest[0]["criteria"]:
                    spec, parser = rest[0], "ai"
                elif kind == "error":
                    notes.append(rest[0])
        yield event(type="status", text="Scoring every pixel, finding landing spots, routing 3 candidates…")
        try:
            res = _finish_mission(mission.plan(c, req.goal, req.vehicle, req.season, req.priority, req.green_only,
                                               goal_spec=(spec, parser, notes)))
        except ValueError as e:
            yield event(type="error", text=str(e))
            return
        yield event(type="result", mission=res)
        if res["candidates"]:
            yield event(type="status", text="The AI model is explaining the choice…")
            text = None
            for kind, *rest in mission.explain_stream(_missions[res["id"]]):
                if kind in ("reasoning", "content"):
                    yield event(type="ai", phase="explain", kind=kind, text=rest[0])
                elif kind == "done":
                    text = rest[0].strip() or None
                elif kind == "error":
                    yield event(type="note", text=rest[0])
            yield event(type="explanation", text=text or res["explanation"], source="ai" if text else "template")
        yield event(type="done")

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/mission/{mid}/explain")
def explain_mission(mid: str):
    """The AI-written explanation of a mission (slower, so the page asks for it after showing the plan)."""
    facts = _missions.get(mid)
    if facts is None:
        raise HTTPException(404, "unknown mission id (the server may have restarted); plan the mission again")
    text = mission.explain_ai(facts)
    return {"explanation": text or facts["summary"], "source": "ai" if text else "template"}


@app.get("/api/tracks")
def rover_tracks(region: str = "jezero", vehicle: str = "on_foot"):
    """Real rover drives classed green (no warning signs) / yellow (high strain), plus the red off-limits
    terrain for a vehicle."""
    c = get_cube(region)
    tr = mission.tracks(c)
    v = MISSION_VEHICLES.get(vehicle, MISSION_VEHICLES["on_foot"])
    red = mission.offlimits(c, v)
    out = {"rect": c.rect, "offlimits_image": to_png(np.where(red, 0.8, np.nan), "Reds", 0, 1, alpha=0.45),
           "offlimits_pct": round(100 * float(red.mean()), 1)}
    if tr is None:
        return {**out, "rover": None, "segments": [], "km": {"green": 0, "yellow": 0}}
    return {**out, "rover": tr["rover"], "source": tr["source"], "km": tr["km"],
            "segments": [{k: s[k] for k in ("sol", "class", "why", "length_m", "coords")} for s in tr["segments"]]}


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


app.include_router(murray.router)          # every map from the Murray Lab CTX viewer (murray.py)

(ROOT / "cubes").mkdir(exist_ok=True)
app.mount("/cubes", StaticFiles(directory=ROOT / "cubes"), name="cubes")   # hi-res photo overlays

# Serve the front end from the same server (one command = whole app)
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
