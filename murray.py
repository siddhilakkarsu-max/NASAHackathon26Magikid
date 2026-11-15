"""
Every map from the Murray Lab global CTX mosaic viewer
(https://murray-lab.caltech.edu/CTX/V01/SceneView/MurrayLabCTXmosaic.html), for our Cesium globe:

- image tiles (CTX 5 m mosaic, MOLA colour shaded relief, Viking MDIM) load straight from Esri's "OnMars"
  services in the browser: same geographic 512 px tiling as Cesium's, and they allow cross-origin requests;
- 3D terrain (MDEM200M, MOLA/HRSC 200 m) is relayed here: Cesium only accepts Esri elevation services in
  WKID 4326, so the service description is passed on with Mars 2000 (104971) relabelled - the grid is identical;
- feature layers (rover traverses, IAU names, impact craters, the CTX tile index with download links, HiRISE
  footprints) are downloaded once, slimmed and cached in cubes/murraycache/.

murray-lab.caltech.edu sends the wrong intermediate certificate, so downloads from it also trust the correct
public one shipped in certs/ (InCommon RSA OV SSL CA 3, issued by Sectigo Public Server Authentication Root R46).
"""
import json
import math
import ssl
import threading
import urllib.request
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

ROOT = Path(__file__).parent
CACHE = ROOT / "cubes" / "murraycache"
ESRI = "https://astro.arcgis.com/arcgis/rest/services/OnMars"
FEATURES = "https://murray-lab.caltech.edu/CTX/V01/SceneView/Features"
CRATERS = ("https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
           "Mars_Nomenclature_Mountains/FeatureServer/7")
CALTECH_CA = ROOT / "certs" / "InCommon_RSA_OV_SSL_CA_3.pem"
MARS_R = 3396190.0
UA = {"User-Agent": "Mozilla/5.0 (compatible; mars-cube-builder)"}

# The viewer's layers, in its order. "default" = shown by default on the Murray Lab page.
LAYERS = [
    dict(id="ctx", kind="tiles", title="CTX mosaic, 5 m (Murray Lab)", default=True, max_level=17,
         url=f"{ESRI}/CTX1/MapServer/tile/{{z}}/{{y}}/{{x}}", credit="Imagery: NASA, JPL, MSSS, Caltech/Murray Lab, Esri"),
    dict(id="mola", kind="tiles", title="MOLA topography (colour shaded relief)", default=False, max_level=17,
         url=f"{ESRI}/MColorDEM/MapServer/tile/{{z}}/{{y}}/{{x}}", credit="USGS Astrogeology, NASA, JPL, ESA, DLR, Esri"),
    dict(id="viking", kind="tiles", title="Viking MDIM 2.1 mosaic", default=False, max_level=17,
         url=f"{ESRI}/MDIM/MapServer/tile/{{z}}/{{y}}/{{x}}", credit="USGS Astrogeology, NASA, JPL, MSSS, Caltech/Murray Lab, Esri"),
    dict(id="terrain", kind="terrain", title="3D terrain (MOLA/HRSC 200 m)", default=True,
         url="/murray/elevation/", credit="Topography: NASA GSFC, DLR, USGS Astrogeology, JPL, Esri"),
    dict(id="m2020", kind="geojson", title="Mars 2020 traverse (through sol 678)", default=True,
         url="/murray/features/m2020.geojson", style="line", color="#3ad6ff", credit="NASA/JPL/M2020"),
    dict(id="msl", kind="geojson", title="MSL traverse (through sol 3420)", default=True,
         url="/murray/features/msl.geojson", style="line", color="#ff5ad1", credit="NASA/JPL/MSL"),
    dict(id="names", kind="geojson", title="Feature names (IAU)", default=False,
         url="/murray/features/names.geojson", style="labels", credit="IAU WGPSN"),
    dict(id="craters", kind="geojson", title="Impact craters (IAU)", default=False,
         url="/murray/features/craters.geojson", style="outlines", credit="IAU WGPSN, Esri"),
    dict(id="quads", kind="geojson", title="Global mosaic tile map (link to data)", default=False,
         url="/murray/features/quads.geojson", style="outlines", credit="Caltech/Murray Lab"),
    dict(id="hirise", kind="bbox", title="HiRISE footprints (in view)", default=False,
         url="/murray/hirise", style="outlines", credit="NASA/JPL/University of Arizona"),
]

router = APIRouter()
_lock = threading.Lock()


def _ssl_ctx():
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    if CALTECH_CA.exists():
        ctx.load_verify_locations(str(CALTECH_CA))
    return ctx


def _fetch(url, timeout=600):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        return r.read()


def _raw(name):
    """A Murray Lab GeoJSON file, downloaded once."""
    path = CACHE / "raw" / f"{name}.geojson"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(_fetch(f"{FEATURES}/{name}.geojson"))
        tmp.rename(path)
    return json.loads(path.read_text())


def _lon(lon):
    return lon - 360 if lon > 180 else lon


def _r(x):
    return round(float(x), 5)


# ------------------------------------------------------------- slimming ----
def _traverse(name, rover):
    """Waypoints (one point per drive step, ~40 fields each) -> a single line with coordinates only."""
    pts = [f["geometry"]["coordinates"] for f in _raw(name)["features"] if f.get("geometry")]
    line, last = [], None
    for lon, lat, *_ in pts:
        p = [_r(_lon(lon)), _r(lat)]
        if p != last:
            line.append(p)
            last = p
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": f"{rover} traverse", "waypoints": len(pts)},
         "geometry": {"type": "LineString", "coordinates": line}}]}


def _names():
    feats = []
    for f in _raw("mars-nomenclature")["features"]:
        p, (lon, lat) = f["properties"], f["geometry"]["coordinates"][:2]
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [_r(_lon(lon)), _r(lat)]},
                      "properties": {"name": p.get("name"), "type": p.get("type"),
                                     "diameter_km": p.get("diameter"), "origin": p.get("origin")}})
    return {"type": "FeatureCollection", "features": feats}


def _quads():
    feats = []
    for f in _raw("MurrayLab_CTX_V01_Quad-Map")["features"]:
        ring = [[_r(_lon(x)), _r(y)] for x, y, *_ in f["geometry"]["coordinates"][0]]
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {"name": f["properties"]["Quad"], "link": f["properties"]["Data"]}})
    return {"type": "FeatureCollection", "features": feats}


def _craters():
    q = ("query?where=type%3D%27Crater%2C+craters%27&outFields=name,diameter,center_lon,center_lat"
         "&returnGeometry=true&geometryPrecision=4&f=geojson&resultRecordCount=2000")
    data = json.loads(_fetch(f"{CRATERS}/{q}", timeout=120))
    feats = []
    for f in data.get("features", []):
        g, p = f.get("geometry"), f.get("properties") or {}
        if not g:
            continue
        rings = g["coordinates"] if g["type"] == "Polygon" else [r for poly in g["coordinates"] for r in poly]
        ring = max(rings, key=len)
        step = max(1, len(ring) // 72)                        # a crater outline needs ~72 points at most
        ring = [[_r(_lon(x)), _r(y)] for x, y, *_ in ring[::step]]
        ring.append(ring[0])
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {"name": p.get("name"), "diameter_km": p.get("diameter")}})
    return {"type": "FeatureCollection", "features": feats}


SLIM = {
    "m2020": lambda: _traverse("Mars2020_0678", "Mars 2020 (Perseverance)"),
    "msl": lambda: _traverse("MSL_3420", "MSL (Curiosity)"),
    "names": _names,
    "quads": _quads,
    "craters": _craters,
}


@router.get("/api/murray/layers")
def murray_layers():
    """The Murray Lab viewer's layers, for the map panel."""
    return {"source": "https://murray-lab.caltech.edu/CTX/V01/SceneView/MurrayLabCTXmosaic.html", "layers": LAYERS}


@router.get("/murray/features/{name}.geojson")
def murray_features(name: str):
    if name not in SLIM:
        raise HTTPException(404, f"unknown layer {name}; one of {list(SLIM)}")
    path = CACHE / f"{name}.geojson"
    with _lock:
        if not path.exists():
            try:
                data = SLIM[name]()
            except Exception as e:
                raise HTTPException(502, f"could not download {name}: {e}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, separators=(",", ":")))
    return Response(path.read_bytes(), media_type="application/geo+json",
                    headers={"Cache-Control": "public, max-age=86400"})


# --------------------------------------------------------- HiRISE index ----
_hirise = None


def _hirise_index():
    """78k HiRISE RED footprints (equirectangular metres in the source) -> degrees + bounding boxes, cached."""
    global _hirise
    if _hirise is not None:
        return _hirise
    with _lock:
        if _hirise is not None:
            return _hirise
        cache = CACHE / "hirise_index.npz"
        if not cache.exists():
            deg = math.pi / 180 * MARS_R
            boxes, rings, ids, starts = [], [], [], [0]
            for f in _raw("hirise_red")["features"]:
                g = f.get("geometry")
                if not g:
                    continue
                ring = np.array(g["coordinates"][0], dtype="float64")[:, :2] / deg
                ring[:, 0] = np.where(ring[:, 0] > 180, ring[:, 0] - 360, ring[:, 0])
                rings.append(np.round(ring, 5))
                starts.append(starts[-1] + len(ring))
                boxes.append([ring[:, 0].min(), ring[:, 1].min(), ring[:, 0].max(), ring[:, 1].max()])
                ids.append(f["properties"].get("OB_ID") or f["properties"].get("PROD_ID") or "")
            tmp = cache.with_name("hirise_index.part.npz")
            np.savez_compressed(tmp, boxes=np.array(boxes), coords=np.concatenate(rings), starts=np.array(starts),
                                ids=np.array(ids))
            tmp.rename(cache)
        z = np.load(cache)
        _hirise = {k: z[k] for k in z.files}
        return _hirise


def _hirise_feature(ix, i):
    s, e = ix["starts"][i], ix["starts"][i + 1]
    ob = str(ix["ids"][i])
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ix["coords"][s:e].tolist()]},
            "properties": {"name": ob, "link": f"https://www.uahirise.org/{ob}" if ob else None}}


@router.get("/murray/hirise")
def murray_hirise(west: float, south: float, east: float, north: float, limit: int = 1500):
    """HiRISE footprints overlapping a box (the page asks for the current view)."""
    ix = _hirise_index()
    b = ix["boxes"]
    hit = np.nonzero((b[:, 0] <= east) & (b[:, 2] >= west) & (b[:, 1] <= north) & (b[:, 3] >= south))[0]
    return {"type": "FeatureCollection", "total": int(hit.size), "truncated": bool(hit.size > limit),
            "features": [_hirise_feature(ix, i) for i in hit[:limit]]}


@router.get("/murray/hirise/at")
def murray_hirise_at(lat: float, lon: float):
    """HiRISE observations whose footprint box contains a point (for the clicked-point panel)."""
    ix = _hirise_index()
    b = ix["boxes"]
    hit = np.nonzero((b[:, 0] <= lon) & (b[:, 2] >= lon) & (b[:, 1] <= lat) & (b[:, 3] >= lat))[0]
    return {"observations": [_hirise_feature(ix, i)["properties"] for i in hit[:20]], "total": int(hit.size)}


_quad_boxes = None


@router.get("/murray/quad/at")
def murray_quad_at(lat: float, lon: float):
    """The CTX mosaic tile containing a point, with its download page."""
    global _quad_boxes
    if _quad_boxes is None:
        murray_features("quads")                       # make sure the cache exists
        feats = json.loads((CACHE / "quads.geojson").read_text())["features"]
        _quad_boxes = [(min(x for x, _ in f["geometry"]["coordinates"][0]), min(y for _, y in f["geometry"]["coordinates"][0]),
                        max(x for x, _ in f["geometry"]["coordinates"][0]), max(y for _, y in f["geometry"]["coordinates"][0]),
                        f["properties"]) for f in feats]
    for w, s_, e, n, props in _quad_boxes:
        if w <= lon <= e and s_ <= lat <= n:
            return props
    return {"name": None, "link": None}


# ------------------------------------------------------- 3D terrain relay ----
_elev_meta = None


def _relabel(obj):
    """Mars 2000 geographic (WKID 104971) -> 4326 so Cesium accepts the identical geographic grid."""
    if isinstance(obj, dict):
        return {k: (4326 if k in ("wkid", "latestWkid") and v == 104971 else _relabel(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_relabel(v) for v in obj]
    return obj


@router.get("/murray/elevation")
@router.get("/murray/elevation/")
def murray_elevation_meta():
    global _elev_meta
    if _elev_meta is None:
        _elev_meta = _relabel(json.loads(_fetch(f"{ESRI}/MDEM200M/ImageServer?f=json", timeout=60)))
    return _elev_meta


@router.get("/murray/elevation/tile/{z}/{y}/{x}")
def murray_elevation_tile(z: int, y: int, x: int):
    path = CACHE / "elevation" / f"{z}_{y}_{x}.lerc"
    if not path.exists():
        try:
            data = _fetch(f"{ESRI}/MDEM200M/ImageServer/tile/{z}/{y}/{x}", timeout=60)
        except Exception:
            raise HTTPException(404, "no elevation tile")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return Response(path.read_bytes(), media_type="application/octet-stream",
                    headers={"Cache-Control": "public, max-age=604800"})
