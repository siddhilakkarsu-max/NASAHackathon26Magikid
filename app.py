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
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from matplotlib import colormaps
from matplotlib.colors import LinearSegmentedColormap, to_hex
from PIL import Image
from pydantic import BaseModel, Field

import physics
from config import MARS_RADIUS_M, SCIENCE_TARGETS, VEHICLES
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
    return {"name": name, "unit": unit, "min": round(float(lo), 2), "max": round(float(hi), 2), "cmap": cmap,
            "colors": [to_hex(layer_palette(cmap)(fraction)) for fraction in np.linspace(0, 1, 17)]}


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


@app.get("/api/pixel")
def pixel(lat: float, lon: float, region: str = "jezero"):
    c = get_cube(region)
    r, col = c.rc(lat, lon)
    vals = {n: (None if not np.isfinite(c.bands[n][r, col]) else round(float(c.bands[n][r, col]), 3))
            for n in c.names}
    firm = vals.get("firmness")
    ground = None if firm is None else ("loose sand/dust - slip risk" if firm < 0.3
                                        else "mixed" if firm < 0.6 else "firm / bedrock")
    return {"lat": lat, "lon": lon, "values": vals, "ground": ground,
            "confidence": round(float(c.coverage[r, col]), 2)}


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
        if name == "imagery":
            finite = arr[np.isfinite(arr)]
            lo, hi = (np.percentile(finite, 1), np.percentile(finite, 99)) if finite.size else (0, 1)
            return {"image": to_png(arr, "gray", lo, hi, alpha=1.0), "rect": c.rect,
                    "legend": legend(name, "brightness", lo, hi, "gray"),
                    "sun": {"elevation": round(sun_e, 1), "azimuth": round(sun_az, 1)}}
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


# Serve the front end from the same server (one command = whole app)
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
