"""
Tools the planning agent calls.

Every tool has a typed input model, a description written for the model that will read it, and a
handler that returns plain JSON. `tool_specs()` produces definitions in the shape both the Anthropic
and the OpenAI function-calling APIs expect, and `call_tool()` validates arguments and dispatches, so
the agent loop is one line:

    result = gear.tools.call_tool(tool_use.name, tool_use.input)

Suggested order for an agent: list_mission_archetypes, then get_route_context for each traverse it
plans, then recommend_gear with publish=true so the page shows the kit it chose.
"""
import inspect
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from . import catalog, rules as rule_mod
from .budget import CARRY_CAP_KG_PER_PERSON, size_consumables
from .context import ARCHETYPES, MissionContext, RouteRequest, archetype_public, resolve
from .engine import build_manifest
from .sources import CONFIDENCE, SOURCES

log = logging.getLogger(__name__)

# In-memory copy is the source of truth; the file only lets the kit survive a server restart.
PUBLISHED = {"manifest": None, "published_at": None, "note": None, "source": None}
STATE_FILE = "published_kit.json"


def state_path() -> Path:
    """Where the published kit is saved. Read on every call so MARSWALK_GEAR_STATE_DIR can change at runtime."""
    base = os.environ.get("MARSWALK_GEAR_STATE_DIR") or Path(__file__).resolve().parent / "state"
    return Path(base) / STATE_FILE


def _jsonable(o):
    if hasattr(o, "tolist"):  # numpy arrays and scalars
        return o.tolist()
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def _save(record):
    path = state_path()
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".published_", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, default=_jsonable)
        os.replace(tmp, path)
        tmp = None
    except (OSError, TypeError, ValueError) as e:
        log.warning("could not save the published gear kit to %s (kept in memory only): %s", path, e)
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _publish(manifest, note=None):
    """The one place a kit gets published: memory first, then a best-effort copy on disk."""
    PUBLISHED.update(manifest=manifest, published_at=time.time(), note=note, source="memory")
    _save({"manifest": manifest, "published_at": PUBLISHED["published_at"], "note": note})


def load_published():
    """Restore the last published kit from disk. A missing, empty or broken file means nothing is published."""
    path = state_path()
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        data = json.loads(text) if text.strip() else None
    except FileNotFoundError:
        data = None
    except (OSError, ValueError) as e:
        log.warning("ignoring unreadable published gear kit at %s: %s", path, e)
        data = None
    if isinstance(data, dict) and isinstance(data.get("manifest"), dict):
        at = data.get("published_at")
        note = data.get("note")
        PUBLISHED.update(manifest=data["manifest"], published_at=at if isinstance(at, (int, float)) else None,
                         note=note if isinstance(note, str) else None, source="disk")
    else:
        PUBLISHED.update(manifest=None, published_at=None, note=None, source=None)
    return PUBLISHED


def clear_published():
    """Forget the published kit, in memory and on disk."""
    PUBLISHED.update(manifest=None, published_at=None, note=None, source=None)
    path = state_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("could not delete the published gear kit at %s: %s", path, e)
    return PUBLISHED


load_published()


# ------------------------------------------------------------------ input models
class Empty(BaseModel):
    pass


class SearchCatalogIn(BaseModel):
    query: Optional[str] = Field(None, description="Words to look for in names, summaries, notes and tags, e.g. 'drill' or 'sterile'")
    category: Optional[str] = Field(None, description="One of: " + ", ".join(c for c, _ in catalog.CATEGORIES))
    carried_by: Optional[Literal["worn", "astronaut", "rover", "base", "deployed"]] = None
    min_confidence: Optional[Literal["V", "P", "E", "I", "N"]] = Field(
        None, description="Only items whose specification is at least this well supported (V best, N worst)")
    limit: int = Field(25, ge=1, le=120)


class ItemIn(BaseModel):
    item_id: str = Field(..., description="An id from search_gear_catalog, e.g. 'd_drill_2m'")


class RulesIn(BaseModel):
    group: Optional[Literal["core", "safety", "terrain", "science", "mission"]] = None


class Adjustment(BaseModel):
    item_id: str
    qty: Optional[int] = Field(None, ge=1, le=500)
    priority: Optional[Literal["critical", "recommended", "optional"]] = None
    reason: str = Field(..., description="Why the planner wants this. Shown on the page next to the item.")


class Removal(BaseModel):
    item_id: str
    reason: str = Field(..., description="Why this item is not needed. Removing a critical item is allowed but is flagged.")


class Adjustments(BaseModel):
    add: list[Adjustment] = []
    remove: list[Removal] = []


class RecommendIn(BaseModel):
    context: MissionContext
    adjustments: Optional[Adjustments] = Field(
        None, description="Items the planner wants to add or drop after seeing the rule output")
    detail: Literal["summary", "full"] = Field(
        "summary", description="'summary' is compact and meant for the agent. 'full' is what the page renders.")
    publish: bool = Field(False, description="Show this kit on the gear page as the planner's current kit")
    note: Optional[str] = Field(None, description="One line shown above the kit when published, e.g. the planner's rationale")


class SizeIn(BaseModel):
    context: MissionContext


class CarryItem(BaseModel):
    item_id: str
    qty: int = Field(1, ge=1, le=500)


class CarryIn(BaseModel):
    items: list[CarryItem]
    crew_in_team: int = Field(2, ge=1, le=4, description="People on the EVA team")


# ------------------------------------------------------------------ handlers
def _list_archetypes(_):
    from config import VEHICLES
    from .context import CREW_VEHICLES
    return {"archetypes": archetype_public(),
            "goals": ["biosignatures", "geology", "subsurface", "water_ice", "atmosphere", "seismic", "radiation", "isru",
                      "construction"],
            "hazards": ["pit", "cliff", "dunes", "canyon_walls", "night_ops", "dust_storm_season"],
            "vehicles": list(VEHICLES),
            "vehicle_details": [{"id": k, "label": v["label"], "max_slope_deg": v["max_slope"],
                                 "top_speed_kmh": v["base_speed_kmh"],
                                 "kind": "on foot" if k == "astronaut" else "crewed" if k in CREW_VEHICLES else "robotic"}
                                for k, v in VEHICLES.items()],
            "note": "Archetypes marked basis=published use figures from NASA documents. basis=assumed are planning "
                    "defaults and are listed as assumptions in the result."}


def _search(a: SearchCatalogIn):
    found = catalog.search(a.query, a.category, a.carried_by, a.min_confidence)
    brief = [{"id": i.id, "name": i.name, "category": i.category, "summary": i.summary, "carried_by": i.carried_by,
              "mass_kg": i.mass_kg, "confidence": i.conf, "planner_vehicle": i.planner_vehicle} for i in found[:a.limit]]
    return {"count": len(found), "returned": len(brief), "items": brief,
            "confidence_key": {k: v["label"] for k, v in CONFIDENCE.items()}}


_ITEM_RULES = None


def rules_for_item(item_id):
    """Which rules can add this item. Found by reading the rule functions, so it never drifts from them."""
    global _ITEM_RULES
    if _ITEM_RULES is None:
        _ITEM_RULES = {}
        for rl in rule_mod.RULES:
            for m in re.finditer(r'A\(\s*"([a-z0-9_]+)"', inspect.getsource(rl.fn)):
                _ITEM_RULES.setdefault(m.group(1), []).append(rl.id)
    return _ITEM_RULES.get(item_id, [])


def _get_item(a: ItemIn):
    if a.item_id not in catalog.ITEMS:
        return {"error": "unknown_item", "message": f"No item '{a.item_id}'. Use search_gear_catalog to find ids."}
    it = catalog.get(a.item_id)
    ids = rules_for_item(a.item_id)
    by_id = {r.id: r for r in rule_mod.RULES}
    return {"item": it.public(), "added_by_rules": [{"id": i, "title": by_id[i].title, "group": by_id[i].group} for i in ids]}


def _list_rules(a: RulesIn):
    rs = [r.public() for r in rule_mod.RULES if not a.group or r.group == a.group]
    return {"count": len(rs), "rules": rs,
            "thresholds": {k: {"value": v[0], "unit": v[1], "confidence": v[2], "note": v[4]}
                           for k, v in rule_mod.THRESHOLDS.items()}}


def _route_context(a: RouteRequest):
    from . import signals
    route, terrain, plan = signals.run_route(a)
    if route is None:
        return {"route_found": False, "warnings": plan.get("warnings", []), "explanation": plan.get("explanation")}
    return {"route_found": True, "route": route.model_dump(), "terrain": terrain.model_dump() if terrain else None,
            "warnings": plan.get("warnings", []),
            "use_it": "Pass route and terrain, or the same request as route_request, to recommend_gear."}


def _size(a: SizeIn):
    ctx = _with_route(a.context)
    return size_consumables(resolve(ctx))


def _with_route(ctx: MissionContext) -> MissionContext:
    if ctx.route_request is None:
        return ctx
    from . import signals
    route, terrain, _plan = signals.run_route(ctx.route_request)
    update = {"vehicle": ctx.route_request.vehicle, "region": ctx.route_request.region}
    if route is not None:
        update.update(route=route, terrain=terrain)
    return ctx.model_copy(update=update)


def compact(m):
    """A short form of a manifest for the agent: ids, quantities, priorities and why."""
    return {
        "context": m["context"], "assumptions": m["assumptions"], "summary": m["summary"],
        "items": [{"id": e["id"], "name": e["name"], "category": e["category"], "qty": e["qty"], "priority": e["priority"],
                   "carried_by": e["carried_by"], "mass_kg": e["total_mass_kg"], "confidence": e["confidence"]["tag"],
                   "rules": e["rules"]} for e in m["items"]],
        "triggered_rules": [{"id": r["id"], "title": r["title"], "detail": r["detail"]} for r in m["rules"]],
        "carry": {k: m["carry"][k] for k in ("team_size", "cap_kg", "load_kg", "over_cap", "moved")},
        "mass_by_carrier_kg": m["mass"]["by_carrier_kg"], "items_without_mass": len(m["mass"]["items_without_mass"]),
        "budget_highlights": _highlights(m["budget"]),
        "warnings": m["warnings"], "flags": m["flags"], "thin_evidence": m["thin_evidence"],
        "adjustments": m["adjustments"],
    }


def _highlights(b):
    out = {}
    for g in b["groups"]:
        for ln in g["lines"]:
            if ln["label"].startswith(("Suit oxygen, one EVA (design", "Suit oxygen over the whole stay", "Food, as shipped")):
                out[ln["label"]] = f'{ln["value"]} {ln["unit"]}'
    out["surface_dose_msv"] = b["radiation"]["surface_dose_msv"]
    out["career_limit_pct"] = b["radiation"]["career_pct"]
    if b.get("planner_check"):
        out["planner_check"] = b["planner_check"]["message"]
    return out


def _recommend(a: RecommendIn):
    ctx = _with_route(a.context)
    adj = a.adjustments.model_dump() if a.adjustments else None
    m = build_manifest(ctx, adj)
    if a.publish:
        _publish(m, a.note)
    out = compact(m) if a.detail == "summary" else m
    out["published"] = bool(a.publish)
    return out


def _carry(a: CarryIn):
    cap = CARRY_CAP_KG_PER_PERSON * a.crew_in_team
    load, unknown, rows = 0.0, [], []
    for x in a.items:
        if x.item_id not in catalog.ITEMS:
            return {"error": "unknown_item", "message": f"No item '{x.item_id}'."}
        it = catalog.get(x.item_id)
        if it.mass_kg is None:
            unknown.append(it.name)
            rows.append({"id": it.id, "qty": x.qty, "mass_kg": None})
        else:
            load += it.mass_kg * x.qty
            rows.append({"id": it.id, "qty": x.qty, "mass_kg": round(it.mass_kg * x.qty, 3)})
    return {"load_kg": round(load, 2), "cap_kg": round(cap, 1), "over_cap": load > cap, "items": rows,
            "items_without_mass": unknown,
            "basis": "22.7 kg (50 lbm) per person tool and sample allowance in NASA's Mars suit study (excerpt-level source). "
                     "Suit weight is not counted. Items without a published mass are not included in load_kg."}


# ------------------------------------------------------------------ registry
TOOLS = {
    "list_mission_archetypes": (Empty, _list_archetypes,
        "List the mission types the gear system understands, with default crew, stay length and power for each, "
        "and the valid goal, hazard and vehicle names. Call this first so you use valid names in later calls."),
    "search_gear_catalog": (SearchCatalogIn, _search,
        "Search the catalog of Mars gear (about 100 items). Returns short rows with id, name, mass and a confidence "
        "tag. Use it to look something up by word or to browse a category; use get_gear_item for the full record."),
    "get_gear_item": (ItemIn, _get_item,
        "Full record for one catalog item: what it is for, mass, power, rate, sources with links, caveats, and which "
        "rules can add it. Use this before explaining a choice to the user."),
    "list_gear_rules": (RulesIn, _list_rules,
        "The rules the engine applies, each with its evidence and confidence, plus every numeric threshold. Use it "
        "to explain why a kit looks the way it does or to check a threshold before overriding it."),
    "get_route_context": (RouteRequest, _route_context,
        "Run the route planner for a base and target and return the route stats (distance, hours, slope, oxygen and "
        "energy against capacity) and the terrain along it (slope, loose-ground share, roughness, temperature, sun). "
        "Call it for the traverse you are planning, then pass the result to recommend_gear."),
    "size_consumables": (SizeIn, _size,
        "Compute suit and cabin consumables, with the formula for every line, plus surface radiation dose against the "
        "career limit and a check of the planner's astronaut oxygen numbers against NASA's Mars design rate."),
    "recommend_gear": (RecommendIn, _recommend,
        "Main tool. Given the mission (and optionally a planned route), run all rules and return the kit: every item "
        "with quantity, priority, who carries it and the rules that asked for it, plus warnings, assumptions and "
        "carry-load check. Pass adjustments to add or drop items with your own reasons. Set publish=true to show the "
        "result on the gear page."),
    "check_carry_load": (CarryIn, _carry,
        "Check whether a hand-carried set of items fits the per-person carry limit for an EVA team."),
}


def tool_specs(fmt="anthropic"):
    specs = []
    for name, (model, _fn, desc) in TOOLS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        if fmt == "openai":
            specs.append({"type": "function", "function": {"name": name, "description": desc, "parameters": schema}})
        else:
            specs.append({"name": name, "description": desc, "input_schema": schema})
    return specs


def call_tool(name, arguments=None):
    if name not in TOOLS:
        return {"error": "unknown_tool", "message": f"No tool '{name}'.", "tools": list(TOOLS)}
    model, fn, _desc = TOOLS[name]
    try:
        args = model.model_validate(arguments or {})
    except ValidationError as e:
        return {"error": "invalid_arguments", "details": [{"field": ".".join(map(str, x["loc"])), "problem": x["msg"]}
                                                          for x in e.errors()]}
    try:
        return fn(args)
    except Exception as e:  # planner errors (no cube, point outside the region) come back as data, not crashes
        detail = getattr(e, "detail", None)
        return {"error": type(e).__name__, "message": str(detail or e)}
