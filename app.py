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
import physics
import search
from config import (CONSUMABLE_SOURCES, MARS_RADIUS_M, MATRIX_CRITERIA, MINERALS, MISSION_VEHICLES,
                    PRIORITIES, SCIENCE_TARGETS, SEARCH_ZONES, SEASONS, VEHICLES)
from gear.api import router as gear_router
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


def _in_dust_season(ls, window):
    if ls is None:
        return False
    lo, hi = window
    return lo <= ls % 360 <= hi


def consumables_block(v, seconds, distance_m, veh_key="", route=None):
    """Round-trip O2 / energy against what the vehicle carries, and which of ITS limits binds first.

    The return leg is the outbound route walked or driven in reverse. With `route` (the planned path,
    the cost grid and the season) the totals account for the terrain:
      - walkers: oxygen follows metabolic effort, which rises uphill and falls downhill (Minetti 2002)
      - vehicles: energy to lift the vehicle up every climb is added (a lower bound)
      - solar vehicles: sunlight through this season's dust sets how long recharging takes
    A contingency (15 %, 20 % in dust-storm season) is held back from every supply; limits, range and
    the binding factor use what is left after it. limiting_factor compares only the vehicle's own limits
    (O2, energy, rated endurance); whether the user's time budget allows the trip is within_budget.
    """
    from config import CONSUMABLE_RESERVE, VEHICLE_POWER, WALKER

    c = v.get("consumables") or {}
    power = VEHICLE_POWER.get(veh_key, {})
    hours = max(float(seconds), 0.0) / 3600.0
    trip_h = 2 * hours
    km = max(float(distance_m), 0.0) / 1000.0
    avg_kmh = km / hours if hours > 1e-9 else 0.0

    profile, ls, latlon = None, None, None
    if route:
        cube = route["cube"]
        profile = physics.route_profile(cube.bands["elevation"], route["path"], route["cost"], cube.pixel_m,
                                        slope=cube.bands.get("slope"))
        ls = route.get("ls")
        mid = route["path"][len(route["path"]) // 2]
        latlon = cube.latlon(*mid)
    reserve = CONSUMABLE_RESERVE["dust_season" if _in_dust_season(ls, CONSUMABLE_RESERVE["dust_season_ls"])
                                 else "normal"]
    walking = veh_key == "astronaut"

    stats = {"o2_used_kg": None, "o2_max_kg": None, "o2_pct": None,
             "energy_used_kwh": None, "energy_max_kwh": None, "energy_pct": None,
             "reserve_pct": int(round(100 * reserve)), "o2_usable_kg": None, "energy_usable_kwh": None,
             "o2_flat_kg": None, "terrain_o2_factor": None, "slope_o2_factor": None, "o2_flat_pace_h": None,
             "climb_kwh": None,
             "elevation_gain_m": round(profile["gain_m"]) if profile else None,
             "elevation_loss_m": round(profile["loss_m"]) if profile else None,
             "power_source": power.get("source") or ("suit" if walking else None),
             "dust_opacity": None, "sunlight_pct": None, "solar_kwh_per_sol": None,
             "recharge_sols": None, "recharge_h": None}
    warnings, limits = [], {}

    if "o2_rate_kg_per_h" in c:
        rate, cap = c["o2_rate_kg_per_h"], float(c["o2_capacity_kg"])
        walk = physics.round_trip_walk(profile) if walking else {"slope_factor": 1.0, "flat_pace_share": 1.0}
        factor = walk["slope_factor"] * walk["flat_pace_share"]      # oxygen per planner-hour vs flat walking
        o2 = rate * trip_h * factor
        usable = cap * (1 - reserve)
        stats.update(o2_used_kg=round(o2, 2), o2_max_kg=round(cap, 2), o2_pct=int(round(100 * o2 / cap)),
                     o2_usable_kg=round(usable, 2))
        if walking:
            flat_kmh = v["base_speed_kmh"] * v["suit_factor"] * math.exp(-3.5 * 0.05)
            o2_flat = rate * 2 * km / max(flat_kmh, 1e-6)
            # terrain = everything about this ground (slow sand, rough rock, slope) against flat firm ground;
            # slope = the climb-out, descend-back effort alone, at this ground's pace
            stats.update(o2_flat_kg=round(o2_flat, 2), terrain_o2_factor=round(o2 / o2_flat, 2) if o2_flat else None,
                         slope_o2_factor=round(walk["slope_factor"], 2),
                         o2_flat_pace_h=round(trip_h * walk["flat_pace_share"], 2))
        limits["oxygen"] = usable / max(rate * factor, 1e-9)
        if o2 > cap:
            warnings.append(f"Round trip needs {o2:.2f} kg of O2 but the suit carries {cap:.2f} kg "
                            f"({stats['o2_pct']}%). Shorten the route or send a rover.")
        elif o2 > usable:
            warnings.append(f"Round trip uses {stats['o2_pct']}% of the suit's O2, cutting into the "
                            f"{stats['reserve_pct']}% reserve held back for contingencies.")
    if "energy_capacity_kwh" in c:
        kw = c["energy_idle_kw"] + c["energy_per_km_kwh"] * avg_kmh
        kwh = kw * trip_h
        if profile and power.get("mass_kg"):
            climb = physics.climb_energy_kwh(power["mass_kg"], profile["gain_m"] + profile["loss_m"])
            kwh += climb
            stats["climb_kwh"] = round(climb, 3)
        cap = float(c["energy_capacity_kwh"])
        usable = cap * (1 - reserve)
        stats.update(energy_used_kwh=round(kwh, 2), energy_max_kwh=round(cap, 2),
                     energy_pct=int(round(100 * kwh / cap)), energy_usable_kwh=round(usable, 2))
        eff_kw = kwh / trip_h if trip_h > 1e-9 else kw
        limits["energy"] = usable / eff_kw if eff_kw > 1e-9 else math.inf
        if kwh > cap:
            hint = "" if veh_key == "pressurized_rover" else \
                " The pressurized rover has more headroom."
            warnings.append(f"Round trip needs {kwh:.2f} kWh but {v['label']} carries only {cap:.2f} kWh "
                            f"({stats['energy_pct']}%).{hint}")
        elif kwh > usable:
            warnings.append(f"Round trip uses {stats['energy_pct']}% of the battery, cutting into the "
                            f"{stats['reserve_pct']}% reserve held back for contingencies.")
    if v.get("rated_hours"):
        limits["rated"] = float(v["rated_hours"])

    # Sunlight through this season's dust, and what it means for recharging
    if latlon and ls is not None and power.get("source") in ("solar", "battery", "nuclear"):
        tau = physics.dust_opacity(latlon[0], latlon[1], ls)
        frac = physics.daily_sunlight_fraction(latlon[0], ls, tau)
        if frac is not None:
            stats.update(dust_opacity=round(tau, 2), sunlight_pct=int(round(100 * frac)))
            if power["source"] == "solar" and power.get("sol_kwh"):
                per_sol = power["sol_kwh"] * frac
                stats["solar_kwh_per_sol"] = round(per_sol, 2)
                if stats["energy_used_kwh"] is not None:
                    stats["recharge_sols"] = round(kwh / per_sol, 1) if per_sol > 1e-6 else None
            if power["source"] == "battery" and power.get("recharge_ratio") and frac > 1e-6:
                stats["recharge_h"] = round(power["recharge_ratio"] * trip_h / frac, 1)
            if power["source"] in ("solar", "battery") and frac < 0.6:
                warnings.append(f"Dust lets only about {stats['sunlight_pct']}% of direct sunlight through here this "
                                f"season (opacity {tau:.2f}); skylight adds some back, but solar charging will be "
                                "slow. A dust storm like this ended Opportunity's mission.")

    # Which limit actually runs out first: a consumable with the highest fraction used. The
    # rated endurance only wins when nothing is consumed over its limit but the trip outlasts
    # the vehicle's rating, so a bar at 1061% is never labelled "rated endurance".
    fractions = {k: trip_h / limits[k] for k in ("oxygen", "energy")
                 if k in limits and limits[k] > 0}
    binding = max(fractions, key=fractions.get) if fractions else None
    outlasts_rating = trip_h > limits.get("rated", math.inf)
    if outlasts_rating and (binding is None or fractions[binding] <= 1.0):
        binding = "rated"
    endurance_h = min(limits.values()) if limits else 0.0
    stats.update(endurance_h=round(endurance_h, 1), max_range_km=round(0.5 * endurance_h * avg_kmh, 2),
                 limiting_factor=binding)
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


@app.get("/api/pixel")
def pixel(lat: float, lon: float, region: str = "jezero"):
    c = get_cube(region)
    r, col = c.rc(lat, lon)
    vals = {n: (None if not np.isfinite(c.bands[n][r, col]) else round(float(c.bands[n][r, col]), 3))
            for n in c.names}
    ti, firm = vals.get("thermal_inertia"), vals.get("firmness")
    if ti is not None:   # THEMIS thermal inertia classes (J m^-2 K^-1 s^-1/2)
        ground = f"thermal inertia {ti:.0f}: {search.ti_class(ti)}" + (" - slip/sinkage risk" if ti < 300 else "")
    else:
        ground = None if firm is None else ("loose sand/dust - slip risk" if firm < 0.3
                                            else "mixed" if firm < 0.6 else "firm / bedrock")
    minerals = [f"{m['label']}: {search.mineral_strength(n, c.bands[n][r, col])}"
                for n, m in MINERALS.items() if n in c.bands and np.isfinite(c.bands[n][r, col])
                and c.bands[n][r, col] >= m["detect"]]
    return {"lat": lat, "lon": lon, "values": vals, "ground": ground, "minerals": minerals,
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
        if name == "thermal_inertia":
            unit, cmap = "J m-2 K-1 s-1/2", "cividis"
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
    cons = consumables_block(v, seconds, dist_m, req.vehicle, route=dict(cube=c, path=path, cost=cost, ls=req.ls))
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
    temp = physics.surface_temp_k(illum, c.bands.get("firmness"), sun_e)
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


app.include_router(gear_router)

# Serve the front end from the same server (one command = whole app)
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
