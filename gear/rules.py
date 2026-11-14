"""
The rule set: IF (mission, route, terrain) THEN (gear).

Each rule is a plain function that returns None (not triggered) or a Hit naming the items it adds, why,
and the numbers that tripped it. Rules are grouped by what drives them:

    core    every surface mission
    safety  consumables, radiation, rescue (hard constraints; items from these rules are marked critical)
    terrain slope, firmness, roughness, cold, light, distance, hazards
    science goals, instruments, samples, drilling
    mission stay length, power, vehicle, archetype

Thresholds live in THRESHOLDS with their evidence tag. A threshold tagged "I" is my own number and
should be treated as tunable. MISSION_EQUIPMENT_RESEARCH.md section 5 has the reasoning for each.
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from .budget import CAREER_LIMIT_MSV, DOSE_RATE_MSV_DAY, RATES
from .context import Resolved
from .sources import CONFIDENCE, sources

# name: (value, unit, evidence tag, source ids, note)
THRESHOLDS = {
    "shelter_minutes": (30, "min", "V", ("lowe2025",), "One 2025 paper's finding, not a NASA requirement"),
    "co2_contingency_h": (1.0, "h", "V", ("std3001_v2_s11",), "Inspired CO2 at most 20 mmHg for at most 1 hour"),
    "eva_food_h": (4.0, "h", "P", ("std3001_v2_s11",), "Nutrition required on surface EVAs longer than this"),
    "slope_loose_deg": (15.0, "deg", "E", ("golombek_slopes",), "Rover limit on unconsolidated ground at a 3 m scale"),
    "slope_rock_deg": (30.0, "deg", "E", ("golombek_slopes", "nasa_rover_page"), "Rover limit on rock; Perseverance avoids tilts over 30"),
    "pressurized_rover_slope_deg": (15.0, "deg", "P", ("nasa_moonbase",), "NASA lunar page for a pressurized rover"),
    "loose_firmness": (0.3, "0-1", "I", (), "The planner's own 'loose sand or dust' cut-off (app.py)"),
    "loose_fraction": (0.2, "share", "I", (), "My threshold: a fifth of the route on loose ground"),
    "roughness_ratio": (1.5, "x p95", "I", (), "My threshold: route roughness 1.5 times the cube's 95th percentile"),
    "cold_surface_k": (210.0, "K", "I", ("sbir_mars_plss",), "Below Jezero's mean air temperature of about 218 K; no published suit threshold"),
    "min_sun_elevation_deg": (10.0, "deg", "I", (), "The planner's default minimum sun elevation"),
    "walkback_km": (15.0, "km", "E", ("dra5",), "DRA 5.0 nominal traverse out, or EVA walk-back distance"),
    "los_km": (6.4, "km", "I", ("mars_relay",), "Smooth-sphere line of sight between two 1.5 m antennas; terrain cuts it"),
    "dose_career_pct": (25.0, "% of 600 mSv", "I", ("std3001_v1_s4",), "My threshold: surface dose alone a quarter of the career limit"),
    "long_stay_sols": (300, "sols", "E", ("mepag_human_sci", "dra5"), "Long stays are 300 to 500 sols"),
    "dust_pel_days": (30, "days", "V", ("nasa_dust_pel",), "NASA's dust limit is defined for exposures up to 30 days"),
    "exercise_sols": (30, "sols", "I", ("std3001_v1_s4",), "Beyond a short stay the bone and muscle standards apply"),
}


@dataclass
class Add:
    item: str
    why: str
    qty: Optional[int] = None
    priority: Optional[str] = None  # critical | recommended | optional; default comes from the rule's group


@dataclass
class Hit:
    detail: str
    adds: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    observed: Optional[str] = None
    threshold: Optional[str] = None


@dataclass
class Rule:
    id: str
    group: str
    title: str
    conf: str
    evidence: list   # list of THRESHOLDS keys and/or free text
    fn: Callable
    sources: tuple = ()
    explain: str = ""

    def public(self):
        ev = []
        for e in self.evidence:
            if e in THRESHOLDS:
                v, u, c, s, n = THRESHOLDS[e]
                ev.append({"label": e.replace("_", " "), "value": f"{v} {u}", "confidence": c, "note": n,
                           "sources": [x["id"] for x in sources(s)]})
            else:
                ev.append({"label": e, "value": None, "confidence": self.conf, "note": "", "sources": []})
        return {"id": self.id, "group": self.group, "title": self.title,
                "confidence": {"tag": self.conf, **CONFIDENCE[self.conf]}, "explain": self.explain,
                "evidence": ev, "sources": sources(self.sources)}


RULES: list = []


def rule(id, group, title, conf, evidence=(), srcs=(), explain=""):
    def deco(fn):
        RULES.append(Rule(id, group, title, conf, list(evidence), fn, tuple(srcs), explain))
        return fn
    return deco


A = Add

# ---- helpers ---------------------------------------------------------------
def max_slope(r: Resolved):
    if r.terrain and r.terrain.max_slope_deg is not None:
        return r.terrain.max_slope_deg
    if r.route and r.route.max_slope_deg is not None:
        return r.route.max_slope_deg
    return None


def loose_fraction(r: Resolved):
    return r.terrain.loose_fraction if r.terrain else None


def distance_km(r: Resolved):
    return r.route.distance_km if r.route else None


def round_trip_h(r: Resolved):
    return r.route.round_trip_h if r.route else None


def one_way_h(r: Resolved):
    return r.route.one_way_h if r.route else None


def on_foot(r: Resolved):
    return r.vehicle == "astronaut"


def n(x, digits=1):
    s = f"{x:.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


# =============================================================== CORE (every surface mission)
@rule("C1", "core", "Every EVA needs a suit, life support and a way to follow procedures", "V",
      evidence=["O2 design rate 0.114 kg/h (NASA Mars suit design basis)", "Drinking water at least 0.24 kg per EVA hour"],
      srcs=("sbir_mars_plss", "std3001_v2_s11", "orion_crew"),
      explain="Baseline suit set, sized from NASA's Mars design rate. Procedures are on the suit display because a "
              "reply from Earth takes 3 to 22 minutes.")
def _c1(r):
    return Hit(f"{r.crew} crew, EVAs of about {n(r.eva_hours)} h", [
        A("suit_pgs", "One suit per crew member"),
        A("suit_backup_o2", "Backup breathing gas if the primary supply fails"),
        A("suit_battery", "Fans, pumps, comms and displays"),
        A("c_suit_o2", "Breathing gas for every EVA hour"),
        A("c_suit_water", "Minimum suited hydration"),
        A("c_suit_cooling", "Heat rejection"),
        A("i_dosimeter_personal", "The suit standard requires radiation monitoring"),
        A("eva_display", "Procedures and status without waiting on Earth"),
        A("n_suit_radio", "Voice and data between suits, vehicles and base"),
    ], observed=f"{r.crew} crew", threshold="always")


@rule("C2", "core", "Medical and rescue baseline", "P",
      evidence=["Autonomous medical care is required; delay to Earth is 3 to 22 minutes",
                "Suits must allow rescue of an incapacitated crew member"],
      srcs=("std3001_s3", "std3001_v2_s11", "orion_crew"))
def _c2(r):
    return Hit("Any surface mission", [
        A("med_core", "First-response medications and wound care"),
        A("med_oxygen", "Treat illness or decompression sickness"),
        A("med_pill_tool", "Medication without opening the suit"),
        A("med_diagnostics", "Diagnose without a doctor on site"),
        A("f_icr", "Move a crew member who cannot move"),
        A("f_fire", "Cabin and vehicle fire; no Mars-specific system exists yet"),
    ], observed="always", threshold="always")


@rule("C3", "core", "Dust control on every ingress", "V",
      evidence=["Dust limit 0.1 mg/m3 as a 24 h average, up to 30 days", "Ultrafine dust sticks to suit-like fabric"],
      srcs=("nasa_dust_pel", "nasa_perseverance_dust", "wang_dust"))
def _c3(r):
    return Hit("Every EVA returns through a lock", [
        A("suit_dust_removal", "Clean suits before they enter the cabin"),
        A("suitport", "Keep dust out of the cabin"),
        A("h_hepa", "Fine dust under 5 micrometres is not cleared by the lungs"),
        A("i_air_monitor", "Check the cabin against the limit"),
    ], observed="always", threshold="always")


@rule("C4", "core", "Radiation shelter and an alarm that works without Earth", "V",
      evidence=["10 g/cm2 water-equivalent shelter on the surface, any duration", "Warning trigger at 25% above the 5-day background"],
      srcs=("std3001_v1_s4", "lowe2025", "srag"))
def _c4(r):
    return Hit("Any surface stay", [
        A("h_storm_shelter", "NASA's surface shelter guideline"),
        A("h_spe_alarm", "Warns of a solar storm even if comms are lost"),
        A("i_dosimeter_area", "Dose rate at the base"),
    ], observed="always", threshold="always")


@rule("C5", "core", "Link to Earth through the relay orbiters", "P", srcs=("mars_relay", "ascend_delay"))
def _c5(r):
    return Hit("Any surface mission", [A("n_relay_link", "Reaches Earth through four orbiters")],
               observed="always", threshold="always")


@rule("C6", "core", "Cabin life support for the whole stay", "P",
      evidence=["Per crew member per day: O2 0.818 kg, food 1.831 kg as shipped, hygiene 0.781 kg"],
      srcs=("frontiers_bvad", "lynch_logistics"))
def _c6(r):
    return Hit(f"{r.crew} crew for {n(r.stay_days, 0)} days", [
        A("c_cabin", "Oxygen, water, food, hygiene and clothing"),
        A("c_personal", "Stepped personal allowance"),
    ], observed=f"{n(r.stay_sols, 0)} sols", threshold="always")


# =============================================================== SAFETY (from the planned route)
@rule("S1", "safety", "Round trip does not fit the suit's oxygen", "V",
      evidence=["O2 design rate 0.114 kg/h (NASA Mars suit design basis)"],
      srcs=("sbir_mars_plss", "bvad2"),
      explain="Checks the planned round trip against the suit's capacity, both at the planner's own rate and at "
              "NASA's Mars design rate.")
def _s1(r):
    if not (r.suited and r.route and r.route.round_trip_h):
        return None
    cap = None
    try:
        from config import VEHICLES
        cap = VEHICLES["astronaut"]["consumables"]["o2_capacity_kg"]
    except Exception:
        pass
    design = RATES["suit_o2_design"][0]
    need = design * r.route.round_trip_h
    over_planner = (r.route.o2_pct or 0) > 100
    over_design = cap is not None and need > cap
    if not (over_planner or over_design):
        return None
    why = ("exceeds the planner's own O2 limit" if over_planner
           else "fits at the planner's rate but not at NASA's Mars design rate")
    return Hit(f"Round trip {n(r.route.round_trip_h)} h needs {n(need, 2)} kg at {design} kg/h; suit carries "
               f"{n(cap, 2) if cap else '?'} kg. It {why}.",
               [A("v_pressurized_rover", "Vehicle support so the suit is not the limiting supply", qty=1)],
               warnings=[f"Suited O2 for this round trip is {n(need, 2)} kg at NASA's design rate against "
                         f"{n(cap, 2) if cap else '?'} kg carried."],
               observed=f"{n(need, 2)} kg needed", threshold=f"{n(cap, 2) if cap else '?'} kg carried")


@rule("S2", "safety", "Work site is more than 30 minutes from shelter", "V",
      evidence=["shelter_minutes"], srcs=("lowe2025", "srag"),
      explain="From a 2025 study of solar storm warning times on Mars. It assumes the base is the shelter.")
def _s2(r):
    ow = one_way_h(r)
    if ow is None or not r.base_has_shelter:
        return None
    minutes = ow * 60
    limit = THRESHOLDS["shelter_minutes"][0]
    if minutes <= limit:
        return None
    adds = [A("h_portable_shelter", "Cover at the work site instead of a long run back")]
    if on_foot(r):
        adds.append(A("v_pressurized_rover", "A vehicle can outrun the warning time on foot", qty=1))
    return Hit(f"One-way trip is {n(minutes, 0)} min against a {limit} min warning window",
               adds, warnings=[f"{n(minutes, 0)} minutes one way is beyond the 30 minute guideline for reaching shelter "
                               "after a solar storm warning."],
               observed=f"{n(minutes, 0)} min one way", threshold=f"{limit} min")


@rule("S3", "safety", "Walk-back longer than the one hour contingency CO2 limit", "V",
      evidence=["co2_contingency_h"], srcs=("std3001_v2_s11",))
def _s3(r):
    ow = one_way_h(r)
    if ow is None or not on_foot(r) or ow <= THRESHOLDS["co2_contingency_h"][0]:
        return None
    return Hit(f"A walk-back of {n(ow)} h is longer than 1 h",
               [A("v_pressurized_rover", "Beyond 1 h on foot the suit CO2 standard no longer covers contingency", qty=1)],
               warnings=[f"A {n(ow)} h walk-back exceeds the suit's 1 h contingency CO2 limit (20 mmHg)."],
               observed=f"{n(ow)} h", threshold="1 h")


@rule("S4", "safety", "Long EVAs need food and drink in the suit", "P",
      evidence=["eva_food_h"], srcs=("std3001_v2_s11", "norcross_walkback"))
def _s4(r):
    h = max(r.eva_hours, round_trip_h(r) or 0)
    if h <= THRESHOLDS["eva_food_h"][0]:
        return None
    return Hit(f"EVA of about {n(h)} h", [A("c_eva_food", "Nutrition on EVAs over 4 h")],
               observed=f"{n(h)} h", threshold="4 h")


@rule("S5", "safety", "Surface dose is a large share of the career limit", "I",
      evidence=["dose_career_pct", "Surface dose 0.67 mSv per day (measured)", "Career limit 600 mSv"],
      srcs=("swri_rad", "std3001_v1_s4"),
      explain="Surface only. Transit adds far more (1.8 mSv per day measured in cruise).")
def _s5(r):
    dose = DOSE_RATE_MSV_DAY * r.stay_days
    pct = 100 * dose / CAREER_LIMIT_MSV
    if pct < THRESHOLDS["dose_career_pct"][0]:
        return None
    return Hit(f"{n(dose, 0)} mSv on the surface alone, {n(pct, 0)}% of the 600 mSv career limit",
               [A("r_shielding", "Pile regolith to cut the dose over a long stay"),
                A("i_dosimeter_personal", "Track each crew member's running dose")],
               warnings=[f"Surface dose over {n(r.stay_days, 0)} days is about {n(dose, 0)} mSv, {n(pct, 0)}% of the career "
                         "limit, before any transit dose."],
               observed=f"{n(pct, 0)}% of career limit", threshold="25%")


# =============================================================== TERRAIN
@rule("T1", "terrain", "Steep ground on loose material", "E",
      evidence=["slope_loose_deg", "loose_fraction", "loose_firmness"], srcs=("golombek_slopes", "purgatory_dune"),
      explain="Rovers are limited to about 15 degrees on unconsolidated ground and about 30 on rock. There is no "
              "published equivalent for suited walkers.")
def _t1(r):
    s = max_slope(r)
    if s is None or s <= THRESHOLDS["slope_loose_deg"][0] or s > THRESHOLDS["slope_rock_deg"][0]:
        return None
    lf = loose_fraction(r)
    if lf is not None and lf < THRESHOLDS["loose_fraction"][0]:
        return None
    adds = [A("m_probe", "Check footing before committing"), A("m_tether_lines", "Link the team on slope")]
    if not on_foot(r):
        adds += [A("m_recovery_gear", "Self-recovery if a wheel digs in"), A("m_traction_aids", "Cross a short soft patch")]
    seen = f"{n(lf * 100, 0)}% loose" if lf is not None else "firmness not checked"
    return Hit(f"Max slope {n(s)} degrees; {seen}", adds,
               observed=f"{n(s)} deg", threshold="15 deg on loose ground")


@rule("T2", "terrain", "Slope beyond a published pressurized-rover limit", "P",
      evidence=["pressurized_rover_slope_deg"], srcs=("nasa_moonbase",))
def _t2(r):
    s = max_slope(r)
    if r.vehicle != "pressurized_rover" or s is None or s <= THRESHOLDS["pressurized_rover_slope_deg"][0]:
        return None
    return Hit(f"Route reaches {n(s)} degrees; NASA's lunar pages list 15 for a pressurized rover", [],
               warnings=[f"Max slope {n(s)} degrees is above the 15 degree limit NASA lists for a pressurized rover "
                         "(a lunar specification)."],
               observed=f"{n(s)} deg", threshold="15 deg")


@rule("T3", "terrain", "Slope steeper than rovers can attempt", "E",
      evidence=["slope_rock_deg"], srcs=("golombek_slopes", "nasa_rover_page"),
      explain="Opportunity made 9 cm of progress while its wheels turned about 20 m at 32 degrees.")
def _t3(r):
    s = max_slope(r)
    if s is None or s <= THRESHOLDS["slope_rock_deg"][0]:
        return None
    return Hit(f"Max slope {n(s)} degrees", [
        A("m_climbing_kit", "Walking route only with climbing gear; no published Mars crew kit exists", priority="critical"),
        A("m_tether_lines", "Link the team"),
    ], warnings=[f"Slope reaches {n(s)} degrees, beyond rover limits. Avoid it or plan a roped route."],
        observed=f"{n(s)} deg", threshold="30 deg")


@rule("T4", "terrain", "Loose sand or dust on the route", "I",
      evidence=["loose_fraction", "loose_firmness"], srcs=("jpl_spirit_trap", "purgatory_dune"),
      explain="Spirit and Opportunity were both lost to soft ground that looked fine from above.")
def _t4(r):
    lf = loose_fraction(r)
    if lf is None or lf < THRESHOLDS["loose_fraction"][0]:
        return None
    adds = [A("m_probe", "Test a crust before crossing it")]
    if not on_foot(r):
        adds += [A("m_traction_aids", "Cross a short soft patch"), A("m_recovery_gear", "Self-recovery")]
    return Hit(f"{n(lf * 100, 0)}% of the route is loose ground", adds,
               observed=f"{n(lf * 100, 0)}% loose", threshold="20%")


@rule("T5", "terrain", "Rough, rocky ground", "I",
      evidence=["roughness_ratio"], srcs=("jpl_curiosity_wheels",))
def _t5(r):
    rr = r.terrain.roughness_ratio if r.terrain else None
    if rr is None or rr < THRESHOLDS["roughness_ratio"][0]:
        return None
    if on_foot(r):
        return Hit(f"Route roughness is {n(rr)} times the typical high value", [],
                   warnings=["Rough ground. No published boot or glove wear data for Mars; check suit wear after each EVA."],
                   observed=f"{n(rr)}x", threshold="1.5x")
    return Hit(f"Route roughness is {n(rr)} times the typical high value",
               [A("m_spare_wheels", "Sharp rock wears wheels; three broken grousers is about 60% of wheel life")],
               observed=f"{n(rr)}x", threshold="1.5x")


@rule("T6", "terrain", "Pit, cliff or canyon wall in the work area", "I",
      evidence=["Skylights 100 to 225 m wide and 68 to 130 m deep", "Canyon walls about 30 degrees, over 16,000 boulder falls"],
      srcs=("cushing_skylights",),
      explain="Crewed gear for these is concept-stage. The rule sends robots first and keeps people on a rope.")
def _t6(r):
    hz = r.hazards & {"pit", "cliff", "canyon_walls"}
    if not hz:
        return None
    adds = [A("m_aerial_scout", "Look before committing"),
            A("v_perseverance", "A robotic precursor surveys the site first", qty=1),
            A("m_tether_lines", "Keep the team linked near edges"),
            A("helmet_lamp", "Shadow inside pits and under walls"),
            A("i_gpr", "Check for voids under the surface")]
    if "pit" in hz or "cliff" in hz:
        adds.append(A("m_climbing_kit", "Descent and ascent gear; none is published for Mars crew", priority="critical"))
    return Hit("Hazards present: " + ", ".join(sorted(hz)), adds,
               warnings=["No published crewed procedure for pits or cliffs. Treat this kit as a proposal."],
               observed=", ".join(sorted(hz)), threshold="hazard flag")


@rule("T7", "terrain", "Cold surface or night work", "I",
      evidence=["cold_surface_k"], srcs=("sbir_mars_plss",),
      explain="NASA says ordinary suit insulation may not be enough on Mars. No heater specification is published.")
def _t7(r):
    t = r.terrain.surface_temp_min_k if r.terrain else None
    cold = t is not None and t < THRESHOLDS["cold_surface_k"][0]
    night = "night_ops" in r.hazards
    if not (cold or night):
        return None
    detail = f"Coldest route pixel {n(t, 0)} K" if cold else "Night operations flagged"
    return Hit(detail, [A("suit_thermal", "Insulation and heaters"), A("suit_battery", "Heaters draw from the suit battery", qty=r.crew * 2)],
               observed=f"{n(t, 0)} K" if t is not None else "night", threshold="210 K")


@rule("T8", "terrain", "Low sun at the planned time", "I", evidence=["min_sun_elevation_deg"])
def _t8(r):
    e = r.terrain.sun_elevation_deg if r.terrain else None
    if e is None or e >= THRESHOLDS["min_sun_elevation_deg"][0]:
        return None
    return Hit(f"Sun is {n(e)} degrees above the horizon", [A("helmet_lamp", "Light for low-sun work")],
               observed=f"{n(e)} deg", threshold="10 deg")


@rule("T9", "terrain", "Farther than a walk-back from base", "E",
      evidence=["walkback_km"], srcs=("dra5",))
def _t9(r):
    d = distance_km(r)
    if d is None or d <= THRESHOLDS["walkback_km"][0]:
        return None
    adds = [A("m_field_cache", "Life support, power and emergency shelter placed ahead")]
    if on_foot(r):
        adds.append(A("v_pressurized_rover", "A second vehicle for the walk-back case", qty=1))
    return Hit(f"{n(d)} km out", adds, observed=f"{n(d)} km", threshold="15 km")


@rule("T10", "terrain", "Beyond reliable line of sight", "I",
      evidence=["los_km"], srcs=("mars_relay",),
      explain="Two 1.5 m antennas see each other to about 6.4 km on a smooth sphere. Hills and crater walls cut that sharply.")
def _t10(r):
    d = distance_km(r)
    if d is None or d <= THRESHOLDS["los_km"][0]:
        return None
    return Hit(f"{n(d)} km route", [A("n_relay_beacon", "Keep radio contact over terrain", qty=max(1, math.ceil(d / 6.4) - 1)),
                                    A("n_nav_aid", "Position without GPS")],
               observed=f"{n(d)} km", threshold="6.4 km")


@rule("T11", "terrain", "Dunes or ripple fields", "I", srcs=("purgatory_dune", "jpl_spirit_trap"))
def _t11(r):
    if "dunes" not in r.hazards:
        return None
    return Hit("Dune hazard flagged", [
        A("m_traction_aids", "Cross a short soft patch"), A("m_recovery_gear", "Self-recovery"),
        A("m_probe", "Test footing"), A("m_aerial_scout", "Scout ripple fields before driving")],
        observed="dunes", threshold="hazard flag")


@rule("T12", "terrain", "Dust storm season", "I", srcs=("insight_dust",))
def _t12(r):
    if "dust_storm_season" not in r.hazards:
        return None
    return Hit("Dust storm season flagged", [A("p_storm_storage", "Carry the base through weeks of blocked sun"),
                                             A("p_array_cleaning", "Restore output afterwards")],
               warnings=["The 2018 global dust storm ended Opportunity's mission. No published threshold for standing down EVAs."],
               observed="season flag", threshold="hazard flag")


# =============================================================== SCIENCE
@rule("M1", "science", "Biosignature search needs clean sampling", "P",
      evidence=["Under 150 ng total Earth organics per sample on Perseverance", "BASALT protocol took 7 samples per site",
                "Perseverance carried 5 witness tubes among 43"],
      srcs=("jpl_sample_tubes", "beaton_basalt", "cospar_pp"),
      explain="Sterile tools, sealed tubes, blanks and two independent analysers, with a robotic precursor ahead of people.")
def _m1(r):
    if "biosignatures" not in r.goals:
        return None
    tubes = max(1, 7 * r.sample_sites)
    witness = max(1, math.ceil(0.12 * tubes))
    return Hit(f"{r.sample_sites} sampling sites", [
        A("g_sterile_kit", "Clean handling"), A("g_sealed_tubes", f"7 samples per site, {r.sample_sites} sites", qty=tubes),
        A("g_witness_tubes", "Blanks show what contamination arrived", qty=witness),
        A("g_swabs", "Track contamination between sites"),
        A("i_hand_nir", "First of two independent analysers"), A("i_hand_xrf", "Second analyser"),
        A("i_hand_raman", "Organics", priority="optional"),
        A("v_perseverance", "COSPAR guidance: robotic precursor before crew reach an uncharacterised site", qty=1,
          priority="optional"),
    ], observed=f"{r.sample_sites} sites", threshold="goal flag")


@rule("M2", "science", "Field geology tool set", "E",
      evidence=["Apollo geology tools and Artemis redesign", "Large hard rocks did not fit one bag size in Desert RATS"],
      srcs=("allton_apollo_tools", "naids_artemis_tools", "desert_rats", "beaton_basalt"))
def _m2(r):
    if not (r.goals & {"geology", "biosignatures"}) and r.archetype != "traverse":
        return None
    return Hit("Geology or sampling goal", [
        A("g_hammer", "Chip rock, drive tubes"), A("g_tongs", "Pick up small rocks"), A("g_scoop", "Soil"),
        A("g_rake", "Pebbles"), A("g_drive_tube", "Soil cores", qty=2 * r.teams), A("g_handle", "Shared shaft"),
        A("g_gnomon", "Scale and colour in photos"), A("g_hand_lens", "Quick look before sampling"),
        A("g_bags", "More than one bag size"), A("g_markers", "Agree on what was sampled"),
        A("g_camera", "Stills of every sample"), A("g_scale", "Track the return mass"),
        A("i_hand_nir", "Mineral groups in 15 s"), A("i_hand_xrf", "Elements in 30 s"),
        A("g_chisel", "Extra ways to take rock", priority="optional"),
        A("g_contact_sampler", "Undisturbed top layer", priority="optional"),
        A("g_vacuum_container", "Keep volatiles", priority="optional"),
    ], observed="geology", threshold="goal flag")


@rule("M3", "science", "Subsurface goal needs a drill", "E",
      evidence=["Drill to at least 2 m (ExoMars class, 21 kg, 80 W)", "Low gravity limits down-force"],
      srcs=("leonardo_drill", "neemo22", "nasa_rimfax"))
def _m3(r):
    if not (r.goals & {"subsurface", "water_ice"}):
        return None
    return Hit("Subsurface or ice goal", [
        A("d_drill_2m", "Samples below the damaged surface layer", qty=1),
        A("g_hand_drill", "Short rock cores on foot", priority="optional"),
        A("g_stabilizer", "Something to push against in low gravity"),
        A("i_gpr", "Find the target before drilling")],
        observed="subsurface", threshold="goal flag")


@rule("M4", "science", "Deep drilling and ice extraction", "E",
      evidence=["Human-scale drill 700 to 2,200 kg", "Mid-latitude ice within about 1 m"],
      srcs=("ntrs_human_drill", "swim_ice", "ntrs_isru_plant"))
def _m4(r):
    adds = []
    if "water_ice" in r.goals or "isru" in r.goals:
        adds += [A("d_ice_system", "Water from subsurface ice"), A("r_water_test", "Confirm the water is safe")]
    if r.archetype == "drilling":
        adds.append(A("d_drill_deep", "Tens to hundreds of metres; 700 to 2,200 kg class"))
    if not adds:
        return None
    return Hit("Ice, ISRU or a drilling campaign", adds, observed="ice or drilling", threshold="goal flag")


@rule("M5", "science", "Atmosphere and weather", "P", evidence=["Four or more stations"], srcs=("mepag_human_sci",))
def _m5(r):
    if "atmosphere" not in r.goals:
        return None
    return Hit("Atmosphere goal", [A("i_weather", "MEPAG asks for four or more locations", qty=4)],
               observed="atmosphere", threshold="goal flag")


@rule("M6", "science", "Seismic monitoring", "E", srcs=("mepag_human_sci",))
def _m6(r):
    if "seismic" not in r.goals:
        return None
    return Hit("Seismic goal", [A("i_seismometer", "Interior structure")], observed="seismic", threshold="goal flag")


@rule("M7", "science", "Resource production", "P",
      evidence=["MOXIE peak 12 g/h; scale-up target 2 to 3 kg/h", "Mining expected to run without crew"],
      srcs=("moxie_nasa", "moxie_sciadv", "hoffman_ez"))
def _m7(r):
    if "isru" not in r.goals:
        return None
    return Hit("ISRU goal", [A("r_oxygen_plant", "Ascent and breathing oxygen"), A("r_excavator", "Feedstock and shielding"),
                             A("x_spares", "A plant is maintenance heavy"), A("x_eva_tools", "Service the plant")],
               observed="isru", threshold="goal flag")


@rule("M8", "science", "Construction", "N", srcs=("nasa_3d_habitat", "hoffman_ez"),
      explain="Prefabricated frames need a lot of EVA time. No tool list has been published.")
def _m8(r):
    if "construction" not in r.goals:
        return None
    return Hit("Construction goal", [A("x_construct", "Fasteners, torque tools, cable and pipe"),
                                     A("x_hab_printer", "Printed shelter", priority="optional"),
                                     A("r_excavator", "Site preparation"), A("x_eva_tools", "General assembly")],
               observed="construction", threshold="goal flag")


# =============================================================== MISSION (stay, power, vehicle)
@rule("P1", "mission", "Power source drives what must be carried", "P",
      evidence=["Fission surface power 40 kWe class, reactor under 6 t", "Dust loss about 0.2% per sol on arrays"],
      srcs=("nasa_fsp", "insight_dust"))
def _p1(r):
    if r.power == "fission":
        return Hit("Fission power", [A("p_fission", "Power independent of sun and dust"), A("p_cable", "Reach habitat and plant")],
                   observed="fission", threshold="power flag")
    if r.power == "solar":
        return Hit("Solar power", [A("p_solar", "Daytime power"), A("p_array_cleaning", "Dust loss is steady"),
                                   A("p_storm_storage", "Storm season")],
                   observed="solar", threshold="power flag")
    return None


@rule("V1", "mission", "The traveller for this route", "P",
      evidence=["SEV concept 10 km/h, 125 km, 14 days", "Perseverance top speed about 152 m/h"],
      srcs=("wiki_sev", "nasa_rover_page"))
def _v1(r):
    from . import catalog
    key = next((i.id for i in catalog.ITEMS.values() if i.planner_vehicle == r.vehicle), None)
    if not key or r.vehicle == "astronaut":
        return None
    adds = [A(key, "The traveller chosen for this route", qty=1, priority="critical")]
    if r.crewed_rover:
        adds.append(A("g_tool_carrier", "Hand tools ride on the vehicle"))
    return Hit(f"Route is planned for: {r.vehicle.replace('_', ' ')}", adds, observed=r.vehicle, threshold="vehicle")


@rule("L1", "mission", "Short stay: the rover is the habitat", "E",
      evidence=["Two crew land and live in a pressurized rover for about 30 sols"], srcs=("m2m_2023",))
def _l1(r):
    if r.archetype != "short_stay" and r.stay_sols > 45:
        return None
    return Hit(f"Stay of {n(r.stay_sols, 0)} sols", [A("v_pressurized_rover", "Mobility and living space in one", qty=1)],
               observed=f"{n(r.stay_sols, 0)} sols", threshold="30 sols")


@rule("L2", "mission", "Stays beyond a month need long-duration care", "I",
      evidence=["exercise_sols", "dust_pel_days"], srcs=("std3001_v1_s4", "nasa_dust_pel", "wang_dust"),
      explain="NASA's dust limit only covers 30 days and its bone and muscle standards apply to longer stays.")
def _l2(r):
    if r.stay_sols <= THRESHOLDS["exercise_sols"][0]:
        return None
    return Hit(f"Stay of {n(r.stay_sols, 0)} sols", [
        A("b_exercise", "Bone and muscle standards"), A("med_ki", "Perchlorate; no dust limit exists beyond 30 days"),
        A("x_spares", "No resupply in transit"), A("x_eva_tools", "Repairs"), A("suit_spares", "Suit wear over many EVAs")],
        observed=f"{n(r.stay_sols, 0)} sols", threshold="30 sols")


@rule("L3", "mission", "Long stay: habitat, onsite care and repair capacity", "E",
      evidence=["long_stay_sols"], srcs=("dra5", "std3001_s3", "nasa_podcast_spares"))
def _l3(r):
    if r.stay_sols < THRESHOLDS["long_stay_sols"][0]:
        return None
    return Hit(f"Stay of {n(r.stay_sols, 0)} sols", [
        A("b_habitat", "Living space for up to about 550 days"), A("med_iv", "Make fluids on site"),
        A("med_dental", "Tooth and mouth emergencies"), A("med_advanced", "Definitive care on site"),
        A("x_printer", "Repair parts"), A("x_diagnostics", "Find and fix faults"),
        A("m_field_cache", "Extends how far teams can go", priority="optional")],
        observed=f"{n(r.stay_sols, 0)} sols", threshold="300 sols")


@rule("L4", "mission", "Rescue mission", "P", evidence=["Pressurized rover seats 4 in an emergency"], srcs=("dra5", "wiki_sev"))
def _l4(r):
    if r.archetype != "rescue":
        return None
    return Hit("Rescue archetype", [
        A("v_pressurized_rover", "Seats four in an emergency", qty=1, priority="critical"),
        A("m_field_cache", "Supplies placed ahead"), A("n_beacon", "Find a crew member who cannot call"),
        A("h_portable_shelter", "Cover at the casualty")], observed="rescue", threshold="archetype")


def evaluate(r: Resolved):
    """Run every rule and return (hits, warnings). hits is a list of (Rule, Hit)."""
    out = []
    for rl in RULES:
        h = rl.fn(r)
        if h is not None:
            out.append((rl, h))
    return out


GROUP_SEVERITY = {"core": "critical", "safety": "critical", "terrain": "recommended", "science": "recommended",
                  "mission": "recommended"}
GROUP_LABEL = {"core": "Every mission", "safety": "Safety", "terrain": "Terrain", "science": "Science", "mission": "Mission"}
