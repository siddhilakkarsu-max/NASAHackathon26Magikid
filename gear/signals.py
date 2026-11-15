"""
Read the planner: run a route and summarise the ground along it.

app.py is imported lazily inside the functions so this package can be imported (and tested) without
starting the web app, and so there is no import cycle when app.py later includes the gear router.
"""
import numpy as np

import physics

from .context import RouteRequest, RouteStats, TerrainSignals

LOOSE_FIRMNESS = 0.3  # same cut-off app.py uses for "loose sand/dust - slip risk"
TI_DUST = 150.0       # thermal inertia classes, same cut-offs as search.ti_class()
TI_SAND = 300.0


def run_route(req: RouteRequest):
    """Plan the route with the existing planner and return (RouteStats | None, TerrainSignals | None, plan dict)."""
    import app as planner

    plan_req = planner.PlanRequest(
        region=req.region, vehicle=req.vehicle, local_hour=req.local_hour, ls=req.ls,
        budget_hours=req.budget_hours, reserve=req.reserve,
        base=planner.Point(lat=req.base.lat, lon=req.base.lon),
        target=planner.Point(lat=req.target.lat, lon=req.target.lon))
    plan = planner.plan(plan_req)
    stats = plan.get("stats")
    if not stats or not plan.get("route"):
        return None, None, plan
    route = RouteStats(**{k: stats.get(k) for k in RouteStats.model_fields})
    terrain = terrain_along(req, plan["route"])
    return route, terrain, plan


def terrain_along(req: RouteRequest, route_points):
    import app as planner

    cube = planner.get_cube(req.region)
    cond = planner.Conditions(region=req.region, vehicle=req.vehicle, local_hour=req.local_hour, ls=req.ls,
                              budget_hours=req.budget_hours, reserve=req.reserve)
    _v, sun_e, _az, illum, _cost = planner.conditions_layers(cube, cond)
    temp = physics.surface_temp_k(illum, cube.bands.get("firmness"), sun_e)

    rr, cc = [], []
    for p in route_points:
        try:
            r, c = cube.rc(p["lat"], p["lon"])
        except Exception:
            continue
        rr.append(r)
        cc.append(c)
    if not rr:
        return None
    rr, cc = np.array(rr), np.array(cc)

    def stat(a, fn):
        v = a[rr, cc]
        v = v[np.isfinite(v)]
        return float(fn(v)) if v.size else None

    slope = cube.bands["slope"]
    firm = cube.bands.get("firmness")
    rough = cube.bands.get("roughness")
    out = TerrainSignals(
        max_slope_deg=stat(slope, np.max), p90_slope_deg=stat(slope, lambda v: np.percentile(v, 90)),
        mean_slope_deg=stat(slope, np.mean), sun_elevation_deg=float(sun_e), local_hour=req.local_hour,
        surface_temp_min_k=stat(temp, np.min), surface_temp_mean_k=stat(temp, np.mean), samples=int(len(rr)))
    if firm is not None:
        f = firm[rr, cc]
        f = f[np.isfinite(f)]
        if f.size:
            out.mean_firmness = float(f.mean())
            out.min_firmness = float(f.min())
            out.loose_fraction = float((f < LOOSE_FIRMNESS).mean())
    ti = cube.bands.get("thermal_inertia")
    if ti is not None:
        t = ti[rr, cc]
        t = t[np.isfinite(t)]
        out.ti_samples = int(t.size)
        if t.size:
            out.ti_mean = float(t.mean())
            out.ti_min = float(t.min())
            out.dust_fraction = float((t < TI_DUST).mean())
            out.sand_fraction = float(((t >= TI_DUST) & (t < TI_SAND)).mean())
            out.ti_loose_fraction = float((t < TI_SAND).mean())
    if rough is not None:
        p95 = float(np.nanpercentile(rough, 95))
        peak = stat(rough, np.max)
        if peak is not None and p95 > 1e-9:
            out.roughness_ratio = peak / p95
    return out
