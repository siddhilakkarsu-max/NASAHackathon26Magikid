"""
What the gear system needs to know about a mission.

MissionContext is the one input every tool shares. The planning agent can fill in as much or as
little as it knows. Anything left out is filled from the archetype's defaults, and each default
that was applied is recorded in `assumptions` so the front end can show it.
"""
import math
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field

SOL_DAYS = 1.0275  # one Mars solar day in Earth days

Archetype = Literal["short_stay", "long_stay", "traverse", "drilling", "isru", "construction", "rescue", "cave"]
Goal = Literal["biosignatures", "geology", "subsurface", "water_ice", "atmosphere", "seismic", "radiation",
               "isru", "construction"]
Hazard = Literal["pit", "cliff", "dunes", "canyon_walls", "night_ops", "dust_storm_season"]
Power = Literal["battery", "solar", "fission"]

# stay_sols / crew are published for short_stay (NASA 2023), long_stay (DRA 5.0) and traverse (DRA 5.0).
# The rest are planning defaults, not published figures, and are reported as assumptions.
ARCHETYPES = {
    "short_stay": dict(
        label="Short-stay landing", stay_sols=30, crew=2, goals=["geology", "biosignatures"], power="battery",
        sample_sites=4, hazards=[], basis="published",
        summary="NASA's current baseline: four crew reach Mars orbit, two land and live in a pressurized rover for "
                "about 30 sols. No surface habitat and minimal power.",
        sources=["m2m_2023"]),
    "long_stay": dict(
        label="Long-stay base", stay_sols=500, crew=4, goals=["geology", "biosignatures", "subsurface"], power="fission",
        sample_sites=12, hazards=[], basis="published",
        summary="Conjunction-class mission of about 500 sols with 4 to 6 crew, a habitat and EVA teams of 2 to 4.",
        sources=["dra5"]),
    "traverse": dict(
        label="Long traverse", stay_sols=14, crew=2, goals=["geology"], power="battery",
        sample_sites=6, hazards=[], basis="published",
        summary="A sortie of one to two weeks and about 100 km from a pressurized rover, with EVAs along the way.",
        sources=["dra5"]),
    "drilling": dict(
        label="Subsurface drilling campaign", stay_sols=500, crew=4, goals=["subsurface", "water_ice"], power="fission",
        sample_sites=6, hazards=[], basis="assumed",
        summary="A drilling and ice-access campaign inside a long stay, with a rover-towed drill at the end of traverses.",
        sources=["dra5"]),
    "isru": dict(
        label="Resource production (ISRU)", stay_sols=500, crew=4, goals=["isru", "water_ice"], power="fission",
        sample_sites=4, hazards=[], basis="assumed",
        summary="Oxygen and water production for ascent propellant. Mining is expected to run mostly without crew.",
        sources=["hoffman_ez", "moxie_sciadv"]),
    "construction": dict(
        label="Outpost construction", stay_sols=500, crew=4, goals=["construction"], power="fission",
        sample_sites=2, hazards=[], basis="assumed",
        summary="Building up a habitat and plant at one site over repeat visits, within about 5 km of the landing site.",
        sources=["hoffman_ez"]),
    "rescue": dict(
        label="Rescue and contingency", stay_sols=14, crew=4, goals=[], power="battery",
        sample_sites=0, hazards=[], basis="assumed",
        summary="Reaching and recovering a crew member. A pressurized rover seats four in an emergency.",
        sources=["dra5"]),
    "cave": dict(
        label="Pit and lava-tube exploration", stay_sols=30, crew=2, goals=["geology", "biosignatures"], power="battery",
        sample_sites=3, hazards=["pit"], basis="assumed",
        summary="Entering a skylight or pit. No crewed architecture has been published, so this is a proposal.",
        sources=["cushing_skylights"]),
}

# Planner vehicle keys (config.VEHICLES) that carry crew and their tools, and those whose crew
# breathe from suits. Every other vehicle is treated as robotic.
CREW_VEHICLES = ("pressurized_rover", "unpressurized_rover")
SUITED_VEHICLES = ("astronaut", "unpressurized_rover")


class RouteStats(BaseModel):
    """The `stats` block returned by POST /api/plan."""
    distance_km: Optional[float] = None
    one_way_h: Optional[float] = None
    round_trip_h: Optional[float] = None
    max_slope_deg: Optional[float] = None
    mean_slope_deg: Optional[float] = None
    within_budget: Optional[bool] = None
    o2_used_kg: Optional[float] = None
    o2_max_kg: Optional[float] = None
    o2_pct: Optional[float] = None
    energy_used_kwh: Optional[float] = None
    energy_max_kwh: Optional[float] = None
    energy_pct: Optional[float] = None
    max_range_km: Optional[float] = None
    limiting_factor: Optional[str] = None


class TerrainSignals(BaseModel):
    """What the cube says about the ground along a route."""
    max_slope_deg: Optional[float] = None
    p90_slope_deg: Optional[float] = None
    mean_slope_deg: Optional[float] = None
    mean_firmness: Optional[float] = Field(None, description="0 = loose sand or dust, 1 = bedrock (THEMIS night proxy)")
    min_firmness: Optional[float] = None
    loose_fraction: Optional[float] = Field(None, description="share of route pixels with firmness below 0.3")
    roughness_ratio: Optional[float] = Field(None, description="route roughness divided by the cube's 95th percentile")
    surface_temp_min_k: Optional[float] = None
    surface_temp_mean_k: Optional[float] = None
    sun_elevation_deg: Optional[float] = None
    local_hour: Optional[float] = None
    samples: Optional[int] = Field(None, description="how many route pixels were sampled")


class Point(BaseModel):
    lat: float
    lon: float


class RouteRequest(BaseModel):
    """Ask the planner for a route so the gear system can read the terrain along it."""
    region: str = "jezero"
    vehicle: str = "astronaut"
    base: Point
    target: Point
    local_hour: float = Field(11.0, ge=0, le=24)
    ls: float = Field(90.0, ge=0, le=360)
    budget_hours: float = Field(4.0, gt=0)
    reserve: float = Field(0.25, ge=0, lt=1)


class MissionContext(BaseModel):
    archetype: Archetype = Field("short_stay", description="Which kind of mission this is")
    crew: Optional[int] = Field(None, ge=1, le=6, description="Crew members on the surface")
    stay_sols: Optional[float] = Field(None, gt=0, le=1100, description="Surface stay in sols")
    goals: Optional[list[Goal]] = Field(None, description="Science and engineering goals")
    hazards: Optional[list[Hazard]] = Field(None, description="Known site hazards")
    vehicle: str = Field("astronaut", description="Traveller for the route being planned")
    eva_hours: Optional[float] = Field(None, gt=0, le=12, description="Typical EVA length in hours")
    eva_days: Optional[int] = Field(None, ge=0, le=1100, description="Number of EVA days over the stay")
    power: Optional[Power] = None
    resupply: bool = Field(False, description="True if resupply is possible during the stay")
    sample_sites: Optional[int] = Field(None, ge=0, le=200, description="Sampling sites planned")
    base_has_shelter: bool = Field(True, description="Base has a radiation storm shelter")
    region: Optional[str] = None
    route: Optional[RouteStats] = None
    terrain: Optional[TerrainSignals] = None
    route_request: Optional[RouteRequest] = Field(
        None, description="If given, the planner is run and route and terrain are filled from it")


@dataclass
class Resolved:
    archetype: str
    label: str
    crew: int
    teams: int
    stay_sols: float
    stay_days: float
    goals: set
    hazards: set
    vehicle: str
    eva_hours: float
    eva_days: int
    power: str
    resupply: bool
    sample_sites: int
    base_has_shelter: bool
    region: Optional[str]
    route: Optional[RouteStats]
    terrain: Optional[TerrainSignals]
    assumptions: list = field(default_factory=list)

    @property
    def crewed_rover(self):
        """A vehicle that carries the crew and their tools."""
        return self.vehicle in CREW_VEHICLES

    @property
    def suited(self):
        """The crew breathe from their suits on this trip."""
        return self.vehicle in SUITED_VEHICLES

    @property
    def surface_days(self):
        return self.stay_days


def resolve(ctx: MissionContext) -> Resolved:
    a = ARCHETYPES[ctx.archetype]
    notes = []

    def pick(value, default, label, basis_note):
        if value is not None:
            return value
        notes.append(f"{label}: {default} ({basis_note})")
        return default

    basis = "published for this archetype" if a["basis"] == "published" else "planning default, not a published figure"
    crew = pick(ctx.crew, a["crew"], "Crew on surface", basis)
    stay = pick(ctx.stay_sols, a["stay_sols"], "Surface stay (sols)", basis)
    if ctx.goals is not None:
        goals = set(ctx.goals)
    else:
        goals = set(a["goals"])
        if goals:
            notes.append(f"Goals: {', '.join(sorted(goals))} (archetype default)")
    if ctx.hazards is not None:
        hazards = set(ctx.hazards)
    else:
        hazards = set(a["hazards"])
        if hazards:
            notes.append(f"Hazards: {', '.join(sorted(hazards))} (archetype default)")
    power = pick(ctx.power, a["power"], "Power", "archetype default")
    sites = pick(ctx.sample_sites, a["sample_sites"], "Sampling sites", "planning default")
    eva_h = pick(ctx.eva_hours, 6.0, "Typical EVA length (h)", "Artemis notional EVA is 6 +/- 2 h")
    stay_days = stay * SOL_DAYS
    if ctx.eva_days is not None:
        eva_days = ctx.eva_days
    elif ctx.archetype == "short_stay":
        eva_days = min(20, int(stay))
        notes.append(f"EVA days: {eva_days} (a NASA memo footnote assumes about 20 EVA days on a 30 sol stay)")
    else:
        eva_days = min(int(stay), math.ceil(stay_days / 7.0 * 24.0 / eva_h))
        notes.append(f"EVA days: {eva_days} (the 24 h per week NASA planning ceiling at {eva_h:g} h per EVA; "
                     "a ceiling, not a plan)")
    if ctx.route is None:
        notes.append("No planned route supplied, so route and terrain rules were not evaluated")
    elif ctx.terrain is None:
        notes.append("Route stats supplied without terrain signals, so slope and firmness rules use the route stats only")
    return Resolved(
        archetype=ctx.archetype, label=a["label"], crew=crew, teams=max(1, crew // 2), stay_sols=stay,
        stay_days=stay_days, goals=goals, hazards=hazards, vehicle=ctx.vehicle, eva_hours=eva_h, eva_days=eva_days,
        power=power, resupply=ctx.resupply, sample_sites=sites, base_has_shelter=ctx.base_has_shelter,
        region=ctx.region, route=ctx.route, terrain=ctx.terrain, assumptions=notes)


def archetype_public():
    return [{"id": k, **{x: v[x] for x in ("label", "summary", "stay_sols", "crew", "goals", "power", "basis")},
             "sources": v["sources"]} for k, v in ARCHETYPES.items()]
