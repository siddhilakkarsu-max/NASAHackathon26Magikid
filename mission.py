"""
Mission planner: goal + vehicle + season + priority -> the recommended mission.

  1. settings      the goal is read into target features (search.py: keywords, else the AI model); the vehicle
                   gives slope/range limits; the priority gives the cost-map and decision-matrix weights
  2. tools         equipment for the goal + essentials, total mass and power
  3. destinations  every pixel gets a science score; a safety mask removes Special Regions, slopes beyond the
                   vehicle and very loose ground; the top 3 separated peaks are the B candidates
     landing       for each B the closest safe touchdown spot A: inside a NASA site ("NASA candidate") or any
                   spot passing config.LANDING_RULES ("Tool-found")
  4. routes        cost map from time, energy/oxygen, terrain risk and seasonal dust; green rover tracks get a
                   discount, yellow ones a penalty, off-limits terrain is blocked; lowest-cost route A -> B
     resources     oxygen and/or battery out and back (the return is the route reversed: Minetti slope cost
                   for walkers, m g h climbs for vehicles) incl. tool mass, with a 15-25 % reserve and a
                   turnaround deadline; routes that fail are dropped
  5. decision      each candidate scored 1-5 on config.MATRIX_CRITERIA, weighted by priority -> recommended
  6. explanation   the AI model words the reasons from the numbers (template text without a model)

Route search: Dijkstra on the cost grid (skimage MCP, compiled) - it returns the same lowest-cost route
A* would; A* only explores fewer pixels on the way.
"""
import json
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion, distance_transform_edt
from skimage.draw import line as draw_line

import physics
import search
from config import (CONSUMABLE_RESERVE, ESSENTIALS, LANDING_RULES, MATRIX_CRITERIA, MINERALS, MISSION_VEHICLES,
                    NASA_SITES, PRIORITIES, SEARCH_ZONES, SEASONS, SITE_HOURS, SPECIAL_REGIONS, SUIT, TOOLS,
                    TRACK_RULES, VEHICLE_POWER, WALKER)

ROOT = Path(__file__).parent
LOCAL_HOUR = 11.0            # plan the walk for late morning: sun high, warmest part of the day


# ------------------------------------------------------------------ helpers ----
def _cached(cube, key, make):
    store = cube.__dict__.setdefault("_mission_cache", {})
    if key not in store:
        store[key] = make()
    return store[key]


def _circle_mask(cube, lat, lon, radius_km):
    lat_g = (cube.n - (np.arange(cube.H) + 0.5) * (cube.n - cube.s) / cube.H)[:, None]
    lon_g = (cube.w + (np.arange(cube.W) + 0.5) * (cube.e - cube.w) / cube.W)[None, :]
    dy = (lat_g - lat) * search.DEG_M
    dx = (lon_g - lon) * search.DEG_M * math.cos(math.radians(lat))
    return np.hypot(dx, dy) <= radius_km * 1000


def _disk(r_px):
    y, x = np.mgrid[-r_px:r_px + 1, -r_px:r_px + 1]
    return x * x + y * y <= r_px * r_px


def _ti(cube):
    return cube.bands.get("thermal_inertia")


def _loose(cube):
    """Very loose ground (fine dust / deep sand): thermal inertia < 150, else firmness < 0.1."""
    ti = _ti(cube)
    if ti is not None:
        return np.nan_to_num(ti, nan=300) < 150
    return np.nan_to_num(cube.bands["firmness"], nan=0.5) < 0.1


def special_mask(cube):
    return _cached(cube, "special", lambda: np.logical_or.reduce(
        [np.zeros((cube.H, cube.W), bool)] +
        [_circle_mask(cube, z["lat"], z["lon"], z["radius_km"]) for z in SPECIAL_REGIONS.get(cube.region, [])]))


def matrix_weights(priority):
    p = PRIORITIES[priority]
    w = {k: float(v[1]) for k, v in MATRIX_CRITERIA.items()}
    boost = p["boost"]
    others = sum(v for k, v in w.items() if k != boost)
    for k in w:                                       # +10 to the boosted criterion, others scaled to fit 100
        w[k] = w[k] + 10 if k == boost else w[k] * (others - 10) / others
    return {k: round(v, 1) for k, v in w.items()}


# ------------------------------------------------------------- rover tracks ----
def tracks(cube):
    """Real rover drive segments classed green (no sign of trouble) or yellow (high strain: the rover was
    tilted >= yellow_tilt_deg, or the ground under it is steep or loose). Cached per cube."""
    def make():
        path = ROOT / "cubes" / f"{cube.region}_tracks.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        slope, ti = cube.bands["slope"], _ti(cube)
        green, yellow = np.zeros((cube.H, cube.W), bool), np.zeros((cube.H, cube.W), bool)
        segs = []
        for s in data["segments"]:
            px = []
            for (lon0, lat0), (lon1, lat1) in zip(s["coords"][:-1], s["coords"][1:]):
                try:
                    r0, c0 = cube.rc(lat0, lon0)
                    r1, c1 = cube.rc(lat1, lon1)
                except Exception:                     # leaves the region
                    continue
                rr, cc = draw_line(r0, c0, r1, c1)
                px += list(zip(rr, cc))
            if not px:
                continue
            rr, cc = np.array(px).T
            reasons = []
            if (s.get("tilt_deg") or 0) >= TRACK_RULES["yellow_tilt_deg"]:
                reasons.append(f"rover tilted {s['tilt_deg']:.0f}°")
            smax = float(np.nanmax(slope[rr, cc]))
            if smax >= TRACK_RULES["yellow_slope_deg"]:
                reasons.append(f"slope up to {smax:.0f}°")
            if ti is not None and np.isfinite(ti[rr, cc]).any() and float(np.nanmin(ti[rr, cc])) < TRACK_RULES["yellow_ti"]:
                reasons.append(f"loose ground (thermal inertia {float(np.nanmin(ti[rr, cc])):.0f})")
            cls = "yellow" if reasons else "green"
            (yellow if reasons else green)[rr, cc] = True
            step = max(1, len(s["coords"]) // 25)
            segs.append({"sol": s["sol"], "class": cls, "why": ", ".join(reasons) or "drove without warning signs",
                         "length_m": s["length_m"], "coords": s["coords"][::step] + [s["coords"][-1]]})
        green = binary_dilation(green) & ~binary_dilation(yellow)   # a pixel touched by any yellow drive is yellow
        yellow = binary_dilation(yellow)
        km = {k: round(sum(x["length_m"] for x in segs if x["class"] == k) / 1000, 1) for k in ("green", "yellow")}
        return {"rover": data["rover"], "source": data["source"], "segments": segs, "km": km,
                "green": green, "yellow": yellow}
    return _cached(cube, "tracks", make)


def offlimits(cube, v):
    """Red: terrain beyond the vehicle's limits (too steep or very loose) or a Special Region."""
    return (np.nan_to_num(cube.bands["slope"], nan=90) > v["max_slope"]) | _loose(cube) | special_mask(cube)


# ------------------------------------------------------------------ landing ----
def landing_mask(cube):
    """Pixels where a lander can touch down: config.LANDING_RULES hold over a whole circle around the spot."""
    def make():
        R = LANDING_RULES
        b = cube.bands
        rough = b["roughness"]
        ok = (np.nan_to_num(b["slope"], nan=90) <= R["max_slope_deg"])
        ok &= np.nan_to_num(rough, nan=1e9) <= np.nanpercentile(rough, R["max_rough_percentile"])
        ti = _ti(cube)
        ok &= (np.nan_to_num(ti, nan=0) >= R["min_ti"]) if ti is not None else (np.nan_to_num(b["firmness"]) >= 0.35)
        ok &= np.nan_to_num(b["elevation"], nan=1e9) <= R["max_elevation_m"]
        lat = (cube.n - (np.arange(cube.H) + 0.5) * (cube.n - cube.s) / cube.H)[:, None]
        ok &= np.abs(lat) <= R["max_abs_lat"]
        ok &= ~special_mask(cube)
        r_px = max(1, int(round(R["area_radius_m"] / min(cube.pixel_m))))
        return binary_erosion(ok, structure=_disk(r_px), border_value=0)
    return _cached(cube, "landing", make)


def nasa_sites(cube):
    """(mask of NASA landing sites / ellipses, list of exploration zones covering the region)."""
    def make():
        mask = np.zeros((cube.H, cube.W), bool)
        owner = np.full((cube.H, cube.W), -1, int)
        sites = NASA_SITES.get(cube.region, [])
        for i, s in enumerate(sites):
            if "radius_km" in s:
                m = _circle_mask(cube, s["lat"], s["lon"], s["radius_km"])
                owner[m & (owner < 0)] = i            # smallest/first listed site wins (landing site before ellipse)
                mask |= m
        zones = [s for s in sites if s.get("kind") == "exploration zone"]
        return mask, owner, zones
    return _cached(cube, "nasa", make)


def nearest_landing(cube, b_rc):
    """Closest safe touchdown spot to B. A NASA site wins if it is not much farther than the closest spot."""
    def make():
        safe = landing_mask(cube)
        nasa, owner, _ = nasa_sites(cube)
        out = {}
        for key, m in (("any", safe), ("nasa", safe & nasa)):
            if m.any():
                d, idx = distance_transform_edt(~m, sampling=cube.pixel_m, return_indices=True)
                out[key] = (d, idx)
        return out
    edts = _cached(cube, "landing_edt", make)
    if "any" not in edts:
        return None
    r, c = b_rc
    d_any, idx = edts["any"]
    best = dict(rc=(int(idx[0][r, c]), int(idx[1][r, c])), dist_m=float(d_any[r, c]), kind="Tool-found", site=None)
    if "nasa" in edts:
        d_n, idx_n = edts["nasa"]
        if d_n[r, c] <= 1.5 * d_any[r, c] + 500:
            rc = (int(idx_n[0][r, c]), int(idx_n[1][r, c]))
            _, owner, _ = nasa_sites(cube)
            site = NASA_SITES[cube.region][owner[rc]]
            best = dict(rc=rc, dist_m=float(d_n[r, c]), kind="NASA candidate", site=site["name"])
    return best


# ------------------------------------------------------------- per mission ----
def tool_list(criteria, vehicle_key):
    feats = {c["feature"] for c in criteria if not c["negate"]}
    items = []
    for t in TOOLS:
        hit = sorted(feats & set(t["for_"]))
        if hit or "*" in t["for_"]:
            items.append(dict(name=t["name"], kg=t["kg"], w=t["w"],
                              why="for " + ", ".join(search.FEATURES[f]["label"] for f in hit) if hit else "every mission"))
    for e in ESSENTIALS:
        items.append(dict(name=e["name"], kg=e["kg"], w=e["w"], why="essential"))
    return dict(items=items, kg=round(sum(i["kg"] for i in items), 1), w=sum(i["w"] for i in items),
                site_wh=round(sum(i["w"] for i in items) * SITE_HOURS))


def _route_layers(cube, v, season, priority, green_only):
    """Per-pixel time (s/m), energy or oxygen per metre, terrain risk and the weighted route cost."""
    b = cube.bands
    slope = np.nan_to_num(b["slope"], nan=90.0)
    firm = np.nan_to_num(b["firmness"], nan=0.5)
    rough = b["roughness"]
    rough_n = np.clip(np.nan_to_num(rough / max(np.nanpercentile(rough, 95), 1e-6)), 0, 2)
    time = physics.cost_seconds_per_meter(b, v)                     # s/m, inf beyond the slope limit
    speed = 1.0 / np.where(np.isfinite(time), time, np.inf)         # m/s
    if v["battery_wh"]:
        energy = v["wh_per_km"] / 1000 * (1 + 0.05 * slope) * (1 + 0.5 * v["sand_penalty"] * (1 - firm) ** 2)
    else:                                                            # on foot: oxygen per metre walked
        energy = SUIT["o2_walk_kg_h"] / 3600 * (1 + 0.04 * slope) / np.maximum(speed, 1e-3)
    risk = (slope / v["max_slope"]) ** 2 + (1 - firm) ** 2 + 0.3 * rough_n
    w = PRIORITIES[priority]["cost"]
    finite = np.isfinite(time)
    t_med, e_med = np.median(time[finite]), np.median(energy[finite])
    cost = (w["time"] * time / t_med + w["energy"] * energy / e_med + w["risk"] * (1 + 3 * risk)) / sum(w.values())
    cost *= 1 + SEASONS[season]["dust_risk"] * (1 - firm)           # dusty ground is worse in storm season
    tr = tracks(cube)
    if tr is not None:
        g, y = TRACK_RULES["green_factor"], TRACK_RULES["yellow_factor"]
        if green_only:
            cost *= np.where(tr["green"], 1.0, 3.0)                  # stick to the green network
            g = 0.3
        cost = np.where(tr["green"], cost * g, np.where(tr["yellow"], cost * y, cost))
    red = offlimits(cube, v)
    cost = np.where(red | ~finite, np.inf, cost)
    return dict(time=time, energy=energy, risk=risk, cost=cost, red=red)


MODEL_SOURCE = ("Walking oxygen: flat-ground pace x Minetti et al. 2002 (J Appl Physiol 93:1039) slope cost ratio, "
                "x carried load (body + suit + tools); the return leg is the route reversed, so climbs out are "
                "descents back. Vehicles: drive energy plus m g h for every climb on each leg (a lower bound). "
                "Same model as the gear page (physics.path_resources).")
# MISSION_VEHICLES -> config.VEHICLE_POWER entry, where one describes the same kind of vehicle. Only the
# pressurized buggy has a counterpart (the crew rover, battery recharged 2:1 from sunlight); the scout bike and
# the open rover have no published power source here, so no recharge time is given for them.
POWER_MAP = {"buggy": "pressurized_rover"}


def _reserve(priority, season):
    """The priority's reserve (+5 % in dusty seasons), never below the team's contingency rule
    (config.CONSUMABLE_RESERVE: 15 %, 20 % in the dust-storm season Ls 180-330)."""
    ls = SEASONS[season]["ls"] % 360
    lo, hi = CONSUMABLE_RESERVE["dust_season_ls"]
    floor = CONSUMABLE_RESERVE["dust_season" if lo <= ls <= hi else "normal"]
    return max(PRIORITIES[priority]["reserve"] + (0.05 if SEASONS[season]["dust_risk"] >= 0.3 else 0.0), floor)


def _sunlight(cube, season):
    """Dust opacity at the region this season and the share of direct sunlight it lets through (cached)."""
    def make():
        lat, lon, ls = (cube.s + cube.n) / 2, (cube.w + cube.e) / 2, SEASONS[season]["ls"]
        tau = physics.dust_opacity(lat, lon, ls)
        return tau, physics.daily_sunlight_fraction(lat, ls, tau)
    return _cached(cube, ("sunlight", season), make)


def _turn_h(r, step_h, out_h):
    """Latest time after leaving A to turn back: the furthest point k where the cost out to k plus the cost
    of walking/driving back from k (the reversed path) plus the site work still fits in the usable supply.
    Beyond B it is extended at the round trip's average burn per outbound hour (the old formula's meaning)."""
    cum_c = np.concatenate([[0.0], np.cumsum(r["step"])])
    cum_t = np.concatenate([[0.0], np.cumsum(step_h)])
    budget = r["usable"] - r["site"]
    if budget >= cum_c[-1]:
        return out_h + (budget - cum_c[-1]) * out_h / max(cum_c[-1], 1e-12)
    return float(np.interp(budget, cum_c, cum_t)) if budget > 0 else 0.0


def _resources(cube, vehicle, v, tools, seg_len, rr, cc, L, priority, season):
    """Round-trip oxygen and/or battery use, reserve, and the turnaround deadline. The way out and the way back
    are costed separately (physics.path_resources): the return leg is the outbound route reversed."""
    n = len(rr) - 1
    run = seg_len[:n]
    a, b_ = rr[:n], cc[:n]                                          # the pixel each step leaves from
    step_h = run * L["time"][a, b_] / 3600
    out_time_h = float(step_h.sum())
    rt_h = 2 * out_time_h + SITE_HOURS
    reserve = _reserve(priority, season)
    z = cube.bands["elevation"][rr, cc]
    res = []
    # O2 or Wh per metre, the same in both directions; slope and climbs are added by path_resources
    o2_per_m = (SUIT["o2_ride_kg_h"] if v["battery_wh"] else SUIT["o2_walk_kg_h"]) / 3600 * L["time"][a, b_]
    if v["suited"]:
        if v["battery_wh"]:                                         # riding: suit O2 by the hour
            P = physics.path_resources(z, run, o2_per_m)
            extra = {}
        else:                                                       # walking: Minetti x carried load
            load = physics.load_factor(tools["kg"], WALKER["body_kg"], WALKER["suit_kg"])
            P = physics.path_resources(z, run, o2_per_m * load, walker=True,
                                       slope_deg=np.nan_to_num(cube.bands["slope"][a, b_], nan=0.0))
            extra = dict(slope_factor=round(P["slope_factor"], 3), slope_factor_out=round(P["slope_factor_out"], 3),
                         slope_factor_back=round(P["slope_factor_back"], 3), load_factor=round(load, 3))
        res.append(dict(name="oxygen", unit="kg", cap=SUIT["o2_kg"], out=P["out"], back=P["back"],
                        site=SITE_HOURS * SUIT["o2_site_kg_h"], step=P["step_out"] + P["step_back"],
                        source=SUIT["source"], extra=extra))
    if v["battery_wh"]:
        load = 1 + tools["kg"] / v["mass_kg"]                      # tools add to the vehicle's mass
        wh_per_m = L["energy"][a, b_] * load + v["hotel_w"] * L["time"][a, b_] / 3600
        P = physics.path_resources(z, run, wh_per_m, mass_kg=v["mass_kg"] + tools["kg"])
        extra = dict(climb_wh=round(P["climb_wh_out"] + P["climb_wh_back"], 1),
                     climb_wh_out=round(P["climb_wh_out"], 1), climb_wh_back=round(P["climb_wh_back"], 1))
        power = VEHICLE_POWER.get(POWER_MAP.get(vehicle, ""), {})
        tau, frac = _sunlight(cube, season)
        extra.update(power_source=power.get("source"), dust_opacity=None if tau is None else round(tau, 2),
                     sunlight_pct=None if frac is None else int(round(100 * frac)), recharge_h=None)
        if power.get("source") == "battery" and power.get("recharge_ratio") and frac and frac > 1e-6:
            extra["recharge_h"] = round(power["recharge_ratio"] * 2 * out_time_h / frac, 1)
        res.append(dict(name="battery", unit="Wh", cap=v["battery_wh"],
                        out=P["out"] + P["climb_wh_out"], back=P["back"] + P["climb_wh_back"],
                        site=tools["site_wh"] + SITE_HOURS * v["hotel_w"],
                        step=P["step_out"] + P["step_back"] + P["climb_out_wh"] + P["climb_back_wh"], extra=extra))
    for r in res:
        r["used"] = r["out"] + r["back"] + r["site"]
        r["usable"] = r["cap"] * (1 - reserve)
        r["left"] = 1 - r["used"] / r["cap"]
        r["ok"] = r["used"] <= r["usable"]
        r["turn_h"] = _turn_h(r, step_h, out_time_h)
    binding = max(res, key=lambda r: r["used"] / r["usable"])
    return dict(out_h=out_time_h, rt_h=rt_h, reserve=reserve, items=res, binding=binding,
                ok=all(r["ok"] for r in res), turn_h=min(r["turn_h"] for r in res),
                gain_m=P["gain_m"], loss_m=P["loss_m"])


def _score(x, steps):
    """1-5 from thresholds (ascending)."""
    return 1 + sum(x >= s for s in steps)


def read_goal(goal):
    """Goal text -> (spec, parser, notes): keywords first, the AI model only for words they don't cover."""
    spec, parser, notes = search.keyword_parse(goal), "keywords", []
    if spec["unknown"] or not spec["criteria"]:
        llm, why = search.ai_parse(goal)
        if llm and llm["criteria"]:
            spec, parser = llm, "ai"
        elif why:
            notes.append(why)
    return spec, parser, notes


def plan(cube, goal, vehicle="on_foot", season="northern_summer", priority="safety", green_only=False,
         goal_spec=None):
    """goal_spec: (spec, parser, notes) when the goal was already read (e.g. streamed); else read_goal(goal)."""
    v = MISSION_VEHICLES[vehicle]

    # 1-2. settings and tools ------------------------------------------------------------------
    spec, parser, notes = goal_spec or read_goal(goal)
    notes = list(notes)
    criteria = [c for c in spec["criteria"] if c["feature"] != "near_base"]   # the start A is chosen later
    if not criteria:
        raise ValueError(f"Couldn't find a target in '{goal}'. Try e.g. 'clay', 'carbonate in a valley', "
                         "'water-bearing minerals on firm ground'.")
    weights = matrix_weights(priority)
    tools = tool_list(criteria, vehicle)

    ls = SEASONS[season]["ls"]
    sun_e, sun_az = physics.sun_position((cube.s + cube.n) / 2, LOCAL_HOUR, ls)
    illum = physics.illumination(cube.bands["slope"], cube.bands["aspect"], sun_e, sun_az)
    temp = physics.surface_temp_k(illum, cube.bands.get("firmness"), sun_e)
    L = _route_layers(cube, v, season, priority, green_only)

    # 3. destinations ----------------------------------------------------------------------------
    ctx = search.Ctx(cube, v, sun_e, illum, temp, L["time"], zones=SEARCH_ZONES.get(cube.region, []))
    score, parts = search.score_map(ctx, criteria)
    notes += ctx.notes
    if score is None:
        raise ValueError("None of the goal's features can be mapped here. " + " ".join(notes))
    safe = ~L["red"] & np.isfinite(L["time"])
    safe[:2, :] = safe[-2:, :] = safe[:, :2] = safe[:, -2:] = False
    nearest_landing(cube, (0, 0))                                   # builds the distance-to-landing maps
    edts = _cached(cube, "landing_edt", dict)
    if "any" not in edts:
        raise ValueError("No spot in this region passes the landing rules.")
    reach = edts["any"][0] <= 0.8 * v["range_km"] * 1000            # routes run ~25 % longer than straight
    if not (safe & reach & (score > 0.05)).any():
        raise ValueError(f"Nothing matching the goal lies within {v['range_km']:.0f} km of a safe landing spot "
                         f"for {v['label'].lower()}. Try a vehicle with more range.")
    safe &= reach
    peaks = search.pick_peaks(score, safe, cube.pixel_m, 3, sep_m=3000)
    if not peaks:
        raise ValueError("No safe place matches the goal for this vehicle.")

    tr = tracks(cube)
    candidates, dropped = [], []
    _, _, zones = nasa_sites(cube)
    for n, (br, bc, bscore) in enumerate(peaks, 1):
        blat, blon = cube.latlon(br, bc)
        cand = dict(id=n, B=dict(lat=round(blat, 5), lon=round(blon, 5)), science=round(bscore, 2))
        a = nearest_landing(cube, (br, bc))
        if a is None:
            dropped.append(dict(cand, reason="no safe landing spot in this region")); continue
        alat, alon = cube.latlon(*a["rc"])
        cand["A"] = dict(lat=round(alat, 5), lon=round(alon, 5), kind=a["kind"], site=a["site"],
                         dist_km=round(a["dist_m"] / 1000, 2))

        # 4. route + resources ---------------------------------------------------------------------
        path, _ = physics.best_route(L["cost"], a["rc"], (br, bc), cube.pixel_m)
        if path is None:
            dropped.append(dict(cand, reason="no route within the vehicle's limits")); continue
        rr, cc = np.array(path).T
        steps = np.hypot(np.diff(rr) * cube.pixel_m[0], np.diff(cc) * cube.pixel_m[1])
        seg_len = np.append(steps, 0.0)                             # length of the step leaving each pixel
        dist_km = float(steps.sum() / 1000)
        R = _resources(cube, vehicle, v, tools, seg_len, rr, cc, L, priority, season)
        slope = cube.bands["slope"][rr, cc]
        ti = _ti(cube)
        loose = (np.nan_to_num(ti[rr, cc], nan=300) < 200) if ti is not None else \
            (np.nan_to_num(cube.bands["firmness"][rr, cc], nan=0.5) < 0.25)
        on_green = tr["green"][rr, cc] if tr else np.zeros(len(rr), bool)
        on_yellow = tr["yellow"][rr, cc] if tr else np.zeros(len(rr), bool)
        frac = lambda m: float(np.sum(seg_len * m) / max(steps.sum(), 1e-9))
        risk = np.where(slope > 0.85 * v["max_slope"], 2, np.where((slope > 0.6 * v["max_slope"]) | loose, 1, 0))
        k = max(1, len(rr) // 400)
        pts = [dict(lat=round(la, 5), lon=round(lo, 5), risk=int(risk[i]), green=bool(on_green[i]))
               for i in list(range(0, len(rr), k)) + [len(rr) - 1] for la, lo in [cube.latlon(rr[i], cc[i])]]
        # turnaround point: where the deadline falls along the outbound route (B if it comes later)
        t_cum = np.cumsum(seg_len * L["time"][rr, cc]) / 3600
        ti_turn = int(min(np.searchsorted(t_cum, R["turn_h"]), len(rr) - 1))
        tlat, tlon = cube.latlon(rr[ti_turn], cc[ti_turn])
        cand["route"] = dict(points=pts, distance_km=round(dist_km, 2), one_way_h=round(R["out_h"], 2),
                             round_trip_h=round(R["rt_h"], 2), max_slope=round(float(np.nanmax(slope)), 1),
                             mean_slope=round(float(np.nanmean(slope)), 1), loose_pct=round(100 * frac(loose)),
                             green_pct=round(100 * frac(on_green)), green_km=round(float(np.sum(seg_len * on_green)) / 1000, 2),
                             yellow_pct=round(100 * frac(on_yellow)))
        cand["resources"] = dict(
            reserve_pct=round(100 * R["reserve"]), binding=R["binding"]["name"], ok=R["ok"],
            items=[dict(name=r["name"], unit=r["unit"], capacity=round(r["cap"], 2), used=round(r["used"], 2),
                        left_pct=round(100 * r["left"]), ok=r["ok"], source=r.get("source", ""),
                        out=round(r["out"], 3), back=round(r["back"], 3), site=round(r["site"], 3),
                        usable=round(r["usable"], 2), **r["extra"]) for r in R["items"]],
            turnaround=dict(h=round(R["turn_h"], 2), lat=round(tlat, 5), lon=round(tlon, 5),
                            at_B=bool(R["turn_h"] >= R["out_h"])),
            elevation_gain_m=round(R["gain_m"]), elevation_loss_m=round(R["loss_m"]),
            reserve_rule="priority reserve (+5% in dusty seasons), at least 15% / 20% in the dust-storm season",
            model="minetti", model_source=MODEL_SOURCE)
        if dist_km > v["range_km"]:
            dropped.append(dict(cand, reason=f"route {dist_km:.1f} km is beyond the {v['range_km']:.0f} km range")); continue
        if not R["ok"]:
            b_ = R["binding"]
            dropped.append(dict(cand, reason=f"round trip needs {b_['used']:.2f} {b_['unit']} {b_['name']} but only "
                                             f"{b_['usable']:.2f} is usable after the {100 * R['reserve']:.0f}% reserve"))
            continue
        cand["card"] = _card(cube, (br, bc), parts, criteria, score, cand, zones, sun_e, illum, temp, season, v)
        cand["_R"] = R
        candidates.append(cand)

    # 5. decision matrix --------------------------------------------------------------------------
    if candidates:
        best_rt = min(c["route"]["round_trip_h"] for c in candidates)
        for c in candidates:
            c["scores"] = _matrix_scores(c, v, best_rt)
            c["total"] = round(sum(weights[k] * s / 5 for k, s in c["scores"].items()), 1)
            del c["_R"]
        candidates.sort(key=lambda c: -c["total"])
        for rank, c in enumerate(candidates, 1):
            c["rank"] = rank

    result = dict(
        settings=dict(goal=goal, parser=parser, model=spec.get("model"), targets=[search.describe(c) for c in criteria],
                      not_understood=spec["unknown"], vehicle=dict(key=vehicle, label=v["label"], max_slope=v["max_slope"],
                      range_km=v["range_km"]), season=dict(key=season, **SEASONS[season]),
                      priority=dict(key=priority, label=PRIORITIES[priority]["label"], cost=PRIORITIES[priority]["cost"]),
                      weights=weights, criteria={k: v_[0] for k, v_ in MATRIX_CRITERIA.items()}, green_only=green_only,
                      sun_elevation=round(sun_e, 1), local_hour=LOCAL_HOUR),
        tools=tools, candidates=candidates, dropped=dropped, notes=notes,
        tracks=dict(rover=tr["rover"], km=tr["km"]) if tr else None, rect=cube.rect)
    result["explanation"], result["explanation_source"] = _template(result), "template"
    result["_score"], result["_red"] = score, L["red"]
    return result


def _card(cube, b_rc, parts, criteria, score, cand, zones, sun_e, illum, temp, season, v):
    r, c = b_rc
    b = cube.bands
    targets = [f"{search.describe(cr)}: {explain(r, c)}" for cr, explain in parts]
    src = b.get("crism_source")
    minerals_wanted = any(cr["feature"] in MINERALS or cr["feature"] == "any_mineral" for cr in criteria)
    if src is not None and np.isfinite(src[r, c]):
        conf = "high: CRISM targeted observation (18-36 m)" if src[r, c] == 1 else "medium: CRISM map tile (~180 m)"
    elif minerals_wanted:
        conf = "low: no CRISM data here (approximate zone only)"
    else:
        conf = "high: CTX elevation (20 m) + THEMIS thermal inertia (1 km)"
    nearby = []
    rad = max(1, int(2000 / min(cube.pixel_m)))
    win = (slice(max(0, r - rad), r + rad + 1), slice(max(0, c - rad), c + rad + 1))
    for name in ("hydrated", "clay", "carbonate"):
        if name in b and not any(cr["feature"] == name for cr in criteria):
            m = np.nan_to_num(b[name][win], nan=-1) >= MINERALS[name]["detect"]
            if m.any():
                nearby.append(f"{MINERALS[name]['label']} within 2 km")
    wall = np.nan_to_num(b["slope"][win], nan=0) >= v["max_slope"] + 2
    if wall.any():
        ys, xs = np.nonzero(wall)
        d = np.min(np.hypot((ys + win[0].start - r) * cube.pixel_m[0], (xs + win[1].start - c) * cube.pixel_m[1]))
        nearby.append(f"shelter at the foot of a wall {d:.0f} m away")
    # sampling spots: the 3 best-scoring pixels for the whole goal within 500 m of B
    rad5 = max(1, int(500 / min(cube.pixel_m)))
    r0, c0 = max(0, r - rad5), max(0, c - rad5)
    sub = np.nan_to_num(score[r0:r + rad5 + 1, c0:c + rad5 + 1], nan=0)
    spots = []
    for flat in np.argsort(sub, axis=None)[::-1][:3]:
        yy, xx = np.unravel_index(flat, sub.shape)
        la, lo = cube.latlon(r0 + yy, c0 + xx)
        spots.append(dict(lat=round(la, 5), lon=round(lo, 5), score=round(float(sub[yy, xx]), 2),
                          what=parts[0][1](r0 + yy, c0 + xx)))
    inside = [z["name"] for z in zones if z["bounds"][0] <= cand["B"]["lon"] <= z["bounds"][2]
              and z["bounds"][1] <= cand["B"]["lat"] <= z["bounds"][3]]
    return dict(
        target=targets, confidence=conf,
        terrain=[f"slope {b['slope'][r, c]:.1f}°, roughness {b['roughness'][r, c]:.1f} m, elevation {b['elevation'][r, c]:.0f} m",
                 search.ground_text(cube, r, c)],
        conditions=[f"{SEASONS[season]['label']}, dust risk {SEASONS[season]['dust_risk']:.0%}",
                    f"at {LOCAL_HOUR:.0f}:00 local: sun {sun_e:.0f}° up, sunlight cos(i) {max(float(illum[r, c]), 0):.2f}, "
                    f"surface ~{temp[r, c]:.0f} K (approx.)"],
        nearby=nearby or ["nothing else notable within 2 km"], sampling=spots,
        protection=["inside a COSPAR Special Region: off-limits" if special_mask(cube)[r, c]
                    else "not in a known COSPAR Special Region"] + [f"inside the {z}" for z in inside],
        from_A=cand["A"]["kind"] + (f": {cand['A']['site']}" if cand["A"]["site"] else "")
               + f"; {cand['A']['dist_km']:.1f} km from B in a straight line")


def _matrix_scores(c, v, best_rt):
    r, res = c["route"], c["resources"]
    safety = 5
    safety -= 2 if r["max_slope"] > 0.8 * v["max_slope"] else 1 if r["max_slope"] > 0.6 * v["max_slope"] else 0
    safety -= 2 if r["loose_pct"] > 50 else 1 if r["loose_pct"] > 25 else 0
    safety -= 1 if r["yellow_pct"] > 25 else 0
    left = min(i["left_pct"] for i in res["items"]) / 100
    landing = (4 if c["A"]["kind"] == "NASA candidate" else 3) + (1 if c["A"]["dist_km"] <= 1 else 0) \
        - (1 if c["A"]["dist_km"] > 0.8 * v["range_km"] else 0)
    conf = c["card"]["confidence"]
    return dict(
        science=round(1 + 4 * c["science"], 1),
        safety=max(1, safety),
        resources=_score(left, [0.2, 0.3, 0.45, 0.6]),
        green=_score(r["green_pct"] / 100, [0.1, 0.3, 0.5, 0.7]),
        time=round(max(1.0, min(5.0, 1 + 4 * best_rt / max(r["round_trip_h"], 1e-6))), 1),
        landing=max(1, min(5, landing)),
        confidence=5 if conf.startswith("high") else 3 if conf.startswith("medium") else 1,
    )


# -------------------------------------------------------------- explanation ----
def _template(res):
    cands = res["candidates"]
    if not cands:
        return "No candidate passed the safety and resource checks. " + \
            " ".join(f"#{d['id']}: {d['reason']}." for d in res["dropped"])
    w, s = cands[0], res["settings"]
    r, R = w["route"], w["resources"]
    bind = next(i for i in R["items"] if i["name"] == R["binding"])
    txt = (f"Route #1 wins with {w['total']}/100: its destination has {w['card']['target'][0]}, "
           f"{r['distance_km']:.1f} km by route from its {'NASA-candidate' if w['A']['kind'] == 'NASA candidate' else 'tool-found'} "
           f"landing spot; it ")
    if res["tracks"] and r["green_km"] > 0:
        txt += f"follows {r['green_km']:.1f} km of {res['tracks']['rover']}'s green track ({r['green_pct']}% of the route), "
    txt += f"stays under {math.ceil(r['max_slope'])}° slope and leaves {bind['left_pct']}% of its {bind['name']}"
    if len(cands) > 1:
        o = cands[1]
        ob = next(i for i in o["resources"]["items"] if i["name"] == bind["name"])
        diff = 100 * (ob["used"] - bind["used"]) / max(ob["used"], 1e-9)
        txt += (f"; it uses about the same {bind['name']} as route #2" if abs(diff) < 1 else
                f"; it uses {abs(diff):.0f}% {'less' if diff > 0 else 'more'} {bind['name']} than route #2")
        top = max(w["scores"], key=lambda k: res["settings"]["weights"][k] * (w["scores"][k] - o["scores"][k]))
        lab = res['settings']['criteria'][top]
        txt += f", and its biggest edge over #2 is {lab[0].lower() + lab[1:]}"
    return txt + "."


def explain_facts(res):
    """The few numbers the AI model needs to word the explanation (small prompt = fast answer)."""
    def row(c):
        bind = next(i for i in c["resources"]["items"] if i["name"] == c["resources"]["binding"])
        r = c["route"]
        return {"rank": c["rank"], "total": c["total"], "scores": c["scores"], "target_at_B": c["card"]["target"][0],
                "landing": c["A"]["kind"], "route_km": r["distance_km"], "round_trip_h": r["round_trip_h"],
                "max_slope_deg": r["max_slope"], "green_track_pct": r["green_pct"], "green_track_km": r["green_km"],
                f"{bind['name']}_used": bind["used"], f"{bind['name']}_left_pct": bind["left_pct"]}
    s = res["settings"]
    return {"goal": s["goal"], "vehicle": s["vehicle"]["label"], "priority": s["priority"]["label"],
            "weights_pct": s["weights"], "candidates": [row(c) for c in res["candidates"]],
            "dropped": [f"B{d['id']}: {d['reason']}" for d in res["dropped"]],
            "rover": (res["tracks"] or {}).get("rover"), "summary": res["explanation"]}


EXPLAIN_SYSTEM = (
    "You explain a Mars traverse plan to an astronaut in 2-3 plain sentences. Rewrite the 'summary' more "
    "naturally and keep its numbers; you may add one more comparison from the candidates table. Routes #2 and "
    "#3 are backups, not dropped; only entries under 'dropped' were dropped. Use only numbers given. "
    "No lists, no markdown.")


def explain_ai(facts):
    """The AI model rewrites the template summary (no streaming, no thinking); None if no model is available."""
    if not facts["candidates"]:
        return None
    return search.ai_write(EXPLAIN_SYSTEM, json.dumps(facts), max_tokens=300)


def explain_stream(facts):
    """The same, streamed with the model's thinking: search.ai_stream events."""
    yield from search.ai_stream([{"role": "system", "content": EXPLAIN_SYSTEM},
                                 {"role": "user", "content": json.dumps(facts)}], max_tokens=4000)
