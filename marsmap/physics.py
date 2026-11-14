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


def shelter_seeds(slope, passable, steep_deg=22.0, extra=()):
    """Places to take cover: walkable pixels at the foot of steep walls (+ base/rover)."""
    from scipy.ndimage import binary_dilation
    steep = np.nan_to_num(slope) >= steep_deg
    foot = binary_dilation(steep, iterations=4) & passable & ~steep   # within ~4 px of a wall
    seeds = [tuple(map(int, rc)) for rc in zip(*np.nonzero(foot))]
    return seeds + list(extra)
