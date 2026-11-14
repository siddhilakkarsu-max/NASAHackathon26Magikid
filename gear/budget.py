"""
Consumables and dose budget.

Every line carries its formula, so a reader can see how the number was made and which input is
published and which is a choice. Rates come from MISSION_EQUIPMENT_RESEARCH.md.
"""
import math

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


def size_consumables(r: Resolved):
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

    # ---- route energy, only when a route was planned
    if r.route and (r.route.o2_used_kg is not None or r.route.energy_used_kwh is not None):
        lines = []
        rt = r.route
        if rt.o2_used_kg is not None:
            lines.append(_line("Planner: round-trip suit oxygen", rt.o2_used_kg, "kg",
                               f"planner rate x {rt.round_trip_h:g} h round trip; capacity {rt.o2_max_kg} kg "
                               f"({rt.o2_pct}%)", "I", ("sbir_mars_plss",), per="this route",
                               note="Uses the planner's own rate. See the planner check below."))
        if rt.energy_used_kwh is not None:
            lines.append(_line("Planner: round-trip vehicle energy", rt.energy_used_kwh, "kWh",
                               f"capacity {rt.energy_max_kwh} kWh ({rt.energy_pct}%)", "I", (), per="this route",
                               note="The crew rover's loads are a labelled engineering estimate."))
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

    check = planner_o2_check(r)
    return {"groups": groups, "radiation": radiation, "planner_check": check}


def planner_o2_check(r: Resolved):
    """Compare the planner's own astronaut O2 numbers with NASA's Mars design rate."""
    try:
        from config import VEHICLES
        c = VEHICLES["astronaut"]["consumables"]
        rate, cap = c["o2_rate_kg_per_h"], c["o2_capacity_kg"]
    except Exception:
        return None
    design = RATES["suit_o2_design"][0]
    out = {"planner_rate_kg_h": rate, "planner_capacity_kg": cap, "nasa_design_rate_kg_h": design,
           "planner_hours_at_design_rate": round(cap / design, 2),
           "message": (f"The planner assumes {rate} kg/h and {cap} kg carried, which lasts 8 h. At NASA's Mars design "
                       f"rate of {design} kg/h the same {cap} kg lasts {cap / design:.1f} h."),
           "confidence": {"tag": "V", **CONFIDENCE["V"]}, "sources": sources(("sbir_mars_plss",))}
    if r.route and r.route.round_trip_h and r.vehicle == "astronaut":
        need = design * r.route.round_trip_h
        out["route_need_at_design_kg"] = round(need, 3)
        out["route_need_pct_of_capacity"] = round(100 * need / cap)
        out["message"] += (f" This {r.route.round_trip_h:g} h round trip needs {need:.2f} kg at the design rate, "
                           f"{100 * need / cap:.0f}% of the suit's capacity.")
    return out
