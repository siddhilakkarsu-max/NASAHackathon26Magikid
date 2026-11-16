"""Route comparison attached to the existing planner and survival game.

The planner captures its own result and measured cube. Browser geometry is
evaluated against that immutable snapshot. AI driving ticks are reported by the
browser simulator, not recomputed by Python; rankings are not cheat-proof.
This module has no independent mission generator, home screen or demo terrain.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import math
import secrets
import sqlite3
import threading
import time
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import leaderboard as players
import mission as planner
import physics
from config import MARS_RADIUS_M, MISSION_VEHICLES, SITE_HOURS, region_box

router = APIRouter(prefix="/api/game", tags=["game routes"])
MODEL_VERSION = "planner-route-comparison-v3-ai-driving"
BENCHMARK_VERSION = "fixed-step-drive-v1"
MAX_POINTS = 5000
MAX_DRIVE_M_S = 60.0  # Above the game's 45 m/s presentation cap, including storm drift.
MAX_HEARTBEAT_GAP_S = 4.0
POSITION_ROUNDOFF_M = .001
CORRIDOR_M = 1000.0  # Existing science/shelter excursions remain available.
# One sample marker at B: 9m interaction plus a half-second movement heartbeat.
# This is a gameplay-position tolerance, not the source's map resolution.
SCIENCE_RADIUS_M = 35.0
_lock = threading.RLock()
_conn = _path = None
_terrain_cache = {}


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _json(value):
    return json.dumps(_clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _db():
    global _conn, _path
    path = players.state_dir() / "game_routes.sqlite3"
    if _conn is None or _path != path:
        if _conn is not None:
            _conn.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
          CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
            terrain TEXT, model TEXT NOT NULL, error TEXT, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS terrain(id TEXT PRIMARY KEY, metadata TEXT NOT NULL, arrays BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, name_lc TEXT NOT NULL, name TEXT NOT NULL,
            plan_id TEXT NOT NULL, candidate INTEGER NOT NULL, mission_key TEXT NOT NULL,
            idempotency_key TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
            UNIQUE(name_lc,idempotency_key));
          CREATE INDEX IF NOT EXISTS attempts_key ON attempts(mission_key,name_lc);
          CREATE TABLE IF NOT EXISTS route_guests(name TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL, created REAL NOT NULL);
        """)
        _path = path
        _terrain_cache.clear()
    return _conn


@contextmanager
def _write():
    with _lock:
        db = _db()
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()


def capture_plan(result, cube):
    """Called by app._finish_mission; keep the planner's original ID and route.

    Missing measured data disables comparison only. It must not replace, move or
    prevent the original mission from playing.
    """
    if cube is None or not result.get("id"):
        return
    payload = _clean(result)
    payload["request_region"] = str(cube.region)
    key = payload.get("settings", {}).get("vehicle", {}).get("key")
    vehicle = MISSION_VEHICLES.get(key)
    error, terrain_id, blob, metadata = None, None, None, None
    try:
        if vehicle is None:
            raise ValueError("The selected vehicle has no supported travel model.")
        b = cube.bands
        elevation = np.asarray(b["elevation"], dtype="<f4")
        slope = np.asarray(b["slope"], dtype="<f4")
        cost = physics.cost_seconds_per_meter(b, vehicle)
        valid = (np.isfinite(elevation) & np.isfinite(slope) & np.isfinite(cost)
                 & np.isfinite(b["roughness"]) & np.isfinite(b["firmness"])
                 & ~planner.offlimits(cube, vehicle))
        # A neutral material fallback keeps the existing unranked game usable,
        # but it is not measured safe terrain for a ranked route.
        if "thermal_inertia" in b:
            valid &= np.isfinite(b["thermal_inertia"])
        else:
            valid[:] = False
        if not valid.any():
            error = "No measured traversable terrain is available for route comparison."
        thermal = np.asarray(b.get("thermal_inertia", np.full_like(elevation, np.nan)), dtype="<f4")
        # Same terrain factors as the existing planner; material is a model proxy,
        # not an observation of bearing strength or individual rocks.
        firm = np.nan_to_num(b.get("firmness", np.full_like(elevation, .5)), nan=.5)
        energy = (vehicle.get("wh_per_km", 0) / 1000 * (1 + .05 * slope) *
                  (1 + .5 * vehicle.get("sand_penalty", 0) * (1-firm)**2))
        arrays = dict(elevation_m=elevation, slope_degrees=slope,
                      firmness=np.asarray(b["firmness"], dtype="<f4"),
                      thermal_inertia=thermal, valid=valid, cost_s_m=np.asarray(cost, dtype="<f8"),
                      energy_wh_m=np.asarray(energy, dtype="<f8"))
        metadata = dict(region=str(cube.region), rect=cube.rect, shape=list(elevation.shape),
                        pixel_m=list(map(float, cube.pixel_m)), radius_m=MARS_RADIUS_M,
                        sources=list(cube.provenance), model_version=MODEL_VERSION,
                        vehicle=dict(vehicle), row_order="north_to_south")
        digest = hashlib.sha256(_json(metadata).encode())
        for name in sorted(arrays):
            digest.update(name.encode())
            digest.update(np.ascontiguousarray(arrays[name]).tobytes())
        terrain_id = digest.hexdigest()
        stream = io.BytesIO()
        np.savez_compressed(stream, **arrays)
        blob = stream.getvalue()
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        error = str(exc)
    with _write() as db:
        if terrain_id:
            db.execute("INSERT OR IGNORE INTO terrain VALUES(?,?,?)", (terrain_id, _json(metadata), blob))
        db.execute("INSERT OR IGNORE INTO plans VALUES(?,?,?,?,?,?)",
                   (payload["id"], _json(payload), terrain_id, _json(vehicle or {}), error, time.time()))


def _plan(plan_id):
    with _lock:
        row = _db().execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "This saved planner mission is unavailable. You can still play it; generate it again to compare routes.")
    return dict(row), json.loads(row["payload"])


def _terrain(terrain_id):
    with _lock:
        db = _db()
        if terrain_id in _terrain_cache:
            return _terrain_cache[terrain_id]
        row = db.execute("SELECT metadata,arrays FROM terrain WHERE id=?", (terrain_id,)).fetchone()
        if row is None:
            raise HTTPException(503, "The saved mission terrain is unavailable.")
        with np.load(io.BytesIO(row[1]), allow_pickle=False) as src:
            data = {k: src[k].copy() for k in src.files}
        data["metadata"] = json.loads(row[0])
        data["id"] = terrain_id
        if len(_terrain_cache) >= 4:
            _terrain_cache.pop(next(iter(_terrain_cache)))
        _terrain_cache[terrain_id] = data
        return data


def _candidate(plan, candidate):
    if candidate < 0 or candidate >= len(plan.get("candidates", [])):
        raise HTTPException(400, "That selected planner route does not exist.")
    return plan["candidates"][candidate]


def _points(raw):
    points = []
    for p in raw:
        lat, lon = float(p["lat"]), float(p["lon"])
        if not math.isfinite(lat) or not math.isfinite(lon):
            raise HTTPException(400, "Route coordinates must be finite.")
        point = {"lat": round(lat, 8), "lon": round(lon, 8)}
        if not points or point != points[-1]:
            points.append(point)
    if len(points) < 2 or len(points) > MAX_POINTS:
        raise HTTPException(400, f"Route needs 2 to {MAX_POINTS} distinct points.")
    return points


def _local(point, data):
    rect = data["metadata"]["rect"]
    mid = math.radians((rect["north"]+rect["south"])/2)
    return np.array([(point["lon"]-rect["west"])*math.pi/180*MARS_RADIUS_M*math.cos(mid),
                     (rect["north"]-point["lat"])*math.pi/180*MARS_RADIUS_M])


def _crossings(a, b, data):
    """Exact raster-cell partition, including all cells touched at edge/corners."""
    dy, dx = data["metadata"]["pixel_m"]
    rows, cols = data["valid"].shape
    if any(p[0] < 0 or p[1] < 0 or p[0] >= cols*dx or p[1] >= rows*dy for p in (a,b)):
        raise HTTPException(400, "The route leaves the mission boundary.")
    cuts = [0., 1.]
    for axis, step in ((0,dx),(1,dy)):
        if abs(b[axis]-a[axis]) > 1e-12:
            lo, hi = sorted((a[axis],b[axis]))
            cuts.extend((k*step-a[axis])/(b[axis]-a[axis])
                        for k in range(math.floor(lo/step)+1, math.ceil(hi/step)))
    cuts = sorted(set(cuts))
    for t in cuts:
        p = a+(b-a)*t
        cc, rr = p[0]/dx, p[1]/dy
        columns = {int(math.floor(cc))}
        lines = {int(math.floor(rr))}
        if abs(cc-round(cc)) < 1e-8:
            columns.add(int(round(cc))-1)
        if abs(rr-round(rr)) < 1e-8:
            lines.add(int(round(rr))-1)
        for r in lines:
            for c in columns:
                if 0 <= r < rows and 0 <= c < cols and not data["valid"][r,c]:
                    raise HTTPException(400, "A route segment crosses missing or forbidden terrain.")
    intervals=[]
    for t0,t1 in zip(cuts,cuts[1:]):
        p=a+(b-a)*((t0+t1)/2)
        r,c=int(p[1]/dy),int(p[0]/dx)
        if not data["valid"][r,c]:
            raise HTTPException(400, "A route segment crosses missing or forbidden terrain.")
        intervals.append((t0,t1,r,c))
    return intervals


def _key(record, plan, candidate):
    c = _candidate(plan,candidate)
    return _hash(dict(terrain=record["terrain"], vehicle=json.loads(record["model"]),
                      settings=plan.get("settings"), reference=_points(c["route"]["points"]),
                      objectives=c.get("card",{}).get("sampling",[]), tools=plan.get("tools"),
                      site_hours=SITE_HOURS, version=MODEL_VERSION))


def _evaluate(record, plan, candidate, raw):
    if record["error"] or not record["terrain"]:
        raise HTTPException(409, record["error"] or "Measured route comparison is unavailable.")
    data=_terrain(record["terrain"])
    cand=_candidate(plan,candidate)
    reference=_points(cand["route"]["points"])
    points=_points(raw)
    local=[_local(p,data) for p in points]
    if any(float(np.linalg.norm(local[i]-_local(reference[i],data))) > 1 for i in (0,-1)):
        raise HTTPException(400,"Keep the original mission start and destination.")
    distance=seconds=energy=0.
    elevations=[]
    for a,b in zip(local,local[1:]):
        length=float(np.linalg.norm(b-a))
        distance+=length
        if distance > 100000:
            raise HTTPException(400,"Route exceeds the 100 km comparison limit.")
        for t0,t1,r,c in _crossings(a,b,data):
            ds=length*(t1-t0)
            seconds+=ds*float(data["cost_s_m"][r,c])
            energy+=ds*float(data["energy_wh_m"][r,c])
            elevations.append(float(data["elevation_m"][r,c]))
    vehicle=json.loads(record["model"])
    if distance <= POSITION_ROUNDOFF_M:
        raise HTTPException(400,"A ranked route must have a measurable travel distance.")
    if distance > vehicle["range_km"]*1000:
        raise HTTPException(400,"The edited route exceeds this vehicle's mission range.")
    total_seconds=2*seconds
    tools_mass=float(plan.get("tools",{}).get("kg",0) or 0)
    load=1+tools_mass/vehicle["mass_kg"] if vehicle.get("battery_wh") else 1
    height_changes=np.diff(elevations)
    climb_factor=(vehicle["mass_kg"]+tools_mass)*physics.MARS_G/3600 if vehicle.get("battery_wh") else 0
    one_way_energy=energy*load+vehicle.get("hotel_w",0)*seconds/3600+climb_factor*float(np.maximum(height_changes,0).sum())
    round_trip_energy=2*energy*load+vehicle.get("hotel_w",0)*total_seconds/3600+climb_factor*float(np.abs(height_changes).sum())
    battery=next((r for r in cand.get("resources",{}).get("items",[]) if r.get("name")=="battery"),None)
    if battery and one_way_energy+float(battery.get("site",0))>float(battery.get("usable",math.inf)):
        raise HTTPException(400,"The edited route exceeds the mission's usable battery after its reserve.")
    metrics=dict(simulated_time_s=round(seconds,3),one_way_time_s=round(seconds,3),
                 round_trip_time_s=round(total_seconds,3),distance_m=round(distance,3),
                 round_trip_distance_m=round(2*distance,3),energy_wh=round(one_way_energy,3),
                 one_way_energy_wh=round(one_way_energy,3),round_trip_energy_wh=round(round_trip_energy,3),
                 science_time_s=SITE_HOURS*3600,time_basis="one-way A to B travel; sampling time excluded",
                 energy_basis="one-way drive, hotel load and grid-resolved climbs; sampling excluded")
    return dict(key=_key(record,plan,candidate),points=points,route_hash=_hash(points),metrics=metrics)


def _display(data, points):
    meta=data["metadata"]; rect=meta["rect"]; rows,cols=data["valid"].shape
    dy,dx=meta["pixel_m"]
    local=np.array([_local(p,data) for p in points])
    margin=max(1000.,float(np.ptp(local,axis=0).max())*.25)
    c0=max(0,int((local[:,0].min()-margin)/dx));c1=min(cols,int((local[:,0].max()+margin)/dx)+2)
    r0=max(0,int((local[:,1].min()-margin)/dy));r1=min(rows,int((local[:,1].max()+margin)/dy)+2)
    step=max(1,math.ceil(max(c1-c0,r1-r0)/512))
    rr=np.arange(r0,r1,step);cc=np.arange(c0,c1,step)
    if not len(rr) or not len(cc):
        raise HTTPException(400,"The saved reference route is outside its terrain grid.")
    def lon(c):return rect["west"]+(c+.5)/cols*(rect["east"]-rect["west"])
    def lat(r):return rect["north"]-(r+.5)/rows*(rect["north"]-rect["south"])
    grid={k:_clean(data[k][np.ix_(rr,cc)]) for k in ("elevation_m","slope_degrees","thermal_inertia","valid")}
    if "firmness" in data:
        grid["firmness"]=_clean(data["firmness"][np.ix_(rr,cc)])
    grid.update(shape=[len(rr),len(cc)],resolution_m=[dy*step,dx*step],row_order="north_to_south")
    return dict(rect=dict(west=lon(cc[0]),east=lon(cc[-1]),north=lat(rr[0]),south=lat(rr[-1])),
                boundary=rect,grid=grid,source_resolution_m=[dy,dx],display_resolution_m=[dy*step,dx*step],
                source_resolution_note="Saved planner cube spacing; source imagery and DEM resolutions differ. See provenance.",
                sources=meta["sources"],dataset_id=data["id"],rect_convention="outer sampled node centres",
                material_note="Thermal inertia is a surface-material estimate, not measured traction.")


@router.get("/materials")
def materials(region: str=Query(default="jezero",min_length=1,max_length=80),
              west: float|None=None,south: float|None=None,east: float|None=None,north: float|None=None):
    """Read an existing regional cube for the standalone game's material map.

    This path never starts a cube build and does not classify unseen terrain.
    Material observations remain visible even where route travel is forbidden.
    """
    if region_box(region) is None:
        raise HTTPException(400,"Unknown mission region.")
    from app import get_cube
    cube=get_cube(region)
    thermal=cube.bands.get("thermal_inertia")
    if thermal is None:
        raise HTTPException(404,"No thermal-inertia observations are available for this region.")
    thermal=np.asarray(thermal)
    rows,cols=thermal.shape
    rect=cube.rect;dy,dx=map(float,cube.pixel_m)
    r0,c0,r1,c1=0,0,rows,cols
    bounds=(west,south,east,north)
    if any(v is not None for v in bounds):
        if not all(v is not None and math.isfinite(v) for v in bounds) or not (-180<=west<east<=180 and -90<=south<north<=90):
            raise HTTPException(400,"Provide a complete, valid material-map rectangle.")
        if east<rect["west"] or west>rect["east"] or north<rect["south"] or south>rect["north"]:
            raise HTTPException(404,"No planner material observations in this view.")
        # Crop before reducing: a short route keeps the native planner pixels.
        c0=max(0,int(math.floor((west-rect["west"])/(rect["east"]-rect["west"])*cols))-1)
        c1=min(cols,int(math.ceil((east-rect["west"])/(rect["east"]-rect["west"])*cols))+1)
        r0=max(0,int(math.floor((rect["north"]-north)/(rect["north"]-rect["south"])*rows))-1)
        r1=min(rows,int(math.ceil((rect["north"]-south)/(rect["north"]-rect["south"])*rows))+1)
        c0=min(c0,cols-2);r0=min(r0,rows-2);c1=max(c1,c0+2);r1=max(r1,r0+2)
    step=max(1,math.ceil(max(r1-r0,c1-c0)/512))
    rr=np.arange(r0,r1,step);cc=np.arange(c0,c1,step)
    grid=dict(thermal_inertia=_clean(thermal[np.ix_(rr,cc)]),shape=[len(rr),len(cc)],
              resolution_m=[dy*step,dx*step],row_order="north_to_south")
    if "firmness" in cube.bands:
        grid["firmness"]=_clean(np.asarray(cube.bands["firmness"])[np.ix_(rr,cc)])
    def lon(c):return rect["west"]+(c+.5)/cols*(rect["east"]-rect["west"])
    def lat(r):return rect["north"]-(r+.5)/rows*(rect["north"]-rect["south"])
    return dict(available=True,terrain=dict(
        rect=dict(west=lon(cc[0]),east=lon(cc[-1]),north=lat(rr[0]),south=lat(rr[-1])),
        boundary=rect,grid=grid,source_resolution_m=[dy,dx],display_resolution_m=[dy*step,dx*step],
        source_resolution_note="Existing planner cube spacing; see source provenance for native instrument resolution.",
        sources=list(cube.provenance),rect_convention="outer sampled node centres",
        material_note="Thermal inertia and derived firmness estimate surface material, not measured bearing strength or individual rocks."))


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, candidate: int=Query(0,ge=0,le=8)):
    record,plan=_plan(plan_id);cand=_candidate(plan,candidate)
    result=dict(plan=plan,candidate=candidate,available=False,key=None,
                reference=dict(points=[]),reason=record["error"])
    try:
        result["reference"]["points"]=_points(cand["route"]["points"])
        result["key"]=_key(record,plan,candidate)
        if record["terrain"]:
            result["terrain"]=_display(_terrain(record["terrain"]),result["reference"]["points"])
        reference=_evaluate(record,plan,candidate,cand["route"]["points"])
        result.update(available=True,reference=reference,reason=None)
    except HTTPException as exc:
        result["reason"]=str(exc.detail)
    return result


class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)


class Point(Strict):
    lat: float=Field(ge=-90,le=90)
    lon: float=Field(ge=-180,le=360)


class RouteRequest(Strict):
    candidate: int=Field(default=0,ge=0,le=8)
    points: list[Point]=Field(min_length=2,max_length=MAX_POINTS)


@router.post("/plans/{plan_id}/evaluate")
def evaluate(plan_id: str, req: RouteRequest):
    record,plan=_plan(plan_id)
    result=_evaluate(record,plan,req.candidate,[p.model_dump() for p in req.points])
    result["reference_metrics"]=_evaluate(record,plan,req.candidate,_candidate(plan,req.candidate)["route"]["points"])["metrics"]
    return result


class Credentials(Strict):
    name: str=Field(min_length=3,max_length=40)
    token: str=Field(min_length=8,max_length=200)


class StartRequest(Credentials,RouteRequest):
    plan_id: str=Field(min_length=1,max_length=80)
    idempotency_key: str=Field(min_length=8,max_length=100)
    difficulty: Literal["cadet","astronaut","commander"]="astronaut"
    driving_mode: Literal["2d","3d"]="3d"


class ClaimAttemptRequest(Credentials):
    guest_token: str=Field(min_length=8,max_length=200)


class FinishRequest(Credentials):
    ai_drive_ticks: int=Field(gt=0,le=54000,strict=True)
    route_hash: str=Field(min_length=64,max_length=64)
    benchmark_version: Literal["fixed-step-drive-v1"]


class ProgressRequest(Credentials):
    sequence: int=Field(ge=1,le=1000000)
    position: Point
    mode: str=Field(pattern="^(driving|paused)$")
    samples: int=Field(default=0,ge=0,le=1)


def _auth(req):
    if req.name.startswith("@guest:"):
        with _lock:
            row=_db().execute("SELECT token_hash FROM route_guests WHERE name=?",(req.name,)).fetchone()
        if row is None or not secrets.compare_digest(row[0],players._hash(req.token)):
            raise HTTPException(403,"This browser does not hold that guest attempt.")
        return req.name
    name=players.clean_name(req.name)
    with players._lock:
        row=players._db().execute("SELECT name,token_hash FROM players WHERE name_lc=?",(name.lower(),)).fetchone()
    if row is None or not secrets.compare_digest(row[1],players._hash(req.token)):
        raise HTTPException(403,"Claim this callsign before submitting route scores.")
    return row[0]


@router.post("/route-guests")
def create_route_guest():
    # A private browser capability, not a public callsign or account login.
    name="@guest:"+secrets.token_hex(12)
    token=secrets.token_urlsafe(24)
    with _write() as db:
        db.execute("INSERT INTO route_guests VALUES(?,?,?)",(name,players._hash(token),time.time()))
    return dict(name=name,token=token)


def _score_key(key,difficulty,driving_mode):
    return _hash(dict(mission=key,difficulty=difficulty,driving_mode=driving_mode))


def _attempt(db,attempt_id,name,allow_legacy=False):
    row=db.execute("SELECT * FROM attempts WHERE id=?",(attempt_id,)).fetchone()
    if row is None:raise HTTPException(404,"Route attempt not found.")
    if row["name_lc"]!=name.lower():raise HTTPException(403,"This attempt belongs to another callsign.")
    payload=json.loads(row["payload"])
    if not allow_legacy and payload.get("model_version")!=MODEL_VERSION:
        raise HTTPException(409,"This attempt used the previous mission format. Restart for a single-destination mission.")
    return row,payload,json.loads(row["state"])


def _snapshot(row,payload,state):
    return dict(payload,**{k:v for k,v in state.items() if k not in ("updated","request_hash")},id=row["id"],plan_id=row["plan_id"],candidate=row["candidate"])


def _save(db,attempt_id,state):
    db.execute("UPDATE attempts SET state=? WHERE id=?",(_json(state),attempt_id))


@router.post("/route-attempts")
def start(req: StartRequest):
    name=_auth(req);record,plan=_plan(req.plan_id)
    payload=evaluate(req.plan_id,RouteRequest(candidate=req.candidate,points=req.points))
    payload["model_version"]=MODEL_VERSION
    payload["max_drive_m_s"]=MAX_DRIVE_M_S
    payload["difficulty"]=req.difficulty
    payload["driving_mode"]=req.driving_mode
    payload["key"]=_score_key(payload["key"],req.difficulty,req.driving_mode)
    with _write() as db:
        prior=db.execute("SELECT * FROM attempts WHERE name_lc=? AND idempotency_key=?",(name.lower(),req.idempotency_key)).fetchone()
        if prior:
            saved=json.loads(prior["payload"])
            if saved.get("model_version")!=MODEL_VERSION:
                raise HTTPException(409,"This attempt used the previous mission format. Restart for a single-destination mission.")
            if saved["route_hash"]!=payload["route_hash"] or saved["key"]!=payload["key"]:
                raise HTTPException(409,"That attempt key already locks a different route.")
            return _snapshot(prior,saved,json.loads(prior["state"]))
        for row in db.execute("SELECT id,state FROM attempts WHERE name_lc=?",(name.lower(),)).fetchall():
            state=json.loads(row["state"])
            if state["status"]=="active":state.update(status="invalidated",mode="paused");_save(db,row["id"],state)
        attempt_id=secrets.token_urlsafe(18)
        state=dict(status="active",mode="paused",sequence=0,position=payload["points"][0],samples=0,
                   visited_destination=False,objective_complete=False,active_drive_s=0.,updated=time.monotonic(),request_hash=None)
        db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)",(attempt_id,name.lower(),name,req.plan_id,req.candidate,payload["key"],req.idempotency_key,_json(payload),_json(state)))
        return _snapshot(*_attempt(db,attempt_id,name))


@router.post("/route-attempts/{attempt_id}/claim")
def claim_attempt(attempt_id:str,req:ClaimAttemptRequest):
    name=_auth(req)
    if name.startswith("@guest:"):
        raise HTTPException(400,"Choose a callsign before joining the leaderboard.")
    with _write() as db:
        row=db.execute("SELECT * FROM attempts WHERE id=?",(attempt_id,)).fetchone()
        if row is None:raise HTTPException(404,"Route attempt not found.")
        if row["name_lc"]==name.lower():return _snapshot(*_attempt(db,attempt_id,name))
        guest=db.execute("SELECT token_hash FROM route_guests WHERE name=?",(row["name"],)).fetchone()
        if guest is None or not secrets.compare_digest(guest[0],players._hash(req.guest_token)):
            raise HTTPException(403,"This browser does not hold that guest attempt.")
        _,payload,state=_attempt(db,attempt_id,row["name"])
        if state["status"]!="active" or not state.get("objective_complete"):
            raise HTTPException(400,"Complete the sample at B before claiming this result.")
        try:
            db.execute("UPDATE attempts SET name_lc=?,name=? WHERE id=?",(name.lower(),name,attempt_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409,"That callsign already owns an attempt with this key.")
        return _snapshot(*_attempt(db,attempt_id,name))


def _distance_to_segment(p,a,b):
    d=b-a;length=float(d@d)
    t=min(1.,max(0.,float((p-a)@d)/length)) if length else 0.
    return float(np.linalg.norm(p-(a+t*d)))


@router.post("/route-attempts/{attempt_id}/progress")
def progress(attempt_id: str, req: ProgressRequest):
    name=_auth(req)
    with _write() as db:
        row,payload,state=_attempt(db,attempt_id,name)
        packet=req.model_dump(exclude={"name","token"});fingerprint=_hash(packet)
        if req.sequence==state["sequence"] and fingerprint==state["request_hash"]:return _snapshot(row,payload,state)
        if state["status"]!="active":raise HTTPException(409,"This route attempt is no longer active.")
        if req.sequence!=state["sequence"]+1:raise HTTPException(409,"Progress is stale. Resume the saved attempt.")
        if state.get("objective_complete") and req.mode!="paused":
            raise HTTPException(409,"This objective is complete. Submit its result or start another mission.")
        record,plan=_plan(row["plan_id"]);data=_terrain(record["terrain"])
        new=req.position.model_dump();a,b=_local(state["position"],data),_local(new,data)
        now=time.monotonic();elapsed=max(0.,now-state["updated"])
        dt=elapsed if state["mode"]=="driving" and elapsed<=MAX_HEARTBEAT_GAP_S else 0.
        length=float(np.linalg.norm(b-a))
        if dt == 0:
            if length>POSITION_ROUNDOFF_M:
                raise HTTPException(400,"Movement requires active driving time. Resume saved progress.")
            # Coordinate conversion can differ by sub-millimetre roundoff. Keep
            # the authoritative anchor: accepting that noise must never grant
            # a fresh movement allowance on every paused/frozen-clock packet.
            new=dict(state["position"]);b=a;length=0.
        elif length>MAX_DRIVE_M_S*dt:
            raise HTTPException(400,"Movement exceeds the active driving allowance. Resume saved progress.")
        # Validate swept terrain, not merely the received endpoints.
        _crossings(a,b,data)
        route=np.array([_local(p,data) for p in payload["points"]])
        vectors=route[1:]-route[:-1]
        squared=np.einsum("ij,ij->i",vectors,vectors)
        for t in np.linspace(0,1,max(2,int(math.ceil(length/20))+1)):
            p=a+(b-a)*t
            fractions=np.clip(np.einsum("ij,ij->i",p-route[:-1],vectors)/np.maximum(squared,1e-12),0,1)
            distances=np.linalg.norm(p-(route[:-1]+fractions[:,None]*vectors),axis=1)
            if float(distances.min())>CORRIDOR_M:
                raise HTTPException(400,"Movement leaves the mission's route and shelter area.")
        visited=state["visited_destination"] or (dt>0 and length>0 and _distance_to_segment(route[-1],a,b)<=SCIENCE_RADIUS_M)
        if req.samples>state["samples"]:
            if not visited or float(np.linalg.norm(b-route[-1]))>SCIENCE_RADIUS_M:
                raise HTTPException(400,"Reach B and complete the sample at this mission's destination.")
            # The server checks collection location; completion of the browser's
            # sampling mini-game remains a browser-reported claim.
        complete=bool(state.get("objective_complete") or (visited and req.samples==1))
        state.update(mode="paused" if complete else req.mode,sequence=req.sequence,position=new,samples=max(state["samples"],req.samples),
                     visited_destination=bool(visited),objective_complete=complete,
                     active_drive_s=state["active_drive_s"]+dt,updated=now,request_hash=fingerprint)
        _save(db,attempt_id,state)
        return _snapshot(row,payload,state)


def _pause(attempt_id,req,invalidate=False):
    name=_auth(req)
    with _write() as db:
        row,payload,state=_attempt(db,attempt_id,name,allow_legacy=invalidate)
        if state["status"]=="active":
            state.update(status="invalidated" if invalidate else "active",mode="paused",updated=time.monotonic())
            _save(db,attempt_id,state)
        return _snapshot(row,payload,state)


@router.post("/route-attempts/{attempt_id}/resume")
def resume(attempt_id:str,req:Credentials):return _pause(attempt_id,req)


@router.post("/route-attempts/{attempt_id}/restart")
def restart(attempt_id:str,req:Credentials):return _pause(attempt_id,req,True)


def _board(db,key,limit=100):
    # Ranking is by route time only. Actual driving time is never a tie-breaker.
    best={}
    for row in db.execute("SELECT * FROM attempts WHERE mission_key=?",(key,)):
        state,payload=json.loads(row["state"]),json.loads(row["payload"])
        if state["status"]!="finished" or payload.get("model_version")!=MODEL_VERSION:continue
        ticks=state.get("ai_drive_ticks")
        if type(ticks) is not int or ticks<=0 or state.get("benchmark_version")!=BENCHMARK_VERSION:continue
        entry=dict(name=row["name"],attempt_id=row["id"],ai_drive_ticks=ticks,ai_driving_time_s=round(ticks/30,6),
                   distance_m=payload["metrics"]["distance_m"],actual_driving_time_s=round(state["active_drive_s"],3),points=payload["points"])
        if row["name_lc"] not in best or ticks<best[row["name_lc"]]["ai_drive_ticks"]:best[row["name_lc"]]=entry
    values=sorted(best.values(),key=lambda e:(e["ai_drive_ticks"],e["name"].lower()))
    rank=0;previous=None
    for i,e in enumerate(values,1):
        if e["ai_drive_ticks"]!=previous:rank=i;previous=e["ai_drive_ticks"]
        e["rank"]=rank
    return (values if limit is None else values[:limit]),len(values)


@router.post("/route-attempts/{attempt_id}/finish")
def finish(attempt_id:str,req:FinishRequest):
    name=_auth(req)
    if name.startswith("@guest:"):raise HTTPException(400,"Choose a callsign before joining the leaderboard.")
    with _write() as db:
        row,payload,state=_attempt(db,attempt_id,name)
        if state["status"]=="finished":return _snapshot(row,payload,state)
        if state["status"]!="active":raise HTTPException(409,"This route attempt was restarted.")
        if req.route_hash!=payload["route_hash"]:
            raise HTTPException(409,"The AI comparison belongs to a different route.")
        record,plan=_plan(row["plan_id"]);data=_terrain(record["terrain"])
        if not state["visited_destination"] or not state.get("objective_complete") or state["samples"]!=1 or float(np.linalg.norm(_local(state["position"],data)-_local(payload["points"][-1],data)))>SCIENCE_RADIUS_M:
            raise HTTPException(400,"Reach B and complete its sample before submitting this mission.")
        checked=_evaluate(record,plan,row["candidate"],payload["points"])
        if checked["metrics"]!=payload["metrics"]:raise HTTPException(409,"The route model changed; restart the attempt.")
        state.update(status="finished",mode="paused",ai_drive_ticks=req.ai_drive_ticks,
                     ai_driving_time_s=round(req.ai_drive_ticks/30,6),benchmark_version=req.benchmark_version)
        _save(db,attempt_id,state)
        # A submission receipt needs its rank even when it lies beyond the
        # first page, including a tie containing more than 100 callsigns.
        board,_=_board(db,payload["key"],limit=None)
        state["rank"]=next((e["rank"] for e in board if e["name"].lower()==name.lower()),None)
        _save(db,attempt_id,state)
        return _snapshot(row,payload,state)


@router.get("/route-leaderboard")
def route_leaderboard(key:str=Query(min_length=1,max_length=80),limit:int=Query(20,ge=1,le=100),
                      difficulty:Literal["cadet","astronaut","commander"]|None=None,
                      driving_mode:Literal["2d","3d"]|None=None):
    if difficulty is not None or driving_mode is not None:
        key=_score_key(key,difficulty or "astronaut",driving_mode or "3d")
    with _lock:
        db=_db();board,count=_board(db,key,limit)
        row=db.execute("SELECT payload FROM attempts WHERE mission_key=? LIMIT 1",(key,)).fetchone()
    payload=json.loads(row[0]) if row else None
    reference=payload["reference_metrics"] if payload and payload.get("model_version")==MODEL_VERSION else None
    return dict(key=key,board=board,players=count,reference_metrics=reference,
                score_label="AI driving your designed route; lower is better",model_version=MODEL_VERSION,
                benchmark_version=BENCHMARK_VERSION)
