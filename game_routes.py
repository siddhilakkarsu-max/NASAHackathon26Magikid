"""Route comparison attached to the existing planner and survival game.

The planner captures its own result and measured cube. Browser geometry is
evaluated against that immutable snapshot; a browser never supplies a score.
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

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import leaderboard as players
import mission as planner
import physics
from config import MARS_RADIUS_M, MISSION_VEHICLES, SITE_HOURS

router = APIRouter(prefix="/api/game", tags=["game routes"])
MODEL_VERSION = "planner-route-comparison-v1"
MAX_POINTS = 5000
MAX_DRIVE_M_S = 60.0  # Above the game's 45 m/s presentation cap, including storm drift.
MAX_HEARTBEAT_GAP_S = 4.0
CORRIDOR_M = 1000.0  # Existing science/shelter excursions remain available.
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
    if distance > vehicle["range_km"]*1000:
        raise HTTPException(400,"The edited route exceeds this vehicle's mission range.")
    total_seconds=2*seconds
    tools_mass=float(plan.get("tools",{}).get("kg",0) or 0)
    load=1+tools_mass/vehicle["mass_kg"] if vehicle.get("battery_wh") else 1
    climb_wh=(vehicle["mass_kg"]+tools_mass)*physics.MARS_G*float(np.abs(np.diff(elevations)).sum())/3600 if vehicle.get("battery_wh") else 0
    energy=2*energy*load+vehicle.get("hotel_w",0)*total_seconds/3600+climb_wh
    battery=next((r for r in cand.get("resources",{}).get("items",[]) if r.get("name")=="battery"),None)
    if battery and energy+float(battery.get("site",0))>float(battery.get("usable",math.inf)):
        raise HTTPException(400,"The edited route exceeds the mission's usable battery after its reserve.")
    metrics=dict(simulated_time_s=round(total_seconds,3),one_way_time_s=round(seconds,3),
                 round_trip_time_s=round(total_seconds,3),distance_m=round(distance,3),
                 round_trip_distance_m=round(2*distance,3),energy_wh=round(energy,3),
                 science_time_s=SITE_HOURS*3600,time_basis="round-trip travel; site work excluded",
                 energy_basis="round-trip drive, hotel load and grid-resolved climbs; site work excluded")
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
    grid.update(shape=[len(rr),len(cc)],resolution_m=[dy*step,dx*step],row_order="north_to_south")
    return dict(rect=dict(west=lon(cc[0]),east=lon(cc[-1]),north=lat(rr[0]),south=lat(rr[-1])),
                boundary=rect,grid=grid,source_resolution_m=[dy,dx],display_resolution_m=[dy*step,dx*step],
                source_resolution_note="Saved planner cube spacing; source imagery and DEM resolutions differ. See provenance.",
                sources=meta["sources"],dataset_id=data["id"],rect_convention="outer sampled node centres",
                material_note="Thermal inertia is a surface-material estimate, not measured traction.")


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, candidate: int=Query(0,ge=0,le=8)):
    record,plan=_plan(plan_id);cand=_candidate(plan,candidate)
    result=dict(plan=plan,candidate=candidate,available=False,key=_key(record,plan,candidate),
                reference=dict(points=_points(cand["route"]["points"])),reason=record["error"])
    try:
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


class ProgressRequest(Credentials):
    sequence: int=Field(ge=1,le=1000000)
    position: Point
    mode: str=Field(pattern="^(driving|paused)$")
    samples: int=Field(default=0,ge=0,le=100)


def _auth(req):
    name=players.clean_name(req.name)
    with players._lock:
        row=players._db().execute("SELECT name,token_hash FROM players WHERE name_lc=?",(name.lower(),)).fetchone()
    if row is None or not secrets.compare_digest(row[1],players._hash(req.token)):
        raise HTTPException(403,"Claim this callsign before submitting route scores.")
    return row[0]


def _attempt(db,attempt_id,name):
    row=db.execute("SELECT * FROM attempts WHERE id=?",(attempt_id,)).fetchone()
    if row is None:raise HTTPException(404,"Route attempt not found.")
    if row["name_lc"]!=name.lower():raise HTTPException(403,"This attempt belongs to another callsign.")
    return row,json.loads(row["payload"]),json.loads(row["state"])


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
    with _write() as db:
        prior=db.execute("SELECT * FROM attempts WHERE name_lc=? AND idempotency_key=?",(name.lower(),req.idempotency_key)).fetchone()
        if prior:
            saved=json.loads(prior["payload"])
            if saved["route_hash"]!=payload["route_hash"] or saved["key"]!=payload["key"]:
                raise HTTPException(409,"That attempt key already locks a different route.")
            return _snapshot(prior,saved,json.loads(prior["state"]))
        for row in db.execute("SELECT id,state FROM attempts WHERE name_lc=?",(name.lower(),)).fetchall():
            state=json.loads(row["state"])
            if state["status"]=="active":state.update(status="invalidated",mode="paused");_save(db,row["id"],state)
        attempt_id=secrets.token_urlsafe(18)
        state=dict(status="active",mode="paused",sequence=0,position=payload["points"][0],samples=0,
                   visited_destination=False,active_drive_s=0.,updated=time.monotonic(),request_hash=None)
        db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)",(attempt_id,name.lower(),name,req.plan_id,req.candidate,payload["key"],req.idempotency_key,_json(payload),_json(state)))
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
        record,plan=_plan(row["plan_id"]);data=_terrain(record["terrain"])
        new=req.position.model_dump();a,b=_local(state["position"],data),_local(new,data)
        now=time.monotonic();elapsed=max(0.,now-state["updated"])
        dt=elapsed if state["mode"]=="driving" and elapsed<=MAX_HEARTBEAT_GAP_S else 0.
        length=float(np.linalg.norm(b-a))
        if length>MAX_DRIVE_M_S*dt+.5:raise HTTPException(400,"Movement exceeds the active driving allowance. Resume saved progress.")
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
        if dt>0 and length>0 and _distance_to_segment(route[-1],a,b)<=35:state["visited_destination"]=True
        state.update(mode=req.mode,sequence=req.sequence,position=new,samples=max(state["samples"],req.samples),
                     active_drive_s=state["active_drive_s"]+dt,updated=now,request_hash=fingerprint)
        _save(db,attempt_id,state)
        return _snapshot(row,payload,state)


def _pause(attempt_id,req,invalidate=False):
    name=_auth(req)
    with _write() as db:
        row,payload,state=_attempt(db,attempt_id,name)
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
        if state["status"]!="finished":continue
        entry=dict(name=row["name"],attempt_id=row["id"],simulated_time_s=payload["metrics"]["simulated_time_s"],
                   distance_m=payload["metrics"]["distance_m"],actual_driving_time_s=round(state["active_drive_s"],3),points=payload["points"])
        if row["name_lc"] not in best or entry["simulated_time_s"]<best[row["name_lc"]]["simulated_time_s"]:best[row["name_lc"]]=entry
    values=sorted(best.values(),key=lambda e:(e["simulated_time_s"],e["name"].lower()))
    rank=0;previous=None
    for i,e in enumerate(values,1):
        if e["simulated_time_s"]!=previous:rank=i;previous=e["simulated_time_s"]
        e["rank"]=rank
    return values[:limit],len(values)


@router.post("/route-attempts/{attempt_id}/finish")
def finish(attempt_id:str,req:Credentials):
    name=_auth(req)
    with _write() as db:
        row,payload,state=_attempt(db,attempt_id,name)
        if state["status"]=="finished":return _snapshot(row,payload,state)
        if state["status"]!="active":raise HTTPException(409,"This route attempt was restarted.")
        record,plan=_plan(row["plan_id"]);data=_terrain(record["terrain"])
        if not state["visited_destination"] or state["samples"]<1 or float(np.linalg.norm(_local(state["position"],data)-_local(payload["points"][0],data)))>35:
            raise HTTPException(400,"Reach the destination, collect a sample and return to the original start first.")
        checked=_evaluate(record,plan,row["candidate"],payload["points"])
        if checked["metrics"]!=payload["metrics"]:raise HTTPException(409,"The route model changed; restart the attempt.")
        state.update(status="finished",mode="paused")
        _save(db,attempt_id,state)
        board,_=_board(db,payload["key"])
        state["rank"]=next((e["rank"] for e in board if e["name"].lower()==name.lower()),None)
        _save(db,attempt_id,state)
        return _snapshot(row,payload,state)


@router.get("/route-leaderboard")
def route_leaderboard(key:str=Query(min_length=1,max_length=80),limit:int=Query(20,ge=1,le=100)):
    with _lock:
        db=_db();board,count=_board(db,key,limit)
        row=db.execute("SELECT payload FROM attempts WHERE mission_key=? LIMIT 1",(key,)).fetchone()
    return dict(key=key,board=board,players=count,reference_metrics=json.loads(row[0])["reference_metrics"] if row else None,
                score_label="Simulated round-trip travel time; lower is better")
