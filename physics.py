"""
Per-pixel models applied on top of the static cube when the user changes inputs.
All are deliberately simple and labeled; each is a place a teammate can improve:
  - sun angle / illumination ............ (Jason)
  - surface temperature (approximate) .... (Jason)
  - slip + walking speed + cost .......... (Victoria / Gia)
  - walk-back zone, time-to-shelter ...... (Gia / Siddhi)
"""
import math

import numpy as np
from skimage.graph import MCP_Geometric

MARS_OBLIQUITY = 25.19  # degrees


# ------------------------------------------------------------------ sun ----
def sun_position(lat_deg, local_solar_hour, ls_deg):
    """Solar elevation and azimuth (deg, azimuth clockwise from north).
    local_solar_hour: 0-24 Mars local solar time. ls_deg: season (0 = northern spring)."""
    d = math.radians
    dec = math.asin(math.sin(d(MARS_OBLIQUITY)) * math.sin(d(ls_deg)))
    H = d(15.0 * (local_solar_hour - 12.0))
    phi = d(lat_deg)
    sin_e = math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(H)
    elev = math.asin(max(-1.0, min(1.0, sin_e)))
    az = math.atan2(-math.sin(H), math.tan(dec) * math.cos(phi) - math.sin(phi) * math.cos(H))
    return math.degrees(elev), (math.degrees(az) + 360) % 360


def illumination(slope, aspect, sun_elev, sun_az):
    """cos(incidence angle) on each sloped pixel. <= 0 means the slope faces away from the sun."""
    s, a = np.radians(slope), np.radians(aspect)
    e, z = math.radians(sun_elev), math.radians(sun_az)
    cos_i = np.cos(s) * math.sin(e) + np.sin(s) * math.cos(e) * np.cos(z - a)
    return np.where(sun_elev > 0, cos_i, -1.0).astype("float32")


def surface_temp_k(cos_i, firmness, sun_elev, albedo=None):
    """VERY approximate surface temperature (K). Swap in Jason's thermal model later.
    Loose material (low thermal inertia) heats more by day and cools more at night.
    Dark ground (low albedo) absorbs more sunlight: absorbed = (1 - albedo) x sunlight."""
    absorb = 1.0 if albedo is None else np.clip((1 - np.nan_to_num(albedo, nan=0.25)) / 0.75, 0.6, 1.3)
    if firmness is None:
        firmness = np.full_like(cos_i, 0.5)
    loose = 1.0 - np.nan_to_num(firmness, nan=0.5)
    if sun_elev <= 0:
        return (175 + 35 * (1 - loose)).astype("float32")
    sun = np.sqrt(np.clip(cos_i, 0, 1))
    return (185 + 105 * sun * absorb * (0.75 + 0.35 * loose)).astype("float32")


# ----------------------------------------------------------- mobility ----
def slip_fraction(slope_deg):
    """Upslope slip in granular terrain, from the MSL Engineering User Guide table
    (<10 deg: 0-25%, 10-17 deg: 25-80%, >17 deg: >80%). Linear between points."""
    return np.interp(slope_deg, [0, 10, 17, 25, 90], [0.0, 0.25, 0.80, 0.95, 1.0]).astype("float32")


def speed_kmh(slope, firmness, v):
    s = np.nan_to_num(slope, nan=0.0)
    loose = 1.0 - np.nan_to_num(firmness, nan=0.5)
    if v["uses_slip_table"]:
        slip = slip_fraction(s) * (0.3 + 0.7 * loose)   # slip mostly matters on loose ground
        return v["base_speed_kmh"] * np.clip(1 - slip, 0.02, 1)
    # Tobler's hiking function x suit factor (suited walking is slower)
    return v["base_speed_kmh"] * v["suit_factor"] * np.exp(-3.5 * np.abs(np.tan(np.radians(s)) + 0.05))


def cost_seconds_per_meter(cube, v, weights=None):
    """Travel cost of each pixel (seconds per meter). np.inf = not allowed (too steep / no data)."""
    w = {"slope": 1.0, "sand": 1.0, "rough": 1.0}
    w.update(weights or {})
    slope = cube["slope"]
    firm = cube.get("firmness", np.full_like(slope, 0.5))
    rough = cube["roughness"]
    rough_n = np.clip(rough / max(np.nanpercentile(rough, 95), 1e-6), 0, 2)
    spd = speed_kmh(slope * w["slope"], firm, v)
    cost = 3.6 / np.maximum(spd, 1e-3)                       # s/m
    cost *= 1 + w["sand"] * v["sand_penalty"] * (1 - np.nan_to_num(firm, nan=0.5)) ** 2
    cost *= 1 + w["rough"] * v["rough_penalty"] * 0.25 * rough_n
    cost[(slope > v["max_slope"]) | np.isnan(slope)] = np.inf
    return cost.astype("float64")


# ------------------------------------------------------------ graphs ----
def _mcp_costs(cost, pixel_m):
    c = np.where(np.isfinite(cost), cost, -1.0)  # negative = impassable for MCP
    return MCP_Geometric(c, sampling=pixel_m, fully_connected=True)


def travel_time_from(cost, seeds, pixel_m):
    """Seconds to reach every pixel from the nearest seed pixel."""
    if not seeds:
        return np.full(cost.shape, np.nan)
    mcp = _mcp_costs(cost, pixel_m)
    t, _ = mcp.find_costs(seeds)
    return t


def best_route(cost, start, goal, pixel_m):
    mcp = _mcp_costs(cost, pixel_m)
    t, _ = mcp.find_costs([start], [goal])
    if not np.isfinite(t[goal]):
        return None, float("inf")
    return mcp.traceback(goal), float(t[goal])


# ------------------------------------------------------- consumables ----
# Round-trip O2 / energy for a planned route is costed in app.consumables_block() with the helpers below.

# ------------------------------------------------- terrain, load, sun ----
MARS_G = 3.711           # m/s2


def minetti_cw(grade):
    """Metabolic cost of walking (J per kg per m) on a signed grade (rise/run), Minetti et al. 2002,
    J Appl Physiol 93:1039. Fitted for -0.45..+0.45, so the grade is clipped to that range."""
    i = np.clip(np.asarray(grade, dtype="float64"), -0.45, 0.45)
    return 280.5 * i**5 - 58.7 * i**4 - 76.8 * i**3 + 51.9 * i**2 + 19.6 * i + 2.5


def walker_slope_slowdown(slope_deg):
    """The share of flat-ground speed speed_kmh() gives a walker on this slope (Tobler, as used there)."""
    s = np.nan_to_num(np.asarray(slope_deg, dtype="float64"), nan=0.0)
    return np.exp(-3.5 * np.abs(np.tan(np.radians(s)) + 0.05)) / math.exp(-3.5 * 0.05)


def route_profile(elevation, path, cost, pixel_m, slope=None):
    """Along-route grades and the time spent on each segment, for terrain-aware consumables.

    elevation: cube band (m). path: list of (row, col) from best_route. cost: s/m grid used to plan it.
    slope: the cube's slope band, so the planner's slope slowdown can be separated from sand and rock.
    Returns per-segment arrays and the climb and descent of the outbound leg."""
    rc = np.asarray(path)
    if len(rc) < 2:
        return None
    rr, cc = rc[:, 0], rc[:, 1]
    dy = np.diff(rr) * pixel_m[0]
    dx = np.diff(cc) * pixel_m[1]
    run = np.maximum(np.hypot(dx, dy), 1e-6)
    z = np.asarray(elevation, dtype="float64")[rr, cc]
    z = np.where(np.isfinite(z), z, np.nanmean(z))
    dz = np.diff(z)
    k = np.asarray(cost, dtype="float64")[rr, cc]
    k = np.where(np.isfinite(k), k, np.nanmax(np.where(np.isfinite(k), k, 0)))
    seg_s = 0.5 * (k[:-1] + k[1:]) * run
    out = {"grade": dz / run, "seg_s": seg_s, "seg_m": run,
           "gain_m": float(dz[dz > 0].sum()), "loss_m": float(-dz[dz < 0].sum())}
    if slope is not None:
        s = np.asarray(slope, dtype="float64")[rr, cc]
        out["slope_deg"] = 0.5 * (s[:-1] + s[1:])
    return out


def round_trip_walk(profile):
    """Oxygen effort of walking the route out and back, against walking the same ground if it were flat.

    The planner's time on each segment already includes a slowdown for slope. That slowdown is taken
    back out, keeping the slowdown for sand and rock, which gives the time the segment would take at
    flat-ground pace. Minetti's cost per metre then charges the climb on the way out and the descent on
    the way back. Minetti measured unsuited people in Earth gravity, so only the ratio to flat ground is
    used, not the absolute energy.

    Returns slope_factor (1.0 = as costly as flat ground) and flat_pace_share (flat-pace time / planner
    time, so oxygen = rate x planner hours x flat_pace_share x slope_factor)."""
    if not profile:
        return {"slope_factor": 1.0, "flat_pace_share": 1.0}
    seg_s = profile["seg_s"]
    slow = walker_slope_slowdown(profile["slope_deg"]) if "slope_deg" in profile else 1.0
    w = seg_s * slow                                   # seconds at flat-ground pace, sand and rock kept
    g = profile["grade"]
    both = (minetti_cw(g) + minetti_cw(-g)) / (2 * minetti_cw(0.0))
    total_w = max(float(np.sum(w)), 1e-9)
    return {"slope_factor": float(np.sum(w * both) / total_w),
            "flat_pace_share": float(total_w / max(float(np.sum(seg_s)), 1e-9))}


def load_factor(carried_kg, body_kg, suit_kg):
    """Walking cost scales with the mass moved: Minetti's cost is per kilogram, so carried tools and
    samples are charged in proportion to body + suit + load."""
    base = max(float(body_kg) + float(suit_kg), 1e-6)
    return (base + max(float(carried_kg), 0.0)) / base


def climb_energy_kwh(mass_kg, climb_m):
    """Energy to lift a vehicle up a climb (m g h). A lower bound: drivetrain losses would add to it."""
    return float(mass_kg) * MARS_G * max(float(climb_m), 0.0) / 3.6e6


def dust_opacity(lat, lon, ls):
    """Daily mean visible dust opacity at the surface from Jason's weather grids (mars_weather),
    looked up the same way surface_temperature.solve_temperature does. None if the data is missing."""
    try:
        from mars_weather import visible_dust_grid
        dust = visible_dust_grid(ls)
    except Exception:
        return None
    ny, nx = dust.shape
    y = float(np.clip((87.5 - lat) / 5, 0, ny - 1))
    x = ((lon + 180) % 360) / 5
    y0, x0 = int(y), int(x) % nx
    y1, x1 = min(y0 + 1, ny - 1), (x0 + 1) % nx
    fy, fx = y - int(y), x - int(x)
    north = dust[y0, x0] * (1 - fx) + dust[y0, x1] * fx
    south = dust[y1, x0] * (1 - fx) + dust[y1, x1] * fx
    return float(north * (1 - fy) + south * fy)


def daily_sunlight_fraction(lat, ls, opacity):
    """Share of a sol's sunlight on a flat panel that gets through the dust.

    Uses the same direct-beam attenuation as the team's temperature model, exp(-tau / cos z),
    integrated over the sol. Diffuse skylight is ignored, so this is the pessimistic end."""
    if opacity is None:
        return None
    hours = np.arange(0.0, 24.0, 0.25)
    mu = np.array([math.sin(math.radians(sun_position(lat, h, ls)[0])) for h in hours])
    up = mu > 0
    if not up.any():
        return 0.0
    clear = mu[up].sum()
    dusty = (mu[up] * np.exp(-opacity / np.maximum(mu[up], 0.05))).sum()
    return float(dusty / clear)


def shelter_seeds(slope, passable, steep_deg=22.0, extra=()):
    """Places to take cover: walkable pixels at the foot of steep walls (+ base/rover)."""
    from scipy.ndimage import binary_dilation
    steep = np.nan_to_num(slope) >= steep_deg
    foot = binary_dilation(steep, iterations=4) & passable & ~steep   # within ~4 px of a wall
    seeds = [tuple(map(int, rc)) for rc in zip(*np.nonzero(foot))]
    return seeds + list(extra)
