"""
Download a rover's real traverse for a region (used for the green / yellow rover-track layer).

    python fetch_tracks.py jezero      -> cubes/jezero_tracks.json

Source: NASA/JPL mission maps (MMGIS) - the drive segments plus the rover's own attitude (tilt) at
each waypoint. JPL does not publish per-drive slip, so mission.py classes a segment as high strain from
the tilt the rover recorded and the terrain it crossed.
"""
import json
import sys
import urllib.request
from pathlib import Path

from config import REGIONS, ROVER_TRACKS

ROOT = Path(__file__).parent


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; mars-cube-builder)"})
    try:
        import certifi, ssl
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        return json.loads(r.read())


def fetch(region):
    src = ROVER_TRACKS[region]
    r = REGIONS[region]
    inside = lambda lon, lat: r["west"] <= lon <= r["east"] and r["south"] <= lat <= r["north"]
    tilt = {}
    for f in _get_json(src["waypoints"])["features"]:
        p = f["properties"]
        if p.get("RMC") is not None and p.get("tilt") is not None:
            tilt[p["RMC"]] = abs(float(p["tilt"]))
    segments = []
    for f in _get_json(src["traverse"])["features"]:
        coords = [(round(lon, 5), round(lat, 5)) for lon, lat, *_ in f["geometry"]["coordinates"]]
        if not any(inside(lon, lat) for lon, lat in coords):
            continue
        p = f["properties"]
        tilts = [tilt[k] for k in (p.get("fromRMC"), p.get("toRMC")) if k in tilt]
        segments.append({"sol": p.get("sol"), "length_m": round(float(p.get("length") or 0), 1),
                         "tilt_deg": round(max(tilts), 1) if tilts else None, "coords": coords})
    out = {"rover": src["rover"], "source": src["traverse"], "waypoints_source": src["waypoints"],
           "segments": segments}
    path = ROOT / "cubes" / f"{region}_tracks.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    km = sum(s["length_m"] for s in segments) / 1000
    print(f"Saved {path.name}: {src['rover']}, {len(segments)} drive segments, {km:.1f} km")


if __name__ == "__main__":
    fetch(sys.argv[1] if len(sys.argv) > 1 else "jezero")
