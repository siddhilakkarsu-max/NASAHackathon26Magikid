"""
Map notes along a planned route: the cliffs, soft ground and minerals a traveller passes, as pins next to the route.

The spots come from the data cube (slope, thermal inertia / firmness and the CRISM mineral bands) in a corridor
around the route; each note carries plain template text and the facts behind it. The AI model then rewrites the
captions in plain words (captions_stream), streamed like the explanation; the template text is the fallback.
"""
import json

import numpy as np
from scipy.ndimage import binary_dilation, distance_transform_edt, label
from skimage.draw import line as draw_line

import search
from config import MINERALS

CORRIDOR_M = 400          # look this far either side of the route
MIN_GAP_M = 350           # notes closer together than this are merged (the more important one is kept)
MAX_NOTES = 8             # per route, so the map stays readable
CLIFF_DEG = 25.0          # labelled a cliff from this slope; anything the vehicle can't climb is a steep slope
SOFT_TI = 200.0           # thermal inertia below this on the route: soft sand / dust (landing rule threshold)


def _route_masks(cube, pts):
    """(pixels the route crosses, the corridor around it, metres from each pixel to the route)."""
    route = np.zeros((cube.H, cube.W), bool)
    rc = []
    for p in pts:
        r = int((cube.n - p["lat"]) / (cube.n - cube.s) * cube.H)
        c = int((p["lon"] - cube.w) / (cube.e - cube.w) * cube.W)
        rc.append((min(max(r, 0), cube.H - 1), min(max(c, 0), cube.W - 1)))
    for (r0, c0), (r1, c1) in zip(rc, rc[1:] or rc):
        rr, cc = draw_line(r0, c0, r1, c1)
        route[rr, cc] = True
    px = float(np.mean(cube.pixel_m))
    dist = distance_transform_edt(~route) * px
    corridor = binary_dilation(route, iterations=max(1, int(round(CORRIDOR_M / px))))
    return route, corridor, dist


def _where_on_route(pts, lat, lon):
    """(km along the route of the nearest route point, 'left'/'right'/'on the route' seen in the travel direction)."""
    k = min(range(len(pts)), key=lambda i: (pts[i]["lat"] - lat) ** 2 + ((pts[i]["lon"] - lon) * np.cos(np.radians(lat))) ** 2)
    a, b = pts[max(k - 1, 0)], pts[min(k + 1, len(pts) - 1)]
    cross = (b["lon"] - a["lon"]) * (lat - a["lat"]) - (b["lat"] - a["lat"]) * (lon - a["lon"])
    return float(pts[k].get("d", 0.0)), ("left" if cross > 0 else "right")


def _components(mask, value, n):
    """Up to n connected patches of mask, strongest first: [(value, row, col, size_px)] at each patch's peak."""
    lab, count = label(mask)
    if not count:
        return []
    out = []
    v = np.where(mask, np.nan_to_num(value, nan=-np.inf), -np.inf)
    for i in range(1, count + 1):
        idx = np.flatnonzero(lab == i)
        j = idx[np.argmax(v.flat[idx])]
        out.append((float(v.flat[j]), *np.unravel_index(j, mask.shape), idx.size))
    return sorted(out, key=lambda t: -t[0])[:n]


def route_notes(cube, cand, v):
    """Notes for one mission candidate (cand["route"]["points"]) and vehicle spec v: a list of
    {id, kind, lat, lon, label, detail, facts}; kind is cliff / steep / soft / mineral."""
    pts = cand["route"]["points"]
    if len(pts) < 2:
        return []
    b = cube.bands
    route, corridor, dist = _route_masks(cube, pts)
    slope = np.nan_to_num(b["slope"], nan=0.0)
    notes = []

    def add(kind, r, c, label_, detail, prio, **facts):
        lat, lon = cube.latlon(r, c)
        at_km, side = _where_on_route(pts, lat, lon)
        off = float(dist[r, c])
        facts.update(km_along_route=round(at_km, 2), distance_from_route_m=round(off),
                     side=("on the route" if off < 60 else side))
        notes.append(dict(kind=kind, lat=round(lat, 5), lon=round(lon, 5), label=label_, detail=detail,
                          prio=prio, facts=facts))

    # ground too steep for the vehicle near the route (cliffs from CLIFF_DEG): the steepest point of each patch
    thr = v["max_slope"]
    for mx, r, c, size in _components(corridor & (slope >= thr), slope, 3):
        word = "Cliff" if mx >= CLIFF_DEG else "Steep slope"
        add("cliff", r, c, f"{word} ({mx:.0f}°)", f"slope {mx:.0f}° (vehicle limit {thr:.0f}°), {size} px patch",
            0, slope_deg=round(mx), what_it_is=word.lower(), vehicle_limit_deg=thr)
    # the steepest stretch the route itself climbs, if it is notable
    on = np.where(route, slope, -1.0)
    r, c = np.unravel_index(np.argmax(on), on.shape)
    if on[r, c] >= 0.6 * v["max_slope"]:
        add("steep", r, c, f"Steepest climb: {on[r, c]:.0f}°", f"route slope {on[r, c]:.0f}° "
            f"(vehicle limit {v['max_slope']:.0f}°)", 3, slope_deg=round(float(on[r, c])),
            vehicle_limit_deg=v["max_slope"])
    # soft ground the route crosses
    ti = b.get("thermal_inertia")
    if ti is not None:
        soft = route & (np.nan_to_num(ti, nan=1e9) < SOFT_TI)
        for neg, r, c, size in _components(soft, -np.nan_to_num(ti, nan=1e9), 2):
            length = size * float(np.mean(cube.pixel_m))
            add("soft", r, c, f"Soft sand (~{length:.0f} m)", f"thermal inertia {-neg:.0f} (< {SOFT_TI:.0f}) "
                f"over ~{length:.0f} m of route", 2, length_m=round(length), thermal_inertia=round(-neg))
    # minerals in the corridor: the strongest spot of each mineral
    for name, m in MINERALS.items():
        if name not in b:
            continue
        band = b[name]
        hits = _components(corridor & (np.nan_to_num(band, nan=-1) >= m["detect"]), band, 1)
        for val, r, c, size in hits:
            strength = search.mineral_strength(name, val).split(" ")[0]
            add("mineral", r, c, f"{m['label'].capitalize()} ({strength})", f"{m['science']}: "
                f"{'/'.join(m['params'])} {val:.3f}, {size} px", 1, mineral=m["label"], signal=strength)

    # keep the most important notes, spaced out
    kept = []
    for n in sorted(notes, key=lambda n: n["prio"]):
        far = all(((n["lat"] - k["lat"]) ** 2 + ((n["lon"] - k["lon"]) * np.cos(np.radians(n["lat"]))) ** 2) ** 0.5
                  * 59274 >= MIN_GAP_M for k in kept)
        if far:
            kept.append(n)
        if len(kept) == MAX_NOTES:
            break
    for i, n in enumerate(kept):
        n["id"] = f"{cand['rank']}-{i}"
        n.pop("prio")
    return kept


CAPTION_SYSTEM = (
    "You write the labels for pins on a map of a planned Mars trip, for people with no science background. "
    "For every item write one label of at most 7 words that says what is there and, when it helps, what to do "
    "about it, e.g. 'Cliff on your left, stay clear', 'Clay here: good sample spot', 'Soft sand ahead, go "
    "slowly'. Use the side and distance facts; use only the facts given; no jargon (no 'thermal inertia', "
    "'CRISM', 'band'). Answer only with JSON: {\"labels\": {\"<id>\": \"<label>\", ...}} with every id.")


def captions_stream(notes, goal, vehicle):
    """Stream the AI model writing plain captions for notes: yields ai_stream's ("reasoning"|"content", text)
    pieces, then ("labels", {id: caption}) or ("error", reason)."""
    if not notes:
        return
    items = [dict(id=n["id"], what=n["kind"], **n["facts"]) for n in notes]
    msgs = [{"role": "system", "content": CAPTION_SYSTEM},
            {"role": "user", "content": json.dumps({"goal": goal, "vehicle": vehicle, "items": items})}]
    fmt = {"type": "json_schema", "json_schema": {"name": "map_labels", "strict": False, "schema": {
        "type": "object", "properties": {"labels": {"type": "object", "additionalProperties": {"type": "string"}}},
        "required": ["labels"]}}}
    for event in search.ai_stream(msgs, response_format=fmt, max_tokens=2500, think_seconds=10):
        if event[0] == "done":
            try:
                labels = search._json_object(event[1] or "")["labels"]
                ids = {n["id"] for n in notes}
                yield ("labels", {k: str(t).strip()[:80] for k, t in labels.items() if k in ids and str(t).strip()})
            except (ValueError, KeyError, TypeError, AttributeError):
                yield ("error", "the AI's labels could not be read")
            return
        yield event
