"""
Consumables and dose budget.

Every line carries its formula, so a reader can see how the number was made and which input is
published and which is a choice. Rates come from MISSION_EQUIPMENT_RESEARCH.md.
"""
import math

import physics

from .context import Resolved
from .sources import CONFIDENCE, sources

# Published or verified rates. The tag says how far to trust each.
RATES = {
    "suit_o2_design": (0.114, "kg/h", "V", ("sbir_mars_plss",), "NASA Mars suit sizing basis: 1.9 g/min averaged over 8 h"),
    "suit_o2_nominal": (0.076, "kg/h", "E", ("bvad2",), "NASA baseline document Rev 2, current EVA with CO2 stored"),
    "suit_o2_walkback": (0.181, "kg/h", "E", ("norcross_walkback", "chappell_eva"), "Apollo walk-back rate, 0.4 lb/h"),
    "drink": (0.24, "kg/h", "V", ("std3001_v2_s11",), "NASA-STD-3001 minimum suited hydration, 240 mL per EVA hour"),
    "cooling": (0.44, "kg/h", "E", ("chappell_eva",), "Apollo nominal cooling water; Mars PLSS differs"),
    "cabin_o2": (0.818, "kg/crew-day", "P", ("frontiers_bvad",), "BVAD (older revision, via a 2025 review)"),
    "water_total": (4.350, "kg/crew-day", "P", ("frontiers_bvad",),
                    "BVAD total water use. Includes water in food and metabolic water, so supply need is lower"),
    "food_shipped": (1.831, "kg/crew-day", "E", ("lynch_logistics", "frontiers_bvad"), "as shipped, including packaging"),
    "hygiene": (0.781, "kg/crew-day", "P", ("frontiers_bvad",), "BVAD"),
    "clothing": (0.22, "kg/crew-day", "E", ("lynch_logistics",), "NASA 2015 consumables model; BVAD range 0.206 to 1.690"),
    "o2_makeup": (0.289, "kg/crew-day", "I", ("frontiers_bvad",),
                  "0.818 minus 51 percent of the 1.040 kg of CO2 produced; ignores leakage"),
    "water_makeup": (0.087, "kg/crew-day", "I", ("frontiers_bvad",), "4.350 kg at 98 percent water recovery"),
}
DOSE_RATE_MSV_DAY = 0.67        # SwRI / MSL RAD, surface dose equivalent, Aug 2012 to Jun 2013 (V)
CAREER_LIMIT_MSV = 600.0        # NASA-STD-3001 Vol 1 (V)
HABITAT_CAP_MSV_DAY = 0.9       # NASA-STD-3001 Vol 1, surface systems (V)
CARRY_CAP_KG_PER_PERSON = 22.7  # 50 lbm tool and sample allowance in NASA's Mars suit study (E)


def _line(label, value, unit, formula, conf, srcs=(), per=None, note=""):
    return {"label": label, "value": None if value is None else round(value, 3), "unit": unit, "per": per,
            "formula": formula, "confidence": {"tag": conf, **CONFIDENCE[conf]}, "sources": sources(srcs), "note": note}


def _rate_line(label, key, hours, per, formula_tail=""):
    rate, unit, conf, srcs, why = RATES[key]
    return _line(label, rate * hours, "kg", f"{rate} {unit} x {hours:g} h{formula_tail}", conf, srcs, per=per, note=why)


def personal_allowance_kg(days):
    for limit, kg in ((14, 5), (60, 10), (360, 25), (1100, 50)):
        if days <= limit:
            return kg
    return 50


def size_consumables(r: Resolved, carry=None):
    """carry: the engine's carry-load result, so the route's oxygen can include what the team carries."""
    groups = []

    # ---- suit consumables
    h = r.eva_hours
    suit = [
        _rate_line("Suit oxygen, one EVA (design rate)", "suit_o2_design", h, "per crew member per EVA"),
        _rate_line("Suit oxygen, one EVA (current-EVA rate)", "suit_o2_nominal", h, "per crew member per EVA"),
        _rate_line("Suit drinking water, one EVA", "drink", h, "per crew member per EVA"),
        _rate_line("Suit cooling water, one EVA (Apollo basis)", "cooling", h, "per crew member per EVA"),
    ]
    total_hours = r.crew * r.eva_days * h
    suit.append(_line("Suit oxygen over the whole stay (design rate)", RATES["suit_o2_design"][0] * total_hours, "kg",
                      f"0.114 kg/h x {h:g} h x {r.eva_days} EVA days x {r.crew} crew", "V", ("sbir_mars_plss",),
                      per="mission", note=f"{total_hours:g} crew EVA hours. EVA days are an assumption unless supplied."))
    if r.route and r.route.one_way_h:
        suit.append(_rate_line("Walk-back reserve for this route (one way)", "suit_o2_walkback", r.route.one_way_h,
                               "per crew member",
                               f"  (one-way time {r.route.one_way_h:g} h from the planner)"))
    groups.append({"id": "suit", "label": "Suit consumables", "lines": suit})

    # ---- cabin and logistics
    d, c = r.stay_days, r.crew
    cd = c * d
    cabin = [
        _line("Cabin oxygen, gross", RATES["cabin_o2"][0] * cd, "kg", f"0.818 kg x {c} crew x {d:.0f} days", "P",
              RATES["cabin_o2"][3], per="mission"),
        _line("Cabin oxygen make-up if CO2 is recycled", RATES["o2_makeup"][0] * cd, "kg",
              f"0.289 kg x {c} crew x {d:.0f} days", "I", RATES["o2_makeup"][3], per="mission",
              note=RATES["o2_makeup"][4]),
        _line("Water, total use", RATES["water_total"][0] * cd, "kg", f"4.350 kg x {c} crew x {d:.0f} days", "P",
              RATES["water_total"][3], per="mission", note=RATES["water_total"][4]),
        _line("Water make-up at 98 percent recovery", RATES["water_makeup"][0] * cd, "kg",
              f"0.087 kg x {c} crew x {d:.0f} days", "I", RATES["water_makeup"][3], per="mission",
              note=RATES["water_makeup"][4]),
        _line("Food, as shipped", RATES["food_shipped"][0] * cd, "kg", f"1.831 kg x {c} crew x {d:.0f} days", "E",
              RATES["food_shipped"][3], per="mission"),
        _line("Hygiene supplies", RATES["hygiene"][0] * cd, "kg", f"0.781 kg x {c} crew x {d:.0f} days", "P",
              RATES["hygiene"][3], per="mission"),
        _line("Clothing", RATES["clothing"][0] * cd, "kg", f"0.22 kg x {c} crew x {d:.0f} days", "E",
              RATES["clothing"][3], per="mission", note=RATES["clothing"][4]),
        _line("Personal items", personal_allowance_kg(d) * c, "kg",
              f"{personal_allowance_kg(d)} kg step for a {d:.0f} day stay x {c} crew", "E", ("lynch_logistics",),
              per="mission"),
    ]
    groups.append({"id": "cabin", "label": "Cabin and crew supplies", "lines": cabin})

    # ---- this route, as the planner costed it (terrain, reserve, dust), plus what the team carries
    loaded = None
    if r.route and (r.route.o2_used_kg is not None or r.route.energy_used_kwh is not None):
        lines, rt = [], r.route
        climb = (f"climbs {rt.elevation_gain_m:g} m out and {rt.elevation_loss_m:g} m back"
                 if rt.elevation_gain_m is not None else "no elevation data")
        if rt.o2_used_kg is not None:
            if rt.slope_o2_factor is not None and rt.o2_flat_pace_h is not None:
                formula = (f"0.114 kg/h x {rt.o2_flat_pace_h:g} h at flat-ground pace x slope effect "
                           f"{rt.slope_o2_factor:g}")
            else:
                formula = f"0.114 kg/h x {rt.round_trip_h:g} h"
            lines.append(_line("Round-trip suit oxygen on this route", rt.o2_used_kg, "kg",
                               formula, "I", ("sbir_mars_plss", "minetti2002"),
                               per="this route",
                               note=f"Route {climb}. Effort rises uphill and falls downhill (Minetti 2002); "
                                    f"capacity {rt.o2_max_kg} kg, so {rt.o2_pct:g}% used."))
            if rt.o2_flat_kg is not None:
                lines.append(_line("Same distance on flat, firm ground", rt.o2_flat_kg, "kg",
                                   f"0.114 kg/h x 2 x {rt.distance_km:g} km at flat walking pace", "I", ("sbir_mars_plss",),
                                   per="comparison",
                                   note=f"This ground costs {rt.terrain_o2_factor:g}x that: slow sand and rough rock "
                                        "stretch the time, slopes change the effort."))
            if rt.o2_usable_kg is not None:
                lines.append(_line(f"Usable after the {rt.reserve_pct:g}% reserve", rt.o2_usable_kg, "kg",
                                   f"{rt.o2_max_kg} kg x (1 - {rt.reserve_pct / 100:g})", "I", ("team_resources",),
                                   per="this route", note="15 percent, 20 percent in the dust-storm season (Ls 180-330)."))
            per_person = (carry["load_kg"] / max(carry["team_size"], 1)) if carry else 0.0
            if r.suited and per_person > 0 and r.vehicle == "astronaut":
                from config import WALKER
                f = physics.load_factor(per_person, WALKER["body_kg"], WALKER["suit_kg"])
                o2_loaded = rt.o2_used_kg * f
                loaded = {"o2_kg": round(o2_loaded, 3), "usable_kg": rt.o2_usable_kg, "factor": round(f, 3),
                          "per_person_kg": round(per_person, 1),
                          "over_usable": rt.o2_usable_kg is not None and o2_loaded > rt.o2_usable_kg}
                lines.append(_line("With the kit's hand-carried load", o2_loaded, "kg",
                                   f"{rt.o2_used_kg:g} kg x ({WALKER['body_kg']:g} + {WALKER['suit_kg']:g} + "
                                   f"{per_person:.1f}) / ({WALKER['body_kg']:g} + {WALKER['suit_kg']:g})", "I",
                                   ("minetti2002", "ices2026_mars_suit"), per="this route",
                                   note=f"{per_person:.1f} kg per person. Walking cost is per kilogram moved, so load "
                                        "is charged in proportion to body + suit + load. Body mass is an assumption."))
        if rt.energy_used_kwh is not None:
            lines.append(_line("Round-trip vehicle energy", rt.energy_used_kwh, "kWh",
                               f"capacity {rt.energy_max_kwh} kWh ({rt.energy_pct}%)", "I", (), per="this route",
                               note="Driving plus housekeeping loads for the route's hours. The crew rover's "
                                    "battery, hotel load and energy per km are from NASA's Mars pressurized rover "
                                    "study (Chappell et al. 2022)."))
            if rt.climb_kwh is not None:
                lines.append(_line("of which climbing", rt.climb_kwh, "kWh", f"mass x 3.711 m/s2 x height, route {climb}",
                                   "I", (), per="this route",
                                   note="Energy to lift the vehicle up each climb. A lower bound: motor losses add more."))
        if rt.sunlight_pct is not None:
            if rt.recharge_sols is not None:
                lines.append(_line("Sols of sunlight to recharge", rt.recharge_sols, "sols",
                                   f"{rt.energy_used_kwh:g} kWh / {rt.solar_kwh_per_sol:g} kWh per sol",
                                   "I", ("insight_dust",), per="this route",
                                   note=f"Dust lets about {rt.sunlight_pct:g}% of direct sunlight through this season "
                                        f"(opacity {rt.dust_opacity:g}, from the team's weather data)."))
            elif rt.recharge_h is not None:
                lines.append(_line("Hours of charging afterwards", rt.recharge_h, "h",
                                   f"2 h of charging per hour driven / {rt.sunlight_pct:g}% sunlight", "I",
                                   ("team_resources",), per="this route",
                                   note="The 2:1 charge ratio is the team's research figure for battery rovers, "
                                        f"not a NASA one. Dust opacity {rt.dust_opacity:g} this season."))
            elif rt.power_source == "nuclear":
                lines.append(_line("Dust effect on power", 0, "kWh", f"{rt.sunlight_pct:g}% sunlight, nuclear source",
                                   "P", ("nasa_rover_page",), per="this route",
                                   note="A radioisotope generator does not need sunlight, so dust storms do not cut "
                                        "its power."))
        groups.append({"id": "route", "label": "This route", "lines": lines})

    # ---- radiation
    dose = round(DOSE_RATE_MSV_DAY * d, 1)
    radiation = {
        "surface_dose_msv": dose, "rate_msv_day": DOSE_RATE_MSV_DAY, "career_limit_msv": CAREER_LIMIT_MSV,
        "career_pct": round(100 * dose / CAREER_LIMIT_MSV, 1), "habitat_cap_msv_day": HABITAT_CAP_MSV_DAY,
        "formula": f"{DOSE_RATE_MSV_DAY} mSv/day x {d:.0f} days",
        "confidence": {"tag": "V", **CONFIDENCE["V"]}, "sources": sources(("swri_rad", "std3001_v1_s4")),
        "caveat": "Surface only. The measured dose in cruise was 1.8 mSv per day, so transit adds far more. The "
                  "0.67 figure is a measured dose equivalent; the 600 mSv limit is a NASA effective dose, and the two "
                  "are not directly comparable.",
    }

    check = planner_o2_check(r, loaded)
    return {"groups": groups, "radiation": radiation, "planner_check": check, "route_with_load": loaded}


def planner_o2_check(r: Resolved, loaded=None):
    """How the planner's suit oxygen is set up, and what this route needs from it."""
    try:
        from config import VEHICLES
        c = VEHICLES["astronaut"]["consumables"]
        rate, cap = c["o2_rate_kg_per_h"], c["o2_capacity_kg"]
    except Exception:
        return None
    design = RATES["suit_o2_design"][0]
    out = {"planner_rate_kg_h": rate, "planner_capacity_kg": cap, "nasa_design_rate_kg_h": design,
           "message": (f"Suit oxygen uses NASA's Mars design basis: {rate} kg/h with {cap} kg carried, sized for "
                       f"8 h. On a planned route the rate follows slope and carried load."),
           "confidence": {"tag": "V", **CONFIDENCE["V"]}, "sources": sources(("sbir_mars_plss", "minetti2002"))}
    rt = r.route
    if rt and rt.o2_used_kg is not None and r.suited:
        out["route_o2_kg"] = rt.o2_used_kg
        out["message"] += f" This round trip needs {rt.o2_used_kg:g} kg, {rt.o2_pct:g}% of the suit's supply"
        if loaded:
            out["route_o2_with_load_kg"] = loaded["o2_kg"]
            out["message"] += (f", or {loaded['o2_kg']:.2f} kg with {loaded['per_person_kg']:g} kg carried per person")
        if rt.o2_usable_kg is not None:
            out["message"] += f". {rt.o2_usable_kg:g} kg is usable after the {rt.reserve_pct:g}% reserve."
        else:
            out["message"] += "."
    return out
