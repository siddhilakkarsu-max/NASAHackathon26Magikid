"""
Every map from the Murray Lab global CTX mosaic viewer
(https://murray-lab.caltech.edu/CTX/V01/SceneView/MurrayLabCTXmosaic.html), for our Cesium globe:

- CTX image tiles are validated and cached locally; damaged upstream tiles use
  the corresponding crop of a valid coarser source tile. MOLA/Viking imagery
  loads straight from Esri's "OnMars" services;
- 3D terrain (MDEM200M, MOLA/HRSC 200 m) is relayed here: Cesium only accepts Esri elevation services in
  WKID 4326, so the service description is passed on with Mars 2000 (104971) relabelled - the grid is identical;
- feature layers (rover traverses, IAU names, impact craters, the CTX tile index with download links, HiRISE
  footprints) are downloaded once, slimmed and cached in cubes/murraycache/.

murray-lab.caltech.edu sends the wrong intermediate certificate, so downloads from it also trust the correct
public one shipped in certs/ (InCommon RSA OV SSL CA 3, issued by Sectigo Public Server Authentication Root R46).
"""
import io
import json
import math
import ssl
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin
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
CTX_MAX_LEVEL = 12
TERRAIN_MAX_LEVEL = 7
UA = {"User-Agent": "Mozilla/5.0 (compatible; mars-cube-builder)"}

# The viewer's layers, in its order. "default" = shown by default on the Murray Lab page.
LAYERS = [
    # CTX1 advertises a generic 0..17 pyramid, but its native ~5 m imagery
    # ends at level 12. Level 13..17 requests return HTTP 400 (verified at
    # Jezero, Gale, Olympus Mons and Valles Marineris on 2026-11-15).
    dict(id="ctx", kind="tiles", title="CTX mosaic, up to 5 m (Murray Lab)", default=True, max_level=CTX_MAX_LEVEL,
         url="/murray/ctx/{z}/{y}/{x}", source_url=f"{ESRI}/CTX1/MapServer/tile/{{z}}/{{y}}/{{x}}",
         resolution_note="Up to 5 m/pixel. Damaged or unavailable source tiles use valid coarser CTX imagery.",
         credit="Imagery: NASA, JPL, MSSS, Caltech/Murray Lab, Esri"),
    # These global products have usable cached tiles through level 7. The service's
    # generic image metadata lists finer levels, but their level-8 tile requests fail.
    # Let Cesium magnify the native imagery instead of requesting nonexistent tiles.
    dict(id="mola", kind="tiles", title="MOLA topography (colour shaded relief)", default=False, max_level=7,
         url=f"{ESRI}/MColorDEM/MapServer/tile/{{z}}/{{y}}/{{x}}", credit="USGS Astrogeology, NASA, JPL, ESA, DLR, Esri"),
    dict(id="viking", kind="tiles", title="Viking MDIM 2.1 mosaic", default=False, max_level=7,
         url=f"{ESRI}/MDIM/MapServer/tile/{{z}}/{{y}}/{{x}}", credit="USGS Astrogeology, NASA, JPL, MSSS, Caltech/Murray Lab, Esri"),
    dict(id="terrain", kind="terrain", title="3D terrain (MOLA/HRSC 200 m)", default=True, max_level=TERRAIN_MAX_LEVEL,
         url="/murray/elevation/v2/", credit="Topography: NASA GSFC, DLR, USGS Astrogeology, JPL, Esri"),
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


# ------------------------------------------------------ validated CTX tiles ----
CTX_FALLBACK_TTL = 3600
CTX_REQUEST_BUDGET = 20


def _ctx_decode(raw):
    """Check the complete PNG/JPEG stream, then decode every source pixel."""
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("CTX source tile exceeds the bounded image size")
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ("PNG", "JPEG") or image.size != (512, 512):
            raise ValueError("Unexpected CTX source format or dimensions")
        image.verify()
    with Image.open(io.BytesIO(raw)) as image:
        image.load()  # Never enable LOAD_TRUNCATED_IMAGES or fill absent pixels.
        info = image.info.copy()
        mode = "RGBA" if image.mode == "RGBA" or "transparency" in info else "RGB"
        return image.convert(mode), info


def _ctx_png(image, source_level):
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("source_level", str(source_level))
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def _ctx_tile(z, y, x, deadline):
    path = CACHE / "ctx" / f"{z}_{y}_{x}.png"
    if path.exists():
        try:
            raw = path.read_bytes()
            _, info = _ctx_decode(raw)
            source_level = int(info["source_level"])
            if 0 <= source_level <= z and (source_level == z or time.time() - path.stat().st_mtime < CTX_FALLBACK_TTL):
                return raw, source_level
        except (OSError, ValueError, KeyError, SyntaxError):
            pass  # Invalid cache entries are replaced only after a valid decode.
    image = None
    remaining = deadline - time.monotonic()
    if remaining > 0:
        try:
            raw = _fetch(f"{ESRI}/CTX1/MapServer/tile/{z}/{y}/{x}", timeout=min(8, remaining))
            image, _ = _ctx_decode(raw)
            source_level = z
        except (OSError, ValueError, SyntaxError):
            image = None
    if image is None:
        if z == 0:
            raise ValueError("No valid CTX image or coarser source is available")
        # Geographic tile y increases southward, matching image rows. Crop the
        # real parent quadrant before interpolation; never repair missing pixels.
        parent, source_level = _ctx_tile(z - 1, y // 2, x // 2, deadline)
        parent_image, _ = _ctx_decode(parent)
        left, top = (x % 2) * 256, (y % 2) * 256
        image = parent_image.crop((left, top, left + 256, top + 256)).resize((512, 512), Image.Resampling.BILINEAR)
    result = _ctx_png(image, source_level)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{threading.get_ident()}.part")
    temporary.write_bytes(result)
    temporary.replace(path)  # Image and source-level metadata commit atomically.
    return result, source_level


@router.get("/murray/ctx/{z}/{y}/{x}")
def murray_ctx_tile(z: int, y: int, x: int):
    if (not all(isinstance(v, (int, np.integer)) for v in (z, y, x))
            or not 0 <= z <= CTX_MAX_LEVEL or not 0 <= y < 2 ** z or not 0 <= x < 2 ** (z + 1)):
        raise HTTPException(404, "Outside the native CTX geographic tile grid")
    try:
        raw, source_level = _ctx_tile(z, y, x, time.monotonic() + CTX_REQUEST_BUDGET)
    except (OSError, ValueError, SyntaxError) as error:
        raise HTTPException(503, "CTX imagery and its coarser source tiles could not load") from error
    return Response(raw, media_type="image/png", headers={
        "Cache-Control": f"public, max-age={604800 if source_level == z else CTX_FALLBACK_TTL}",
        "X-Imagery-Fallback-Level": str(source_level),
        "X-Imagery-Resolution": "native" if source_level == z else "coarser-source-crop",
    })


def _raw(name):
    """A Murray Lab GeoJSON file, downloaded once."""
    path = CACHE / "raw" / f"{name}.geojson"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(_fetch(f"{FEATURES}/{name}.geojson"))
        tmp.rename(path)
    # The source uses UTF-8 (including IAU names/origins outside Windows' default code page).
    return json.loads(path.read_text(encoding="utf-8"))


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
        # The source's east edge can be 180.0000000000001. Round before wrapping
        # so a 176..180 tile does not acquire a misleading -180..176 bounding box.
        ring = [[_lon(_r(x)), _r(y)] for x, y, *_ in f["geometry"]["coordinates"][0]]
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
            path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return Response(path.read_bytes(), media_type="application/geo+json",
                    headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------ place names ----
_places = None


def place_name(lat, lon):
    """A plain name for a spot from the IAU feature names: the smallest named feature it lies in ("Gale crater"),
    else "Near <nearest feature>". None if the names can't be loaded. Albedo features (telescope-era shading
    names) are skipped."""
    global _places
    if _places is None:
        try:
            murray_features("names")                     # downloads and caches names.geojson once
            feats = json.loads((CACHE / "names.geojson").read_text(encoding="utf-8"))["features"]
        except Exception:
            return None
        rows = []
        for f in feats:
            p = f["properties"]
            kind = (p.get("type") or "")
            if not p.get("name") or kind.startswith("Albedo"):
                continue
            name = p["name"] + (" crater" if kind.startswith("Crater") else "")
            lo, la = f["geometry"]["coordinates"]
            rows.append((la, lo, max(float(p.get("diameter_km") or 0), 1.0) / 2, name))
        if not rows:
            return None
        _places = (np.array([r[0] for r in rows]), np.array([r[1] for r in rows]), np.array([r[2] for r in rows]),
                   [r[3] for r in rows])
    la, lo, rad, names = _places
    p1, p2, dl = math.radians(lat), np.radians(la), np.radians(lo - lon)
    hav = np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    km = 2 * MARS_R / 1000 * np.arcsin(np.sqrt(np.clip(hav, 0, 1)))
    inside = np.flatnonzero(km <= rad)
    if inside.size:
        return names[int(inside[np.argmin(rad[inside])])]
    return "Near " + names[int(np.argmin(km - rad))]


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


def _footprint_contains(ring, lat, lon):
    """Test the published footprint polygon, including its boundary, in local lon/lat.

    Unwrap longitudes about the point so ordinary footprints across +/-180 still
    work. A bounding-box hit alone does not establish that an image covers a point.
    """
    points = np.asarray(ring, dtype=float)
    if len(points) < 3:
        return False
    xs = np.degrees(np.unwrap(np.radians(points[:, 0])))
    xs -= lon + 360 * round((float(xs.mean()) - lon) / 360)
    ys = points[:, 1] - lat
    inside = False
    x1, y1 = xs[-1], ys[-1]
    for x2, y2 in zip(xs, ys):
        cross = x1 * y2 - x2 * y1
        if abs(cross) < 1e-10 and min(x1, x2) - 1e-10 <= 0 <= max(x1, x2) + 1e-10 and min(y1, y2) - 1e-10 <= 0 <= max(y1, y2) + 1e-10:
            return True
        if (y1 > 0) != (y2 > 0) and x1 + (x2 - x1) * (-y1) / (y2 - y1) > 0:
            inside = not inside
        x1, y1 = x2, y2
    return inside


@router.get("/murray/hirise")
def murray_hirise(west: float, south: float, east: float, north: float, limit: int = 1500):
    """HiRISE footprints overlapping a box (the page asks for the current view)."""
    if (not all(math.isfinite(v) for v in (west, south, east, north))
            or not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90)
            or not 1 <= limit <= 1500):
        raise HTTPException(422, "Use a valid Mars bounding box and a limit between 1 and 1500.")
    ix = _hirise_index()
    b = ix["boxes"]
    # A view crossing +/-180 has west > east. It covers either side of the dateline,
    # not an empty interval. Keep the index in its original -180..180 coordinate range.
    longitude = ((b[:, 0] <= east) & (b[:, 2] >= west)) if west <= east else ((b[:, 2] >= west) | (b[:, 0] <= east))
    # A narrow polygon straddling the dateline has a misleading ~360-degree cached
    # box. Test its unwrapped longitude extent instead, including both map edges.
    for i in np.flatnonzero((b[:, 2] - b[:, 0] > 180) & (b[:, 1] <= north) & (b[:, 3] >= south)):
        ring = ix["coords"][ix["starts"][i]:ix["starts"][i + 1]]
        xs = np.degrees(np.unwrap(np.radians(ring[:, 0])))
        ranges = [(west, east)] if west <= east else [(west, 180), (-180, east)]
        longitude[i] = any(xs.min() <= e + shift and xs.max() >= w + shift
                           for w, e in ranges for shift in (-360, 0, 360))
    hit = np.nonzero(longitude & (b[:, 1] <= north) & (b[:, 3] >= south))[0]
    return {"type": "FeatureCollection", "total": int(hit.size), "truncated": bool(hit.size > limit),
            "features": [_hirise_feature(ix, i) for i in hit[:limit]]}


@router.get("/murray/hirise/at")
def murray_hirise_at(lat: float, lon: float):
    """HiRISE observations whose published footprint contains the clicked point."""
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(422, "Use latitude -90..90 and longitude -180..180.")
    ix = _hirise_index()
    b = ix["boxes"]
    longitude = ((b[:, 0] <= lon) & (b[:, 2] >= lon)) | ((b[:, 2] - b[:, 0]) > 180)
    candidates = np.nonzero(longitude & (b[:, 1] <= lat) & (b[:, 3] >= lat))[0]
    hit = [i for i in candidates if _footprint_contains(ix["coords"][ix["starts"][i]:ix["starts"][i + 1]], lat, lon)]
    return {"observations": [_hirise_feature(ix, i)["properties"] for i in hit[:20]], "total": len(hit)}


_quad_boxes = None


@router.get("/murray/quad/at")
def murray_quad_at(lat: float, lon: float):
    """The CTX mosaic tile containing a point, with its download page."""
    global _quad_boxes
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(422, "Use latitude -90..90 and longitude -180..180.")
    if _quad_boxes is None:
        murray_features("quads")                       # make sure the cache exists
        feats = json.loads((CACHE / "quads.geojson").read_text(encoding="utf-8"))["features"]
        boxes = []
        for f in feats:
            ring = np.asarray(f["geometry"]["coordinates"][0])
            # Also support caches generated before the east-edge rounding fix.
            xs = np.degrees(np.unwrap(np.radians(ring[:, 0])))
            boxes.append((xs.min(), ring[:, 1].min(), xs.max(), ring[:, 1].max(), f["properties"]))
        _quad_boxes = boxes
    for w, s_, e, n, props in _quad_boxes:
        if s_ <= lat <= n and any(w <= lon + shift <= e for shift in (-360, 0, 360)):
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


def _write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.part")
    tmp.write_bytes(data)
    tmp.replace(path)


def _raw_elevation_tile(z, y, x, timeout):
    """The tile exactly as Esri serves it (cached on disk)."""
    path = CACHE / "elevation" / f"{z}_{y}_{x}.lerc"
    if not path.exists():
        _write_atomic(path, _fetch(f"{ESRI}/MDEM200M/ImageServer/tile/{z}/{y}/{x}", timeout=timeout))
    return path.read_bytes()


# About 1 in 6 MDEM200M tiles at levels 4, 5 and 7 hold heights from somewhere else (checked against MOLA:
# kilometres off, e.g. +1.1 km at 7.5N 5.6W where Mars is at -1.4 km), which made patches of the 3D globe
# float above their neighbours with hollow gaps. Every tile is checked against NASA's MOLA MEGDR
# (16 px/degree, 33 MB, downloaded once) and a wrong one is rebuilt from the nearest correct coarser tile.
MOLA_REF_URL = "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg016/megt90n000eb.img"
MOLA_REF_SHAPE = (2880, 5760)            # 90N..90S, 0..360E, 1/16 degree, big-endian int16 metres (areoid)
TILE_MAX_MEDIAN_ERROR_M = 250            # correct tiles stay within ~40 m of MOLA; wrong ones are 1-7 km off
_mola_ref = None
_mola_lock = threading.Lock()


def mola_reference():
    global _mola_ref
    with _mola_lock:
        if _mola_ref is None:
            path = CACHE / "mola_megdr_16ppd.img"
            if not path.exists() or path.stat().st_size != 2 * MOLA_REF_SHAPE[0] * MOLA_REF_SHAPE[1]:
                _write_atomic(path, _fetch(MOLA_REF_URL, timeout=300))
            _mola_ref = np.memmap(path, dtype=">i2", mode="r", shape=MOLA_REF_SHAPE)
    return _mola_ref


def mola_heights(lat, lon):
    """Bilinear MOLA heights (m) at arrays of planetocentric lat / lon (degrees, any longitude range)."""
    from scipy.ndimage import map_coordinates
    ref = mola_reference()
    rows = np.clip((90 - np.asarray(lat, float)) * 16 - 0.5, 0, MOLA_REF_SHAPE[0] - 1)
    cols = (np.asarray(lon, float) % 360) * 16 - 0.5
    c0 = int(np.floor(np.min(cols))) - 1
    r0, r1 = int(np.floor(rows.min())), int(np.ceil(rows.max())) + 1
    cidx = np.arange(c0, int(np.ceil(np.max(cols))) + 2) % MOLA_REF_SHAPE[1]
    window = np.asarray(ref[r0:r1 + 1][:, cidx], dtype="float32")
    return map_coordinates(window, [rows - r0, cols - c0], order=1, mode="nearest", prefilter=False)


def _tile_grid(z, y, x, n):
    w = 180 / 2 ** z
    t = np.linspace(0, 1, n)
    return np.meshgrid(90 - (y + t) * w, -180 + (x + t) * w, indexing="ij")


def _decode_heights(blob):
    import lerc
    code, data, valid = lerc.decode(blob)[:3]
    if code:
        raise ValueError(f"elevation tile failed to decode ({code})")
    data = np.asarray(data, dtype="float32")
    if valid is not None:
        data = np.where(np.asarray(valid) > 0, data, np.nan).astype("float32")
    return data


def _matches_mola(z, y, x, heights):
    lat, lon = _tile_grid(z, y, x, 33)
    idx = np.linspace(0, heights.shape[0] - 1, 33).round().astype(int)
    diff = np.abs(heights[np.ix_(idx, idx)] - mola_heights(lat, lon))
    diff = diff[np.isfinite(diff)]
    return diff.size > 0 and float(np.median(diff)) < TILE_MAX_MEDIAN_ERROR_M


def _lerc2_v3(heights):
    """Uncompressed LERC2 version 3 (the newest layout Cesium's decoder reads; the lerc package writes v6)."""
    import struct
    h, w = heights.shape
    data = np.ascontiguousarray(heights, dtype="<f4")
    zmin, zmax = float(data.min()), float(data.max())
    body = struct.pack("<iiiiiiddd", h, w, h * w, 8, 0, 6, 0.0, zmin, zmax) + struct.pack("<I", 0)
    if zmax > zmin:
        body += b"\x01" + data.tobytes()
    blob_size = 6 + 4 + 4 + len(body)
    body = body[:16] + struct.pack("<i", blob_size) + body[20:]
    a = b = 0xFFFF                                   # Fletcher-32 exactly as LERC computes it
    words = len(body) // 2
    i = 0
    while words:
        n = min(words, 359)
        words -= n
        for _ in range(n):
            a += body[i] << 8
            a += body[i + 1]
            b += a
            i += 2
        a, b = (a & 0xFFFF) + (a >> 16), (b & 0xFFFF) + (b >> 16)
    if len(body) & 1:
        a += body[i] << 8
        b += a
    a, b = (a & 0xFFFF) + (a >> 16), (b & 0xFFFF) + (b >> 16)
    return b"Lerc2 " + struct.pack("<iI", 3, ((b << 16) | a) & 0xFFFFFFFF) + body


def _rebuilt_tile(z, y, x, timeout):
    """A wrong or missing tile, rebuilt from the nearest coarser tile that matches MOLA (else MOLA itself)."""
    from scipy.ndimage import map_coordinates
    for level in range(z - 1, -1, -1):
        f = 2 ** (z - level)
        try:
            parent = _decode_heights(_raw_elevation_tile(level, y // f, x // f, timeout))
        except Exception:
            continue
        span = (parent.shape[0] - 1) / f
        rows = (y % f) * span + np.linspace(0, span, 513)
        cols = (x % f) * span + np.linspace(0, span, 513)
        sub = map_coordinates(parent, np.meshgrid(rows, cols, indexing="ij"), order=1, mode="nearest", prefilter=False)
        if np.isfinite(sub).all() and _matches_mola(z, y, x, sub):
            return sub.astype("float32")
    lat, lon = _tile_grid(z, y, x, 513)
    return mola_heights(lat, lon).astype("float32")


def elevation_tile_bytes(z, y, x, *, timeout=60):
    """One LERC tile of the 3D terrain (MDEM200M), checked against MOLA and cached on disk.
    Shared by the globe and the cube builder."""
    if (not all(isinstance(v, (int, np.integer)) for v in (z, y, x))
            or not 0 <= z <= TERRAIN_MAX_LEVEL
            or not (0 <= y < 2 ** z and 0 <= x < 2 ** (z + 1))):
        raise ValueError("elevation tile outside the published level-0..7 geographic grid")
    z, y, x = int(z), int(y), int(x)
    path = CACHE / "elevation_checked" / f"{z}_{y}_{x}.lerc"
    if path.exists():
        return path.read_bytes()
    try:
        raw = _raw_elevation_tile(z, y, x, timeout)
    except Exception:
        raw = None                                   # Esri sometimes answers 500: rebuild, but don't keep it
    try:
        if raw is not None and _matches_mola(z, y, x, _decode_heights(raw)):
            data = raw
        else:
            data = _lerc2_v3(_rebuilt_tile(z, y, x, timeout))
    except OSError:
        if raw is None:
            raise
        return raw                                   # MOLA reference unreachable: serve the tile unchecked
    if raw is not None:
        _write_atomic(path, data)
    return data


@router.get("/murray/elevation/v2")
@router.get("/murray/elevation/v2/")
def murray_elevation_meta_v2():
    return murray_elevation_meta()


@router.get("/murray/elevation/tile/{z}/{y}/{x}")
@router.get("/murray/elevation/v2/tile/{z}/{y}/{x}")
def murray_elevation_tile(z: int, y: int, x: int):
    try:
        data = elevation_tile_bytes(z, y, x)
    except Exception:
        raise HTTPException(404, "no elevation tile")
    return Response(data, media_type="application/octet-stream", headers={"Cache-Control": "public, max-age=604800"})
