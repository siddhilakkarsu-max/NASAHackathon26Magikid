"""
Text search for a navigation target: "valley with clay", "flat firm ground near a cliff", ...

1. The query is turned into criteria (valley, clay, flat, ...), each optionally negated
   ("without sand") or made a proximity ("near a cliff").
2. Each criterion becomes a per-pixel score 0..1 computed from the cube + current conditions.
3. Scores are combined with a weighted geometric mean (a soft AND) and the best,
   well-separated, passable pixels are returned as candidate targets.

Parsing: the built-in keyword parser below needs no network. If the query has words it does not
know and OPENROUTER_API_KEY is set, a free AI model on OpenRouter translates the query into the same
criteria; otherwise the unknown words are reported back.

To teach the search a new word, add it to a feature's "words" in FEATURES.
Minerals (clay, carbonate, olivine, ...) come from CRISM bands in the cube (see config.MINERALS for
the parameters and detection thresholds); where a region has no such band, the approximate zones in
config.SEARCH_ZONES are used instead.
"""
import json
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.request

import numpy as np
from scipy.ndimage import distance_transform_edt, uniform_filter

from config import MARS_RADIUS_M, MINERALS

DEG_M = math.pi / 180 * MARS_RADIUS_M      # meters per degree of latitude


class Unavailable(Exception):
    """This criterion cannot be computed for this cube / these conditions."""


def ramp(a, lo, hi):
    """0 at lo, 1 at hi, linear between (lo > hi gives a falling ramp)."""
    return np.clip((a - lo) / (hi - lo if hi != lo else 1e-9), 0, 1).astype("float32")


def sigmoid(x):
    return (1 / (1 + np.exp(-x))).astype("float32")


def pct(a, q):
    finite = a[np.isfinite(a)]
    return np.percentile(finite, q) if finite.size else np.zeros(np.size(q))


# ------------------------------------------------------------- context ----
class Ctx:
    """Everything a feature needs: the cube, the current conditions and a cache for slow arrays."""

    def __init__(self, cube, vehicle, sun_elev, illum, temp, cost, t_base=None, usable_s=None, zones=()):
        self.cube, self.v, self.sun_elev = cube, vehicle, sun_elev
        self.illum, self.temp, self.cost = illum, temp, cost
        self.t_base, self.usable_s, self.zones = t_base, usable_s, list(zones)
        self.notes = []

    def band(self, name):
        if name not in self.cube.bands:
            raise Unavailable(f"the cube has no '{name}' band")
        return self.cube.bands[name]

    def cached(self, key, make):
        """Arrays that only depend on the cube are computed once per cube."""
        store = self.cube.__dict__.setdefault("_search_cache", {})
        if key not in store:
            store[key] = make()
        return store[key]

    def tpi(self):
        """Topographic position: how much higher/lower each pixel is than the land around it.
        Returns (z-score averaged over ~0.75 km and ~3 km neighbourhoods, meters vs ~3 km)."""
        def make():
            elev = self.band("elevation").astype("float64")
            elev = np.where(np.isfinite(elev), elev, np.nanmean(elev))
            px = math.sqrt(self.cube.pixel_m[0] * self.cube.pixel_m[1])
            zs, diff = [], None
            for radius_m in (750, 3000):
                k = max(3, int(round(2 * radius_m / px)) | 1)
                diff = elev - uniform_filter(elev, k, mode="nearest")
                zs.append(diff / (diff.std() + 1e-6))
            return (sum(zs) / len(zs)).astype("float32"), diff.astype("float32")
        return self.cached("tpi", make)

    def distance_m(self, mask):
        """Meters from every pixel to the nearest True pixel of mask."""
        return distance_transform_edt(~mask, sampling=self.cube.pixel_m).astype("float32")

    def zone_distance_km(self, z):
        """km from every pixel to the edge of a circular zone (<= 0 inside)."""
        c = self.cube
        lat = (c.n - (np.arange(c.H) + 0.5) * (c.n - c.s) / c.H)[:, None]
        lon = (c.w + (np.arange(c.W) + 0.5) * (c.e - c.w) / c.W)[None, :]
        dy = (lat - z["lat"]) * DEG_M
        dx = (lon - z["lon"]) * DEG_M * math.cos(math.radians(z["lat"]))
        return (np.hypot(dy, dx) / 1000 - z["radius_km"]).astype("float32")


# ------------------------------------------------------------ features ----
# Each returns (score array 0..1, explain(r, c) -> short text about that pixel).
def f_valley(ctx):
    z, d = ctx.tpi()
    return sigmoid(-2.5 * (z + 0.75)), lambda r, c: f"{abs(d[r, c]):.0f} m {'below' if d[r, c] < 0 else 'above'} the land around it"


def f_ridge(ctx):
    z, d = ctx.tpi()
    return sigmoid(2.5 * (z - 0.75)), lambda r, c: f"{abs(d[r, c]):.0f} m {'above' if d[r, c] > 0 else 'below'} the land around it"


def _slope_text(s):
    return lambda r, c: f"slope {s[r, c]:.1f}°"


def f_flat(ctx):
    s = ctx.band("slope")
    return 1 - ramp(s, 2, 10), _slope_text(s)


def f_steep(ctx):
    s = ctx.band("slope")
    return ramp(s, 8, 25), _slope_text(s)


def f_smooth(ctx):
    rough = ctx.band("roughness")
    lo, hi = pct(rough, [40, 90])
    return 1 - ramp(rough, lo, hi), lambda r, c: f"roughness {rough[r, c]:.1f} m"


def f_rough(ctx):
    rough = ctx.band("roughness")
    lo, hi = pct(rough, [50, 95])
    return ramp(rough, lo, hi), lambda r, c: f"roughness {rough[r, c]:.1f} m"


def ti_class(ti):
    """THEMIS thermal inertia (J m^-2 K^-1 s^-1/2) -> likely surface material."""
    return ("fine dust" if ti < 150 else "sand" if ti < 300 else "coarse sand / crusted / mixed rock" if ti < 600
            else "bedrock / rock-rich")


def ground_text(cube, r, c):
    ti = cube.bands.get("thermal_inertia")
    if ti is not None and np.isfinite(ti[r, c]):
        return f"thermal inertia {ti[r, c]:.0f} ({ti_class(ti[r, c])}), firmness {cube.bands['firmness'][r, c]:.2f}"
    return f"firmness {cube.bands['firmness'][r, c]:.2f} (THEMIS night-IR proxy)"



def f_firm(ctx):
    f = ctx.band("firmness")
    return ramp(f, 0.45, 0.85), lambda r, c: ground_text(ctx.cube, r, c)


def f_sand(ctx):
    f = ctx.band("firmness")
    return 1 - ramp(f, 0.15, 0.5), lambda r, c: ground_text(ctx.cube, r, c)


def f_sunny(ctx):
    if ctx.sun_elev <= 0:
        raise Unavailable("the sun is below the horizon at this time of day")
    i = ctx.illum
    return ramp(i, 0.3, 0.9), lambda r, c: f"sunlight cos(i) {max(float(i[r, c]), 0):.2f}"


def f_shade(ctx):
    i = ctx.illum
    if ctx.sun_elev <= 0:
        ctx.notes.append("shadow: the sun is down, so everywhere is dark right now")
    return 1 - ramp(i, 0.05, 0.5), lambda r, c: f"sunlight cos(i) {max(float(i[r, c]), 0):.2f}"


def f_warm(ctx):
    t = ctx.temp
    lo, hi = pct(t, [20, 90])
    return ramp(t, lo, hi), lambda r, c: f"~{t[r, c]:.0f} K (approx.)"


def f_cold(ctx):
    t = ctx.temp
    lo, hi = pct(t, [10, 80])
    return 1 - ramp(t, lo, hi), lambda r, c: f"~{t[r, c]:.0f} K (approx.)"


def f_shelter(ctx):
    wall = ctx.v["max_slope"] + 2      # same rule as the "Minutes to shelter" layer
    steep = np.nan_to_num(ctx.band("slope")) >= wall
    if not steep.any():
        raise Unavailable(f"no walls steeper than {wall:.0f}° in this region")
    d = ctx.cached(("wall_dist", wall), lambda: ctx.distance_m(steep))
    return np.exp(-d / 600).astype("float32"), lambda r, c: f"{d[r, c]:.0f} m from a wall steeper than {wall:.0f}°"


def _elev_text(e):
    return lambda r, c: f"elevation {e[r, c]:.0f} m"


def f_low(ctx):
    e = ctx.band("elevation")
    lo, hi = pct(e, [5, 60])
    return 1 - ramp(e, lo, hi), _elev_text(e)


def f_high(ctx):
    e = ctx.band("elevation")
    lo, hi = pct(e, [40, 95])
    return ramp(e, lo, hi), _elev_text(e)


def f_easy(ctx):
    cost = ctx.cost
    lc = np.log(np.where(np.isfinite(cost), cost, np.nan))
    lo, hi = pct(lc, [10, 90])
    return 1 - ramp(np.nan_to_num(lc, nan=hi), lo, hi), lambda r, c: f"travel cost {cost[r, c]:.1f} s/m"


def f_near_base(ctx):
    if ctx.t_base is None:
        raise Unavailable("set a base first")
    t = ctx.t_base
    scale = max(ctx.usable_s / 4, 600)
    m = np.exp(-np.nan_to_num(t, nan=np.inf, posinf=np.inf) / scale).astype("float32")
    return m, lambda r, c: f"{t[r, c] / 60:.0f} min from base"


def mineral_strength(name, value):
    """Words for a CRISM band depth: below detection / weak / clear / strong."""
    m = MINERALS[name]
    if not np.isfinite(value):
        return "no CRISM data here"
    if value < m["detect"]:
        return f"{'/'.join(m['params'])} {value:.3f}, below detection"
    word = "weak" if value < (m["detect"] + m["strong"]) / 2 else "clear" if value < m["strong"] else "strong"
    return f"{word} ({'/'.join(m['params'])} {value:.3f})"


def _mineral_band(ctx, name):
    """0..1 per pixel from a CRISM band: 0 below the detection limit, 1 at a strong signature."""
    m, arr = MINERALS[name], ctx.cube.bands[name]
    detected = int((np.nan_to_num(arr, nan=-1e9) >= m["detect"]).sum())
    if detected < 10:
        raise Unavailable(f"CRISM shows no {m['label']} in this region ({detected} isolated pixels above the "
                          "detection limit)")
    covered = float(np.isfinite(arr).mean())
    if covered < 0.95:
        ctx.notes.append(f"{name}: CRISM covers {covered:.0%} of this region; places without data can't match.")
    return np.nan_to_num(ramp(arr, m["detect"], m["strong"]), nan=0.0), \
        lambda r, c: mineral_strength(name, arr[r, c])


def f_any_mineral(ctx):
    names = [n for n in MINERALS if n in ctx.cube.bands and n != "hydrated"]
    if not names:
        raise Unavailable("the cube has no CRISM mineral bands")
    scores = np.stack([np.nan_to_num(ramp(ctx.cube.bands[n], MINERALS[n]["detect"], MINERALS[n]["strong"]))
                       for n in names])
    best = np.argmax(scores, axis=0)

    def explain(r, c):
        n = names[best[r, c]]
        return f"{MINERALS[n]['label']}: {mineral_strength(n, ctx.cube.bands[n][r, c])}"
    return scores.max(axis=0), explain


def material(tag, band_names):
    """A mineral/place: a cube band if one exists, else hint zones from config."""
    def fn(ctx):
        for b in band_names:
            if b in ctx.cube.bands:
                if b in MINERALS:
                    return _mineral_band(ctx, b)
                arr = ctx.cube.bands[b]
                lo, hi = pct(arr, [50, 98])
                return ramp(arr, lo, hi), lambda r, c: f"{b} band = {arr[r, c]:.3g}"
        zones = [z for z in ctx.zones if tag in z["tags"]]
        if not zones:
            raise Unavailable(f"no '{tag}' band in this cube and no '{tag}' zone in config.SEARCH_ZONES")
        dists = [ctx.zone_distance_km(z) for z in zones]
        near_i = np.argmin(np.stack(dists), axis=0)
        dmin = np.min(np.stack(dists), axis=0)
        # 1 inside the zone, fading to ~0 one radius outside it
        radius = np.array([z["radius_km"] for z in zones])[near_i]
        m = np.where(dmin <= 0, 1.0, np.exp(-(dmin / (0.5 * radius)) ** 2)).astype("float32")
        ctx.notes.append(f"{tag}: the cube has no '{tag}' band yet, so this uses the approximate zone "
                         + ", ".join(f"'{z['name']}' ({z['source']})" for z in zones))

        def explain(r, c):
            z = zones[near_i[r, c]]
            d = dmin[r, c]
            if d <= 0:
                return f"inside zone '{z['name']}' (approx.)"
            return f"at the edge of zone '{z['name']}'" if d < 0.15 else f"{d:.1f} km outside zone '{z['name']}'"
        return m, explain
    return fn


FEATURES = {
    "valley": dict(label="valley / channel", help="valleys, channels, dry riverbeds, where water flowed: lower than the land around it", fn=f_valley, words=[
        "valley", "vallis", "valles", "channel", "canyon", "gully", "gulley", "ravine", "trough", "depression",
        "hollow", "ditch", "riverbed", "river bed", "streambed", "stream bed", "wash", "wadi", "river", "stream",
        "drainage", "dry river", "low spot", "inlet", "outlet"]),
    "ridge": dict(label="ridge / high point", help="ridges, hills, viewpoints: higher than the land around it", fn=f_ridge, words=[
        "ridge", "crest", "hill", "hilltop", "peak", "summit", "mound", "knob", "butte", "mesa", "high point",
        "high ground", "rise", "overlook", "vantage", "vantage point", "viewpoint", "view", "lookout", "top",
        "rim", "crater rim"]),
    "flat": dict(label="flat ground", help="slope under ~2-10 degrees", fn=f_flat, words=[
        "flat", "flats", "level", "plain", "plains", "gentle", "low slope", "gentle slope", "shallow slope",
        "horizontal", "landing zone", "landing pad"]),
    "steep": dict(label="steep slope / cliff", help="slope over ~8-25 degrees", fn=f_steep, words=[
        "steep", "slope", "sloped", "sloping", "hillside", "incline", "inclined", "cliff", "scarp", "escarpment",
        "wall", "bluff", "ledge", "precipice", "steep slope", "crater wall"]),
    "smooth": dict(label="smooth ground", help="low small-scale roughness", fn=f_smooth, words=[
        "smooth", "even", "boulder free"]),
    "rough": dict(label="rough / rocky ground", help="high small-scale roughness", fn=f_rough, words=[
        "rough", "rugged", "bumpy", "boulder", "boulder field", "jagged", "broken", "chaotic", "hummocky",
        "rubble", "blocky", "rocky"]),
    "firm": dict(label="firm ground / bedrock", help="high night-time IR (thermal inertia proxy)", fn=f_firm, words=[
        "firm", "solid", "hard", "bedrock", "bed rock", "rock", "outcrop", "compact", "compacted", "stable",
        "packed", "hard packed", "consolidated", "indurated", "rocky"]),
    "sand": dict(label="loose sand / dust", help="low night-time IR (loose material)", fn=f_sand, words=[
        "sand", "sandy", "dune", "ripple", "loose", "dust", "dusty", "soft", "powdery", "unconsolidated",
        "sand trap", "fines"]),
    "sunny": dict(label="in sunlight", help="sunlit at the chosen time and season", fn=f_sunny, words=[
        "sunny", "sunlit", "sunlight", "sun", "lit", "bright", "illuminated", "daylight", "solar", "sun facing"]),
    "shade": dict(label="in shadow", help="facing away from the sun at the chosen time", fn=f_shade, words=[
        "shade", "shaded", "shady", "shadow", "shadowed", "shadowy", "dark", "out of the sun", "out of sun"]),
    "warm": dict(label="warm surface", help="warmer than most of the region (approx. model)", fn=f_warm, words=[
        "warm", "warmer", "hot", "heated"]),
    "cold": dict(label="cold surface", help="colder than most of the region (approx. model)", fn=f_cold, words=[
        "cold", "colder", "cool", "chilly", "freezing", "frigid", "cold trap"]),
    "shelter": dict(label="shelter (foot of a wall)", help="close to a wall too steep for the vehicle",
                    fn=f_shelter, words=[
        "shelter", "sheltered", "cover", "covered", "protected", "protection", "refuge", "hide", "hideout",
        "hiding", "cave", "overhang", "alcove", "lee", "haven", "storm shelter", "dust storm",
        "radiation shelter"]),
    "low": dict(label="low elevation", help="among the lowest ground in the region", fn=f_low, words=[
        "low", "deep", "bottom", "floor", "basin", "low lying", "sunken", "crater floor"]),
    "high": dict(label="high elevation", help="the highest ground in the region, e.g. the crater rim", fn=f_high, words=[
        "high", "elevated", "upland", "uplands", "highland", "highlands", "plateau", "tall", "rim", "crater rim"]),
    "easy": dict(label="easy going", help="safe, easy, quick to travel over for the chosen vehicle", fn=f_easy, words=[
        "easy", "safe", "accessible", "walkable", "drivable", "traversable", "easy going"]),
    "near_base": dict(label="close to base", help="short travel time from the base", fn=f_near_base, words=[
        "base", "home", "habitat", "hab", "lander", "camp", "nearby", "close", "close by", "short walk",
        "short drive", "quick", "reachable", "within reach", "walking distance"]),
    # one feature per mineral in config.MINERALS is added below
    "any_mineral": dict(label="any mineral detection", help="the strongest CRISM mineral signature of any kind",
                        fn=f_any_mineral, words=["mineral", "minerals", "mineralogy", "spectral", "interesting rocks"]),
    "ice": dict(label="water ice / hydrogen", help="subsurface ice or water-equivalent hydrogen (band or hint zone)",
                fn=material("ice", ["ice", "hydrogen", "weh"]), words=[
        "ice", "frost", "hydrogen", "water ice", "ground ice", "glacier"]),
    "delta": dict(label="delta / fan deposit", help="river delta or alluvial fan (hint zone)",
                  fn=material("delta", ["delta"]), words=["delta", "fan", "alluvial fan", "fan delta", "deltaic"]),
}

for _name, _m in MINERALS.items():
    FEATURES[_name] = dict(label=_m["label"], help=f"{_m['label']} from CRISM {'/'.join(_m['params'])} (or hint zone)",
                           fn=material(_name, [_name]), words=_m["words"])

# "the flattest spot" = flat, counted double
SUPERLATIVES = {
    "flattest": "flat", "steepest": "steep", "highest": "high", "tallest": "high", "lowest": "low",
    "deepest": "low", "sunniest": "sunny", "brightest": "sunny", "darkest": "shade", "shadiest": "shade",
    "warmest": "warm", "hottest": "warm", "coldest": "cold", "coolest": "cold", "smoothest": "smooth",
    "roughest": "rough", "firmest": "firm", "hardest": "firm", "sandiest": "sand", "safest": "easy",
    "easiest": "easy", "closest": "near_base", "nearest": "near_base",
}
NEGATE = {"no", "not", "without", "avoid", "avoiding", "except", "non", "never", "nothing"}
NEAR = {"near", "next", "beside", "by", "along", "alongside", "around", "bordering", "adjacent"}
STRONG = {"very", "really", "extremely", "most", "super", "lots", "plenty", "much"}
NEAR_2 = {"next to", "close to", "adjacent to", "near to", "right by"}
NEGATE_NEAR_2 = {"away from", "far from"}
STOP = set("""a an the with and or of to on in at for into onto from find me show get go take i want need
look looking some somewhere something spot spots place places area areas region site location point target
terrain ground surface zone that has have having is are there where which good nice please one any it its can
could we us our my let lets s lot bit rich bearing containing contain contains full exposed exposure deposit
deposits material materials kind interesting type sort little quite fairly too like would should
destination go goes going walk drive travel route facing""".split())

PHRASES = {}
for _key, _f in FEATURES.items():
    for _w in _f["words"]:
        PHRASES.setdefault(tuple(_w.split()), []).append(_key)
for _w, _key in SUPERLATIVES.items():
    PHRASES.setdefault((_w,), []).append(_key)
VOCAB = {t for p in PHRASES for t in p} | NEGATE | NEAR | STRONG | STOP | {"to", "from", "away", "far", "close"}
MAX_PHRASE = max(len(p) for p in PHRASES)


def _lemma(t):
    """Plural -> singular when only the singular is known (gullies -> gully, clays -> clay)."""
    if t in VOCAB:
        return t
    for cut, add in (("ies", "y"), ("es", ""), ("s", "")):
        if t.endswith(cut) and t[: -len(cut)] + add in VOCAB:
            return t[: -len(cut)] + add
    return t


def keyword_parse(query):
    toks = [_lemma(t) for t in re.findall(r"[a-z0-9]+", query.lower())]
    criteria, unknown = [], []
    negate = near = strong = False
    i = 0
    while i < len(toks):
        two = " ".join(toks[i:i + 2])
        if two in NEGATE_NEAR_2:
            negate = near = True; i += 2; continue
        if two in NEAR_2:
            near = True; i += 2; continue
        t = toks[i]
        if t in NEGATE:
            negate = True; i += 1; continue
        if t in NEAR:
            near = True; i += 1; continue
        if t in STRONG:
            strong = True; i += 1; continue
        for n in range(min(MAX_PHRASE, len(toks) - i), 0, -1):
            feats = PHRASES.get(tuple(toks[i:i + n]))
            if feats:
                for f in feats:
                    criteria.append(dict(feature=f, negate=negate, near=near and f != "near_base",
                                         strong=strong or (n == 1 and t in SUPERLATIVES)))
                negate = near = strong = False
                i += n
                break
        else:
            if t not in STOP and not t.isdigit():
                unknown.append(t)
            i += 1
    if near:                                   # "a valley near" / "something near" -> near the base
        criteria.append(dict(feature="near_base", negate=negate, near=False, strong=strong))
    return dict(criteria=_dedupe(criteria), unknown=unknown)


def _dedupe(criteria):
    out = {}
    for cr in criteria:
        k = (cr["feature"], cr["negate"], cr["near"])
        if k in out:
            out[k]["strong"] = out[k]["strong"] or cr["strong"]
        else:
            out[k] = dict(cr)
    return list(out.values())


def describe(cr):
    f = FEATURES[cr["feature"]]
    return ("not " if cr["negate"] else "") + ("near " if cr["near"] else "") + f["label"] + \
        (" (important)" if cr["strong"] else "")


# --------------------------------------------- AI parser (OpenRouter) ----
# Free models on OpenRouter (https://openrouter.ai); needs a free API key in OPENROUTER_API_KEY.
# Free-model limits are per account: 20 requests/min and 50/day (1000/day once $10 of credits has
# been bought). No $0 text model is exempt, so the AI is only asked about queries with words the
# keyword parser doesn't know, and each answer is cached.
# OPENROUTER_MODELS="a:free,b:free" overrides the automatic choice of models (tried in order).
OPENROUTER_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
SERVER = "OpenRouter" if "openrouter.ai" in OPENROUTER_URL else "the AI server at " + OPENROUTER_URL.split("/")[2]
FREE_ROUTER = "openrouter/free"        # OpenRouter's router over its free models: the last fallback
MAX_MODELS = 4
_models_cache = {"at": 0.0, "ids": None}
_llm_cache = {}
_LLM_SYSTEM = """You turn a Mars traverse planner user's description of where they want to go into search \
criteria. Each criterion picks one map feature that is scored for every pixel of the map:

{features}

Per criterion set: negate=true for things to avoid ("without sand", "not steep"); near=true when the place \
should be NEXT TO the feature rather than ON it; strong=true when the user stresses it ("very flat", \
"the flattest"). Use near_base for "close to base/home/camp". Use as few criteria as capture the request. \
Put any part of the request that no feature can express in not_covered, in a few words each.

Example: "flat spot beside a cliff, no sand, I really want sun" ->
{{"criteria": [{{"feature": "flat", "negate": false, "near": false, "strong": false}},
 {{"feature": "steep", "negate": false, "near": true, "strong": false}},
 {{"feature": "sand", "negate": true, "near": false, "strong": false}},
 {{"feature": "sunny", "negate": false, "near": false, "strong": true}}], "not_covered": []}}

Reply with the JSON object only."""


def _llm_schema():
    return {
        "type": "object",
        "properties": {
            "criteria": {"type": "array", "items": {
                "type": "object",
                "properties": {"feature": {"type": "string", "enum": list(FEATURES)},
                               "negate": {"type": "boolean"}, "near": {"type": "boolean"},
                               "strong": {"type": "boolean"}},
                "required": ["feature", "negate", "near", "strong"], "additionalProperties": False}},
            "not_covered": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["criteria", "not_covered"], "additionalProperties": False,
    }


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _http_json(url, body=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        return json.loads(r.read())


def _is_small(model_id):
    """Skip tiny models (e.g. '...-1.7b', 'nano', 'mini'): they follow the schema poorly."""
    name = model_id.split("/")[-1].lower()
    sizes = [float(x) for x in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)b(?![a-z0-9])", name)]
    if sizes:                              # an explicit size wins: "nano-30b-a3b" is not small
        return max(sizes) < 8
    return bool(re.search(r"nano|mini|small|tiny", name))


def free_models():
    """Free text models to try, best first. The free lineup changes often, so it is read from
    OpenRouter's public model list (cached for an hour) unless OPENROUTER_MODELS is set."""
    env = os.environ.get("OPENROUTER_MODELS", "").strip()
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    if _models_cache["ids"] and time.time() - _models_cache["at"] < 3600:
        return _models_cache["ids"]
    try:
        data = _http_json(f"{OPENROUTER_URL}/models", timeout=15)["data"]
    except (OSError, ValueError, KeyError, TypeError):
        data = []
    ranked = []
    for m in data:
        mid, params = m.get("id", ""), set(m.get("supported_parameters") or [])
        # Only ":free" ids: the untagged $0 entries are billed per item (e.g. music generation).
        if not mid.endswith(":free") or (m.get("architecture") or {}).get("output_modalities") != ["text"]:
            continue
        if not params & {"response_format", "structured_outputs"} or _is_small(mid):
            continue
        if (m.get("reasoning") or {}).get("mandatory"):    # can't switch thinking off: slow for this job
            continue
        ranked.append(("structured_outputs" in params, m.get("created") or 0, mid))
    ids = [mid for *_, mid in sorted(ranked, reverse=True)][:MAX_MODELS - 1] + [FREE_ROUTER]
    # remember a failed lookup for 5 minutes only
    _models_cache.update(at=time.time() - (0 if ranked else 3300), ids=ids)
    return ids


def _json_object(text):
    """The JSON object in a reply, tolerating code fences or text around it."""
    try:
        return json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        return json.loads(text[a:b + 1]) if 0 <= a < b else None


AI_REASONING = os.environ.get("AI_REASONING", "low")   # thinking effort when the page streams it ("none" = off)
# Some models think for minutes on a short job; after this many seconds of thinking without an answer the
# stream stops them and asks for the answer straight away, passing along the notes made so far.
AI_THINK_SECONDS = float(os.environ.get("AI_THINK_SECONDS", "40"))
FAIL = "so only built-in words were used"


def _parse_messages(query):
    features = "\n".join(f"- {k}: {f['label']} ({f['help']})" for k, f in FEATURES.items())
    return [{"role": "system", "content": _LLM_SYSTEM.format(features=features)}, {"role": "user", "content": query}]


def _parse_format():
    return {"type": "json_schema", "json_schema": {"name": "search_criteria", "strict": True, "schema": _llm_schema()}}


def _spec_from_text(text, model):
    """The model's JSON answer -> spec; raises ValueError if it can't be read."""
    try:
        data = _json_object(text or "")
        criteria = [dict(feature=c["feature"], negate=bool(c.get("negate")),
                         near=bool(c.get("near")) and c["feature"] != "near_base",   # already a distance
                         strong=bool(c.get("strong"))) for c in data["criteria"] if c.get("feature") in FEATURES]
        unknown = [str(x) for x in data.get("not_covered", [])]
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"The AI model's answer could not be read, {FAIL}.") from e
    return dict(criteria=_dedupe(criteria), unknown=unknown, model=model)


def _error_text(e):
    """A short, user-facing reason for a failed AI request."""
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 401:
            return f"OPENROUTER_API_KEY was rejected, {FAIL}."
        if e.code == 429:
            return (f"Free AI model limit reached (20/min, 50/day; 1000/day after buying $10 of OpenRouter credits), "
                    f"{FAIL}.")
        return f"{SERVER} returned error {e.code}, {FAIL}."
    if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
        return f"The AI model stopped answering for too long, {FAIL}."
    return f"Could not reach {SERVER}, {FAIL}."


def _no_key():
    return "Set OPENROUTER_API_KEY (free at openrouter.ai) to let a free AI model read words the search doesn't know."


def ai_parse(query):
    """Ask a free OpenRouter model to map a free-form query onto FEATURES (no streaming, thinking off: fast).
    Returns (spec, None) or (None, reason it could not)."""
    key = query.strip().lower()
    if key in _llm_cache:
        return _llm_cache[key], None
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None, _no_key()
    models = free_models()
    body = {
        "model": models[0],
        "models": models,                                # OpenRouter tries these in order if one fails
        "messages": _parse_messages(query),
        "response_format": _parse_format(),
        "provider": {"require_parameters": True},       # only providers that enforce the schema
        "reasoning": {"effort": "none"},                # a short lookup: thinking made it 3-8x slower, no better
        "max_tokens": 3000,
    }
    try:
        resp = _http_json(f"{OPENROUTER_URL}/chat/completions", body,
                          {"Authorization": f"Bearer {api_key}"}, timeout=40)
    except (OSError, ValueError) as e:                  # HTTPError, URLError, timeout, bad JSON
        return None, _error_text(e)
    if resp.get("error"):
        return None, f"{SERVER} error: {resp['error'].get('message', 'unknown')}, {FAIL}."
    message = ((resp.get("choices") or [{}])[0].get("message") or {})
    try:
        spec = _spec_from_text(message.get("content"), resp.get("model") or models[0])
    except ValueError as e:
        return None, str(e)
    _llm_cache[key] = spec
    return spec, None


def ai_write(system, user, max_tokens=600):
    """Free text from the same AI model as ai_parse (OpenRouter or a local server); None if unavailable."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None
    models = free_models()
    body = {"model": models[0], "models": models, "max_tokens": max_tokens, "reasoning": {"effort": "none"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    try:
        resp = _http_json(f"{OPENROUTER_URL}/chat/completions", body, {"Authorization": f"Bearer {api_key}"}, timeout=40)
    except (OSError, ValueError):
        return None
    text = (((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    return text or None


def ai_stream(messages, response_format=None, max_tokens=4000, reasoning=None, think_seconds=None):
    """Stream an answer with the model's thinking. Yields ("reasoning", text) and ("content", text) pieces as
    they arrive, then ("done", full_answer, model) - or ("error", reason) if it fails. Thinking is cut off after
    think_seconds (default AI_THINK_SECONDS) without an answer; the answer is then asked for without thinking."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        yield ("error", _no_key())
        return
    models = free_models()
    effort = reasoning or AI_REASONING
    body = {"model": models[0], "models": models, "messages": messages, "stream": True, "max_tokens": max_tokens,
            "reasoning": {"effort": effort}}
    if response_format:
        body.update(response_format=response_format, provider={"require_parameters": True})
    req = urllib.request.Request(f"{OPENROUTER_URL}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream",
                                          "Authorization": f"Bearer {api_key}"})
    budget = AI_THINK_SECONDS if think_seconds is None else think_seconds
    parts, thoughts, model, t_think, cut = [], [], models[0], None, False
    try:
        with urllib.request.urlopen(req, timeout=90, context=_ssl_ctx()) as r:   # 90 s max between pieces
            for raw in r:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue                            # blank lines and ": keep-alive" comments
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("error"):
                    yield ("error", f"{SERVER} error: {chunk['error'].get('message', 'unknown')}, {FAIL}.")
                    return
                model = chunk.get("model") or model
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    thought = delta.get("reasoning") or delta.get("reasoning_content")
                    if thought:
                        thoughts.append(thought)
                        t_think = t_think or time.time()
                        yield ("reasoning", thought)
                    if delta.get("content"):
                        parts.append(delta["content"])
                        yield ("content", delta["content"])
                if budget and not parts and t_think and time.time() - t_think > budget:
                    cut = True                          # closing the connection makes the server stop
                    break
    except (OSError, ValueError) as e:
        yield ("error", _error_text(e))
        return
    if cut:
        yield ("reasoning", f"\n\n[Thinking stopped after {budget:.0f} s; answering from these notes.]")
        notes = "".join(thoughts)[-6000:]
        yield from ai_stream(messages + [{"role": "user", "content": f"Your notes so far:\n{notes}\n\n"
                                          "Now give only the final answer."}],
                             response_format, max_tokens, reasoning="none", think_seconds=0)
        return
    yield ("done", "".join(parts), model)


def ai_parse_stream(query):
    """ai_parse, streamed with the model's thinking: yields ("reasoning"|"content", text) pieces, then
    ("spec", spec) or ("error", reason)."""
    key = query.strip().lower()
    if key in _llm_cache:
        yield ("spec", _llm_cache[key])
        return
    for event in ai_stream(_parse_messages(query), response_format=_parse_format()):
        if event[0] == "done":
            try:
                spec = _spec_from_text(event[1], event[2])
            except ValueError as e:
                yield ("error", str(e))
                return
            _llm_cache[key] = spec
            yield ("spec", spec)
            return
        yield event
        if event[0] == "error":
            return


# -------------------------------------------------------------- search ----
def _near(ctx, m, label):
    feature = m >= 0.5
    if not feature.any():
        feature = m >= np.percentile(m, 98)
    d = ctx.distance_m(feature)
    return np.exp(-d / 750).astype("float32"), \
        lambda r, c: f"on {label}" if d[r, c] < 1 else f"{d[r, c]:.0f} m from {label}"


def score_map(ctx, criteria):
    """Weighted geometric mean of all computable criteria. Returns (score or None, [(criterion, explain)])."""
    total, wsum, parts = None, 0.0, []
    for cr in criteria:
        f = FEATURES[cr["feature"]]
        try:
            m, explain = f["fn"](ctx)
        except Unavailable as e:
            ctx.notes.append(f"{describe(cr)}: skipped, {e}")
            continue
        m = np.nan_to_num(m, nan=0.0)
        if cr["near"]:
            m, explain = _near(ctx, m, f["label"])
        if cr["negate"]:
            m = 1 - m
        w = 2.0 if cr["strong"] else 1.0
        term = w * np.log(np.clip(m, 0.01, 1.0))
        total = term if total is None else total + term
        wsum += w
        parts.append((cr, explain))
    if total is None:
        return None, parts
    return np.exp(total / wsum).astype("float32"), parts


def pick_peaks(score, allowed, pixel_m, count, bias=None, sep_m=2000):
    """Best pixels, at least sep_m apart, among allowed pixels. bias (0..1 per pixel) only
    affects the ranking, e.g. to break ties in favour of places near where the user is looking."""
    px = math.sqrt(pixel_m[0] * pixel_m[1])
    s = np.where(allowed, score, 0.0)
    k = int(round(300 / px)) | 1                       # smooth over ~300 m so single noisy pixels don't win
    if k > 1:
        s = uniform_filter(s, k)
    rank = np.where(allowed, s if bias is None else s * bias, -1.0)
    sr, sc = max(2, int(sep_m / pixel_m[0])), max(2, int(sep_m / pixel_m[1]))
    out = []
    for _ in range(count):
        r, c = np.unravel_index(int(np.argmax(rank)), rank.shape)
        if rank[r, c] < 0.05:
            break
        h = k // 2                                     # the best actual pixel inside the smoothing window
        win = np.where(allowed[max(0, r - h):r + h + 1, max(0, c - h):c + h + 1],
                       score[max(0, r - h):r + h + 1, max(0, c - h):c + h + 1], -1.0)
        dr, dc = np.unravel_index(int(np.argmax(win)), win.shape)
        out.append((int(max(0, r - h) + dr), int(max(0, c - h) + dc), float(s[r, c])))
        rank[max(0, r - sr):r + sr + 1, max(0, c - sc):c + sc + 1] = -1.0
    return out


def find(ctx, query, count=5, use_llm=True, focus=None):
    """focus: (lat, lon) the user cares about (base or view centre); equal matches closer to it win."""
    spec, parser = keyword_parse(query), "keywords"
    if use_llm and (spec["unknown"] or not spec["criteria"]):
        llm, why = ai_parse(query)
        if llm and llm["criteria"]:
            spec, parser = llm, "ai"
        elif why:
            ctx.notes.append(why)
    if not spec["criteria"]:
        raise ValueError(f"No terrain words recognised in '{query}'. Try e.g. 'valley with clay', "
                         "'flat firm ground near a cliff', 'sunny ridge close to base', 'shelter without sand'.")
    score, parts = score_map(ctx, spec["criteria"])
    if score is None:
        raise ValueError("None of the requested features can be computed here. " + " ".join(ctx.notes))

    c = ctx.cube
    allowed = np.isfinite(ctx.cost)                     # the target itself must be passable
    allowed[:2, :] = allowed[-2:, :] = False            # skip the cube border (filter edge effects)
    allowed[:, :2] = allowed[:, -2:] = False
    within = None
    if ctx.t_base is not None:
        allowed &= np.isfinite(ctx.t_base)              # must be reachable from the base at all
        within = 2 * ctx.t_base <= ctx.usable_s
        score = np.where(within, score, score * 0.6)    # prefer places you can walk to AND back from
    if not allowed.any():
        raise ValueError("No passable pixel to search in (check vehicle and base).")

    bias = None
    if focus is not None:                               # up to 15 % lower rank at the far side of the map
        dist = ctx.zone_distance_km(dict(lat=focus[0], lon=focus[1], radius_km=0))
        bias = 1 - 0.15 * dist / max(float(dist.max()), 1e-6)
    peaks = pick_peaks(score, allowed, c.pixel_m, count, bias)
    used = {cr["feature"] for cr, _ in parts}
    matches = []
    for r, col, val in peaks:
        lat, lon = c.latlon(r, col)
        why = [f"{describe(cr)}: {explain(r, col)}" for cr, explain in parts]
        if not used & {"flat", "steep"}:
            why.append(f"slope {c.bands['slope'][r, col]:.1f}°")
        if "firmness" in c.bands and not used & {"firm", "sand"}:
            why.append(ground_text(c, r, col))
        ok = None
        if ctx.t_base is not None:
            ok = bool(within[r, col])
            why.append(f"{2 * ctx.t_base[r, col] / 3600:.1f} h round trip from base"
                       + ("" if ok else " (over the EVA budget)"))
        matches.append(dict(lat=round(lat, 5), lon=round(lon, 5), score=round(val, 2), why=why, within_budget=ok))
    if matches and matches[0]["score"] < 0.35:
        ctx.notes.append("Weak match: nothing in this region fits the description well.")
    return dict(query=query, parser=parser, model=spec.get("model"), criteria=[describe(cr) for cr, _ in parts],
                not_understood=spec["unknown"], notes=ctx.notes, matches=matches,
                score=np.where(allowed, score, np.nan))
