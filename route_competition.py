"""Authoritative, versioned rover route competition; independent of survival scores.

Measured terrain supplies elevation and slope. The explicitly illustrative rover
model is a fixed comparison rule, not a prediction of an actual rover's performance.
TES thermal inertia is display context only; it never becomes a traction penalty.
Scores depend solely on a confirmed route. Driving earns completion eligibility,
with server-clock motion bounds, and is not part of the ranked time.
"""
import hashlib
import heapq
import json
import math
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Literal

import numpy as np
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import leaderboard as players

router = APIRouter(prefix="/api/competition", tags=["route competition"])
MODEL = dict(version="jezero-rover-comparison-v1", base_speed_m_s=0.04,
             grade_scale=0.10, max_slope_degrees=25.0, electrical_power_w=110.0,
             mass_kg=899.0, gravity_m_s2=3.71, drivetrain_efficiency=0.70,
             integration_step_m=5.0, drive_time_scale=400.0, corridor_m=30.0,
             objective_radius_m=30.0, heartbeat_gap_s=2.0)
CONDITIONS = dict(rover="fixed comparison rover", weather="fixed clear conditions",
                  traction="uniform assumption; thermal inertia is not used",
                  score="standardized simulated travel time; lower is better")
REFERENCE_VERSION = "astar-eight-neighbours-v1"
START = [3900.0, 2500.0]
CATALOG = [dict(id="station-a", label="Survey station A", xy=[4100.0, 2650.0]),
           dict(id="station-b", label="Survey station B", xy=[4300.0, 2550.0]),
           dict(id="station-c", label="Survey station C", xy=[4450.0, 2750.0])]
MAX_ROUTE_POINTS = 512
MAX_ROUTE_M = 30000.0
_lock = threading.RLock()
_conn = None
_conn_path = None


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Credentials(StrictRequest):
    name: str = Field(min_length=3, max_length=40)
    token: str = Field(min_length=8, max_length=200)


class MissionRequest(StrictRequest):
    goal: str = Field(default="Explore the Jezero delta margin", max_length=300)
    destination: tuple[float, float]
    required_stops: list[tuple[float, float]] = Field(default_factory=list, max_length=4)


class RouteRequest(StrictRequest):
    route: list[tuple[float, float]] = Field(min_length=2, max_length=MAX_ROUTE_POINTS)


class AttemptRequest(Credentials):
    mission_id: str = Field(min_length=1, max_length=80)
    route: list[tuple[float, float]] = Field(min_length=2, max_length=MAX_ROUTE_POINTS)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ProgressRequest(Credentials):
    sequence: int = Field(ge=1, le=1000000)
    mode: Literal["driving", "paused"]
    position: tuple[float, float]


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _terrain():
    try:
        from competition_terrain import load_terrain
        return load_terrain()
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(503, "Competition terrain is unavailable; install the verified Jezero terrain package.") from exc


def _db():
    global _conn, _conn_path
    path = players.state_dir() / "route_competition.sqlite3"
    if _conn is None or _conn_path != path:
        if _conn is not None:
            _conn.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS competition_missions (
              id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS competition_attempts (
              id TEXT PRIMARY KEY, name_lc TEXT NOT NULL, name TEXT NOT NULL,
              mission_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
              route_hash TEXT NOT NULL, payload TEXT NOT NULL,
              status TEXT NOT NULL, mode TEXT NOT NULL, sequence INTEGER NOT NULL DEFAULT 0,
              position TEXT NOT NULL, distance_m REAL NOT NULL DEFAULT 0,
              completed_stops TEXT NOT NULL DEFAULT '[]', active_drive_s REAL NOT NULL DEFAULT 0,
              updated REAL NOT NULL, created REAL NOT NULL, finished REAL,
              time_ms INTEGER NOT NULL, result TEXT, last_request TEXT,
              UNIQUE(name_lc, idempotency_key));
            CREATE INDEX IF NOT EXISTS competition_board
              ON competition_attempts(mission_id,status,time_ms);
        """)
        _conn_path = path
    return _conn


@contextmanager
def _write_db():
    """Serialize state transitions across server processes as well as threads."""
    db = _db()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    else:
        db.commit()


def _auth(req):
    name = players.clean_name(req.name)
    with players._lock:
        row = players._db().execute("SELECT name,token_hash FROM players WHERE name_lc=?", (name.lower(),)).fetchone()
    if row is None:
        raise HTTPException(404, "Claim a callsign before starting a competition attempt.")
    if not secrets.compare_digest(row[1], players._hash(req.token)):
        raise HTTPException(403, "This browser does not hold that callsign.")
    return row[0]


def _xy(value):
    if len(value) != 2 or not all(math.isfinite(float(v)) for v in value):
        raise HTTPException(422, "Coordinates must contain two finite numbers.")
    return [round(float(v), 3) for v in value]


def _canonical_route(route):
    result = []
    for point in route:
        p = _xy(point)
        if result and math.dist(result[-1], p) < 0.001:
            continue
        while len(result) >= 2:
            a, b = result[-2:]
            ab, bc = [b[i] - a[i] for i in range(2)], [p[i] - b[i] for i in range(2)]
            if abs(ab[0] * bc[1] - ab[1] * bc[0]) > 1e-8 or sum(ab[i] * bc[i] for i in range(2)) < 0:
                break
            result.pop()
        result.append(p)
    if len(result) < 2:
        raise HTTPException(400, "A route needs at least two different points.")
    return result


def _valid_segment(terrain, a, b):
    try:
        return bool(terrain.segment_is_valid(a, b, max_slope_degrees=MODEL["max_slope_degrees"]))
    except (ValueError, IndexError):
        return False


def _travel_seconds(horizontal, rise):
    return math.hypot(horizontal,rise)/MODEL["base_speed_m_s"]*(1+(rise/horizontal/MODEL["grade_scale"])**2)


def _circle_entry(a, b, center, radius):
    d = [b[i] - a[i] for i in range(2)]
    q = [a[i] - center[i] for i in range(2)]
    aa, bb, cc = sum(v*v for v in d), 2*sum(q[i]*d[i] for i in range(2)), sum(v*v for v in q)-radius*radius
    if cc <= 0:
        return 0.0
    discriminant = bb*bb - 4*aa*cc
    if aa == 0 or discriminant < 0:
        return None
    t = (-bb - math.sqrt(discriminant))/(2*aa)
    return max(0.0, t) if -1e-10 <= t <= 1+1e-10 else None


def _objective_stations(route, stops):
    stations, previous = [], 0.0
    for stop in stops:
        offset, found = 0.0, None
        for a, b in zip(route, route[1:]):
            length = math.dist(a, b)
            if offset+length >= previous:
                begin = max(0.0, (previous-offset)/length)
                aa = [a[i]+begin*(b[i]-a[i]) for i in range(2)]
                t = _circle_entry(aa, b, stop["xy"], stop["radius_m"])
                if t is not None:
                    found = offset+length*(begin+(1-begin)*t)
                    break
            offset += length
        if found is None:
            raise HTTPException(400, "Route must visit every required stop in the stated order.")
        stations.append(dict(id=stop["id"], distance_m=round(found, 6)))
        previous = found+0.001
    return stations


def evaluate_route(mission, raw_route, terrain=None):
    terrain = terrain or _terrain()
    if mission["terrain_identity"] != _terrain_identity(terrain) or mission["model"] != MODEL:
        raise HTTPException(409, "This mission uses a different terrain or model version. Create a new mission.")
    route = _canonical_route(raw_route)
    if math.dist(route[0], mission["start"]) > 0.001 or math.dist(route[-1], mission["destination"]) > 0.001:
        raise HTTPException(400, "Route must start and finish at the exact mission endpoints.")
    lengths = [math.dist(a, b) for a, b in zip(route, route[1:])]
    distance = sum(lengths)
    if distance > MAX_ROUTE_M:
        raise HTTPException(400, "Route exceeds the 30 km competition limit.")
    for i, (a, b) in enumerate(zip(route, route[1:])):
        if not _valid_segment(terrain, a, b):
            raise HTTPException(400, f"Segment {i+1} crosses the boundary, missing elevation, or terrain above 25 degrees.")
    objectives = _objective_stations(route, mission["required_stops"])
    # Uniform stations over the whole polyline prevent arbitrary waypoint density
    # from changing the numerical integration of the same geometric route.
    samples = [0.0,distance]
    samples.extend(float(s) for s in np.arange(MODEL["integration_step_m"], distance, MODEL["integration_step_m"]))
    samples.extend(float(s) for s in np.cumsum(lengths)[:-1])
    # True corners must be integrated: an ascent and descent at a turn between
    # uniform stations cannot cancel each other's grade/energy cost.
    samples = sorted(set(samples))
    profile, index, offset, seconds, energy, surface = [], 0, 0.0, 0.0, 0.0, 0.0
    prev = None
    for station in samples:
        while index < len(lengths)-1 and station > offset+lengths[index]:
            offset += lengths[index]
            index += 1
        a, b = route[index:index+2]
        t = min(1.0, max(0.0, (station-offset)/lengths[index]))
        x, y = [a[k]+t*(b[k]-a[k]) for k in range(2)]
        try:
            z = float(terrain.sample(x, y)["elevation_m"])
        except (ValueError, KeyError, IndexError) as exc:
            raise HTTPException(400, "Route crosses missing elevation.") from exc
        if not math.isfinite(z):
            raise HTTPException(400, "Route crosses missing elevation.")
        if prev:
            horizontal, dz = station-prev[0], z-prev[1]
            ds = math.hypot(horizontal, dz)
            dt = _travel_seconds(horizontal,dz)
            seconds += dt
            surface += ds
            energy += MODEL["electrical_power_w"]*dt/3600 + max(0,dz)*MODEL["mass_kg"]*MODEL["gravity_m_s2"]/MODEL["drivetrain_efficiency"]/3600
        profile.append(dict(x=round(x,6), y=round(y,6), elevation_m=round(z,6), distance_m=round(station,6), time_s=round(seconds,6)))
        prev = station, z
    return dict(route=route, route_hash=_hash(route), metrics=dict(simulated_time_s=round(seconds,3),
                distance_m=round(distance,3), surface_distance_m=round(surface,3), energy_wh=round(energy,3)),
                profile=profile, objectives=objectives)


def _terrain_identity(terrain):
    meta = terrain.metadata()
    return {k: meta[k] for k in ("dataset_version", "dataset_sha256")}


def _graph_route(terrain, start, destination):
    """A* on native measured nodes, followed by exact segment revalidation."""
    resolution = float(terrain.resolution_m)
    heights = np.asarray(terrain.elevation_m)
    safe = np.asarray(terrain.valid, dtype=bool) & np.isfinite(heights) & (np.asarray(terrain.slope_degrees) <= MODEL["max_slope_degrees"])
    nr, nc = heights.shape
    def rc(p):
        return int(round((terrain.height_m-p[1])/resolution)), int(round(p[0]/resolution))
    def xy(p):
        return [p[1]*resolution, terrain.height_m-p[0]*resolution]
    first, last = rc(start), rc(destination)
    for node in (first,last):
        if not (0 <= node[0] < nr and 0 <= node[1] < nc and safe[node]):
            raise HTTPException(400, "An objective lies outside safe measured terrain.")
    queue, cost, parent = [(0.0,first)], {first:0.0}, {}
    closed = set()
    while queue:
        _, node = heapq.heappop(queue)
        if node in closed:
            continue
        if node == last:
            nodes = [last]
            while nodes[-1] != first:
                nodes.append(parent[nodes[-1]])
            path = [start]+[xy(n) for n in reversed(nodes)]+[destination]
            return _canonical_route(path)
        closed.add(node)
        r,c = node
        for dr,dc in ((-1,0),(0,-1),(0,1),(1,0),(-1,-1),(-1,1),(1,-1),(1,1)):
            rr,cc = r+dr,c+dc
            nxt = (rr,cc)
            if not (0 <= rr < nr and 0 <= cc < nc and safe[nxt]):
                continue
            # Every cell touching an edge is checked, including diagonal corners.
            r0,r1,c0,c1 = max(0,min(r,rr)-1),min(nr,max(r,rr)+2),max(0,min(c,cc)-1),min(nc,max(c,cc)+2)
            if not safe[r0:r1,c0:c1].all():
                continue
            length = resolution*math.hypot(dr,dc)
            edge = _travel_seconds(length,float(heights[nxt])-float(heights[node]))
            proposed = cost[node]+edge
            if proposed < cost.get(nxt,float("inf")):
                cost[nxt],parent[nxt] = proposed,node
                heuristic = math.dist(nxt,last)*resolution/MODEL["base_speed_m_s"]
                heapq.heappush(queue,(proposed+heuristic,nxt))
    raise HTTPException(400, "No safe reference route connects these objectives.")


def _create_mission(req, terrain=None):
    terrain = terrain or _terrain()
    points = [_xy(START)]+[_xy(p) for p in req.required_stops]+[_xy(req.destination)]
    if any(math.dist(a,b) < 2*MODEL["objective_radius_m"] for a,b in zip(points,points[1:])):
        raise HTTPException(400, "Consecutive objectives must be at least 60 metres apart.")
    route = []
    for a,b in zip(points,points[1:]):
        leg = _graph_route(terrain,a,b)
        route.extend(leg if not route else leg[1:])
    route = _canonical_route(route)
    if len(route) > MAX_ROUTE_POINTS:
        raise HTTPException(400, "Reference route is too complex; choose closer objectives.")
    stops = [dict(id=f"stop-{i+1}",label=f"Required stop {i+1}",xy=p,radius_m=MODEL["objective_radius_m"]) for i,p in enumerate(points[1:-1])]
    canonical = dict(start=points[0],destination=points[-1],required_stops=stops,
                     terrain_identity=_terrain_identity(terrain),model=MODEL.copy(),conditions=CONDITIONS.copy(),
                     reference_version=REFERENCE_VERSION,reference_route=route)
    mission = dict(canonical,id=_hash(canonical),goal=req.goal.strip(),reference_label="AI reference (graph search)",
                   interpretation="The selected destination and ordered stops are the objectives. Goal text is descriptive; it is not interpreted by a language model.")
    reference = evaluate_route(mission,route,terrain)
    mission["reference"] = reference
    with _lock, _write_db() as db:
        db.execute("INSERT OR IGNORE INTO competition_missions VALUES (?,?,?)",(mission["id"],_json(mission),time.time()))
        mission = json.loads(db.execute("SELECT payload FROM competition_missions WHERE id=?",(mission["id"],)).fetchone()[0])
    # Description is request context, not a ranked mission constraint. Reusing a
    # canonical ID must echo this request's note without rewriting the stored
    # mission, its objectives, or its immutable reference route.
    return dict(mission,goal=req.goal.strip())


def _mission(mission_id):
    with _lock:
        row = _db().execute("SELECT payload FROM competition_missions WHERE id=?",(mission_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Competition mission not found.")
    return json.loads(row[0])


def _public_mission(mission):
    terrain = _terrain()
    if mission["terrain_identity"] != _terrain_identity(terrain):
        raise HTTPException(409, "The installed terrain differs from this immutable mission.")
    return dict(mission,terrain=dict(metadata=terrain.metadata(),grid=terrain.public_grid(step=1)))


@router.get("/config")
def config():
    default = _create_mission(MissionRequest(destination=CATALOG[-1]["xy"], required_stops=[p["xy"] for p in CATALOG[:-1]]))
    return dict(model=MODEL,conditions=CONDITIONS,start=START,catalog=CATALOG,default_mission_id=default["id"],
                limits=dict(max_route_points=MAX_ROUTE_POINTS,max_route_m=MAX_ROUTE_M,max_required_stops=4),
                limitations=["Illustrative fixed rover model, not a measured prediction of flight rover performance.",
                             "Elevation is native 20 m CTX terrain; displayed interpolation does not reveal small rocks.",
                             "Coarse TES thermal inertia is context only and does not control traction.",
                             "Driving completion is checked geometrically and by server time; client input is not proof of human driving.",
                             "Equal millisecond-rounded simulated times receive equal ranks; driving time never breaks ties."])


@router.get("/missions")
def missions():
    with _lock:
        rows = _db().execute("SELECT payload FROM competition_missions ORDER BY created DESC LIMIT 100").fetchall()
    return {"missions":[{k:m[k] for k in ("id","goal","start","destination","required_stops","terrain_identity")} for m in (json.loads(r[0]) for r in rows)]}


@router.post("/missions")
def create_mission(req: MissionRequest):
    return _public_mission(_create_mission(req))


@router.get("/missions/{mission_id}")
def get_mission(mission_id: str):
    return _public_mission(_mission(mission_id))


@router.post("/missions/{mission_id}/evaluate")
def evaluate(mission_id: str, req: RouteRequest):
    return evaluate_route(_mission(mission_id),req.route)


def _attempt(db, attempt_id, name):
    row = db.execute("SELECT * FROM competition_attempts WHERE id=?",(attempt_id,)).fetchone()
    if row is None:
        raise HTTPException(404,"Competition attempt not found.")
    if row["name_lc"] != name.lower():
        raise HTTPException(403,"This attempt belongs to another callsign.")
    return row


def _snapshot(row):
    payload = json.loads(row["payload"])
    mission = _mission(row["mission_id"])
    position, stops = json.loads(row["position"]),json.loads(row["completed_stops"])
    complete = len(stops) == len(mission["required_stops"]) and math.dist(position,mission["destination"]) <= MODEL["objective_radius_m"] and row["distance_m"] >= payload["metrics"]["distance_m"]-MODEL["objective_radius_m"]
    result = dict(id=row["id"],mission_id=row["mission_id"],status=row["status"],mode=row["mode"],sequence=row["sequence"],
                  position=position,distance_m=row["distance_m"],completed_stops=stops,completed=complete,
                  active_drive_s=round(row["active_drive_s"],3),route=payload["route"],route_hash=row["route_hash"],metrics=payload["metrics"])
    if row["result"]:
        result.update(json.loads(row["result"]))
    return result


@router.post("/attempts")
def start_attempt(req: AttemptRequest):
    name = _auth(req)
    mission = _mission(req.mission_id)
    scored = evaluate_route(mission,req.route)
    with _lock, _write_db() as db:
        prior = db.execute("SELECT * FROM competition_attempts WHERE name_lc=? AND idempotency_key=?",(name.lower(),req.idempotency_key)).fetchone()
        if prior:
            if prior["mission_id"] != req.mission_id or prior["route_hash"] != scored["route_hash"]:
                raise HTTPException(409,"Idempotency key already confirms a different route or mission.")
            return _snapshot(prior)
        # One active run per callsign: confirming an edited route invalidates its
        # previous run and cannot inherit progress or completion eligibility.
        db.execute("UPDATE competition_attempts SET status='invalidated',mode='paused' WHERE name_lc=? AND status='active'",(name.lower(),))
        now, attempt_id = time.time(),secrets.token_urlsafe(18)
        db.execute("""INSERT INTO competition_attempts
           (id,name_lc,name,mission_id,idempotency_key,route_hash,payload,status,mode,position,updated,created,time_ms)
           VALUES (?,?,?,?,?,?,?,'active','paused',?,?,?,?)""",
           (attempt_id,name.lower(),name,req.mission_id,req.idempotency_key,scored["route_hash"],_json(scored),_json(mission["start"]),now,now,round(scored["metrics"]["simulated_time_s"]*1000)))
        return _snapshot(_attempt(db,attempt_id,name))


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, x_callsign: str = Header(default=""), authorization: str = Header(default="")):
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not x_callsign or not token:
        raise HTTPException(401,"Supply X-Callsign and an Authorization Bearer token.")
    try:
        credentials = Credentials(name=x_callsign,token=token)
    except ValidationError as exc:
        raise HTTPException(401,"Invalid callsign authorization headers.") from exc
    name = _auth(credentials)
    with _lock:
        return _snapshot(_attempt(_db(),attempt_id,name))


def _pause_attempt(attempt_id, req, invalidate=False):
    name = _auth(req)
    with _lock, _write_db() as db:
        row = _attempt(db,attempt_id,name)
        if row["status"] == "active":
            db.execute("UPDATE competition_attempts SET status=?,mode='paused',updated=? WHERE id=?",("invalidated" if invalidate else "active",time.time(),attempt_id))
        return _snapshot(_attempt(db,attempt_id,name))


@router.post("/attempts/{attempt_id}/resume")
def resume_attempt(attempt_id: str, req: Credentials):
    """Refresh never grants elapsed drive credit or continues an old driving mode."""
    return _pause_attempt(attempt_id,req)


@router.post("/attempts/{attempt_id}/restart")
def restart_attempt(attempt_id: str, req: Credentials):
    return _pause_attempt(attempt_id,req,True)


def _projection(route, point, minimum=0.0, maximum=float("inf")):
    best, offset = None,0.0
    for a,b in zip(route,route[1:]):
        length = math.dist(a,b)
        lo,hi = max(0,(minimum-offset)/length),min(1,(maximum-offset)/length)
        if lo <= hi:
            t = min(hi,max(lo,sum((point[k]-a[k])*(b[k]-a[k]) for k in range(2))/length**2))
            q = [a[k]+t*(b[k]-a[k]) for k in range(2)]
            candidate = (math.dist(q,point),offset+t*length)
            if best is None or candidate < best:
                best = candidate
        offset += length
    return best


def _swept_in_corridor(route, start, end, minimum, maximum):
    """Cover the entire movement by the union of route-segment capsules.

    Each capsule is its endpoint circles plus its rectangular strip. Their exact
    line-intersection intervals avoid missing a short excursion between samples.
    """
    intervals, offset = [],0.0
    movement = [end[i]-start[i] for i in range(2)]
    radius = MODEL["corridor_m"]
    def circle(center):
        q = [start[i]-center[i] for i in range(2)]
        aa,bb,cc = sum(v*v for v in movement),2*sum(q[i]*movement[i] for i in range(2)),sum(v*v for v in q)-radius*radius
        if aa < 1e-16:
            if cc <= 1e-8:
                intervals.append((0.0,1.0))
            return
        disc = bb*bb-4*aa*cc
        if disc >= 0:
            lo,hi = max(0.0,(-bb-math.sqrt(disc))/(2*aa)),min(1.0,(-bb+math.sqrt(disc))/(2*aa))
            if lo <= hi:
                intervals.append((lo,hi))
    for a,b in zip(route,route[1:]):
        length = math.dist(a,b)
        lo,hi = max(0.0,(minimum-offset)/length),min(1.0,(maximum-offset)/length)
        offset += length
        if lo > hi:
            continue
        aa,bb = [[a[i]+fraction*(b[i]-a[i]) for i in range(2)] for fraction in (lo,hi)]
        circle(aa)
        circle(bb)
        segment_length = math.dist(aa,bb)
        if segment_length < 1e-10:
            continue
        u = [(bb[i]-aa[i])/segment_length for i in range(2)]
        normal = [-u[1],u[0]]
        lower,upper = 0.0,1.0
        for axis,low,high in ((u,0.0,segment_length),(normal,-radius,radius)):
            origin = sum((start[i]-aa[i])*axis[i] for i in range(2))
            velocity = sum(movement[i]*axis[i] for i in range(2))
            if abs(velocity) < 1e-12:
                if origin < low-1e-9 or origin > high+1e-9:
                    lower,upper = 1.0,0.0
                    break
            else:
                t0,t1 = sorted(((low-origin)/velocity,(high-origin)/velocity))
                lower,upper = max(lower,t0),min(upper,t1)
        if lower <= upper:
            intervals.append((lower,upper))
    covered = 0.0
    for lo,hi in sorted(intervals):
        if lo > covered+1e-8:
            return False
        covered = max(covered,hi)
        if covered >= 1-1e-8:
            return True
    return False


def _movement_seconds(terrain, start, end):
    distance = math.dist(start,end)
    if distance < 1e-9:
        return 0.0
    count = max(1,math.ceil(distance/MODEL["integration_step_m"]))
    previous, seconds = float(terrain.sample(*start)["elevation_m"]),0.0
    for i in range(1,count+1):
        p = [start[k]+i/count*(end[k]-start[k]) for k in range(2)]
        z = float(terrain.sample(*p)["elevation_m"])
        seconds += _travel_seconds(distance/count,z-previous)
        previous = z
    return seconds


@router.post("/attempts/{attempt_id}/progress")
def progress(attempt_id: str, req: ProgressRequest):
    name, position = _auth(req),_xy(req.position)
    terrain = _terrain()
    request_hash = _hash(dict(sequence=req.sequence,mode=req.mode,position=position))
    with _lock, _write_db() as db:
        row = _attempt(db,attempt_id,name)
        if req.sequence == row["sequence"] and row["last_request"] == request_hash:
            return _snapshot(row)
        if row["status"] != "active":
            raise HTTPException(409,"This attempt is no longer active.")
        if req.sequence != row["sequence"]+1:
            raise HTTPException(409,"Progress sequence is stale or skips an update. Resume the saved attempt.")
        mission = _mission(row["mission_id"])
        if mission["terrain_identity"] != _terrain_identity(terrain) or mission["model"] != MODEL:
            raise HTTPException(409,"Terrain or model changed; restart with a new mission.")
        now, old = time.time(),json.loads(row["position"])
        elapsed = max(0,now-row["updated"])
        # Long loading/network gaps earn no motion or active-time credit.
        dt = elapsed if row["mode"] == "driving" and elapsed <= MODEL["heartbeat_gap_s"] else 0.0
        maximum_motion = MODEL["base_speed_m_s"]*MODEL["drive_time_scale"]*dt
        movement = math.dist(old,position)
        if (movement > 0.002 and dt < 0.05) or movement > maximum_motion+0.002:
            raise HTTPException(400,"Movement exceeds the server clock allowance; resume at the saved position.")
        if not _valid_segment(terrain,old,position):
            raise HTTPException(400,"Movement crosses unsafe or missing terrain.")
        if _movement_seconds(terrain,old,position) > dt*MODEL["drive_time_scale"]+0.1:
            raise HTTPException(400,"Movement is too fast for the measured grade and fixed rover model.")
        route = json.loads(row["payload"])["route"]
        projection = _projection(route,position,row["distance_m"]-0.002,row["distance_m"]+maximum_motion+0.002)
        if projection is None or projection[0] > MODEL["corridor_m"]:
            raise HTTPException(400,"Stay within the confirmed route corridor and travel forward.")
        station = max(row["distance_m"],projection[1])
        if not _swept_in_corridor(route,old,position,row["distance_m"]-0.002,station+0.002):
            raise HTTPException(400,"The swept movement leaves the confirmed route corridor.")
        completed = json.loads(row["completed_stops"])
        previous_entry = 0.0
        for stop in mission["required_stops"][len(completed):]:
            after = [old[k]+previous_entry*(position[k]-old[k]) for k in range(2)]
            entry = _circle_entry(after,position,stop["xy"],stop["radius_m"])
            if entry is None:
                break
            previous_entry += (1-previous_entry)*entry
            completed.append(stop["id"])
        db.execute("""UPDATE competition_attempts SET mode=?,sequence=?,position=?,distance_m=?,completed_stops=?,
                      active_drive_s=?,updated=?,last_request=? WHERE id=?""",
                   (req.mode,req.sequence,_json(position),station,_json(completed),row["active_drive_s"]+dt,now,request_hash,attempt_id))
        return _snapshot(_attempt(db,attempt_id,name))


def _board(db, mission_id, limit=100):
    rows = db.execute("""WITH best AS (
        SELECT *,ROW_NUMBER() OVER(PARTITION BY name_lc ORDER BY time_ms,finished,id) AS chosen
        FROM competition_attempts WHERE mission_id=? AND status='finished')
        SELECT *,RANK() OVER(ORDER BY time_ms) AS place FROM best WHERE chosen=1
        ORDER BY time_ms,name_lc LIMIT ?""",(mission_id,limit)).fetchall()
    return [dict(rank=r["place"],name=r["name"],attempt_id=r["id"],simulated_time_s=r["time_ms"]/1000,
                 distance_m=json.loads(r["payload"])["metrics"]["distance_m"],energy_wh=json.loads(r["payload"])["metrics"]["energy_wh"],
                 active_drive_s=round(r["active_drive_s"],3),route_hash=r["route_hash"]) for r in rows]


@router.post("/attempts/{attempt_id}/finish")
def finish(attempt_id: str, req: Credentials):
    name = _auth(req)
    with _lock, _write_db() as db:
        row = _attempt(db,attempt_id,name)
        if row["status"] == "finished":
            return _snapshot(row)
        if row["status"] != "active":
            raise HTTPException(409,"This attempt was invalidated. Confirm a new route.")
        snapshot = _snapshot(row)
        if not snapshot["completed"]:
            raise HTTPException(400,"Drive the confirmed route through every ordered stop and the destination before finishing.")
        mission = _mission(row["mission_id"])
        checked = evaluate_route(mission,snapshot["route"])
        if checked["route_hash"] != row["route_hash"] or checked["metrics"] != snapshot["metrics"]:
            raise HTTPException(409,"Confirmed route no longer matches its original evaluation.")
        before = db.execute("SELECT MIN(time_ms) FROM competition_attempts WHERE name_lc=? AND mission_id=? AND status='finished'",(name.lower(),row["mission_id"])).fetchone()[0]
        db.execute("UPDATE competition_attempts SET status='finished',mode='paused',finished=? WHERE id=?",(time.time(),attempt_id))
        best = min(row["time_ms"],before) if before is not None else row["time_ms"]
        rank = db.execute("SELECT COUNT(*)+1 FROM (SELECT MIN(time_ms) AS best FROM competition_attempts WHERE mission_id=? AND status='finished' GROUP BY name_lc HAVING best<?)",(row["mission_id"],best)).fetchone()[0]
        reference = mission["reference"]["metrics"]
        result = dict(rank=rank,best_simulated_time_s=best/1000,improved=before is None or row["time_ms"] < before,
                      reference_metrics=reference,improvement_percent=round((reference["simulated_time_s"]-checked["metrics"]["simulated_time_s"])/reference["simulated_time_s"]*100,3))
        db.execute("UPDATE competition_attempts SET result=? WHERE id=?",(_json(result),attempt_id))
        return _snapshot(_attempt(db,attempt_id,name))


@router.get("/leaderboard")
def leaderboard(mission_id: str = Query(min_length=1,max_length=80), limit: int = Query(default=20,ge=1,le=100)):
    mission = _mission(mission_id)
    with _lock:
        db = _db()
        count = db.execute("SELECT COUNT(DISTINCT name_lc) FROM competition_attempts WHERE mission_id=? AND status='finished'",(mission_id,)).fetchone()[0]
        board = _board(db,mission_id,limit)
    return dict(mission_id=mission_id,board=board,players=count,reference_metrics=mission["reference"]["metrics"],ranking="Lowest standardized simulated travel time; equal millisecond times share rank.")
