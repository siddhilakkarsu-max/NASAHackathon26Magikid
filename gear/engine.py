"""
Turns a MissionContext into a kit manifest.

Pipeline: resolve defaults -> run rules -> merge hits per item -> decide who carries what ->
total the mass -> size consumables -> collect warnings and evidence counts.
"""
from typing import Optional

from . import catalog, rules as rule_mod
from .budget import CARRY_CAP_KG_PER_PERSON, size_consumables
from .context import MissionContext, Resolved, resolve, ARCHETYPES
from .sources import CONFIDENCE

RANK = {"optional": 0, "recommended": 1, "critical": 2}
PRIORITY_LABEL = {"critical": "Critical", "recommended": "Recommended", "optional": "Optional"}


def _default_qty(item, r: Resolved):
    return {"astronaut": r.crew, "team": r.teams, "mission": 1}[item.per]


def _is_vehicle(item):
    return item.planner_vehicle is not None or item.id.startswith("v_")


def _prio(a, group):
    return a.priority or rule_mod.GROUP_SEVERITY[group]


def _collect(r: Resolved):
    """item_id -> {qty, priority, reasons[]}, plus the triggered rules and warnings."""
    hits = rule_mod.evaluate(r)
    merged, warnings, triggered = {}, [], []
    for rl, hit in hits:
        triggered.append({
            **rl.public(), "detail": hit.detail, "observed": hit.observed, "threshold": hit.threshold,
            "items": [a.item for a in hit.adds], "warnings": hit.warnings,
        })
        warnings.extend(hit.warnings)
        for a in hit.adds:
            item = catalog.get(a.item)
            pr = _prio(a, rl.group)
            slot = merged.setdefault(a.item, {"qty": 0, "priority": "optional", "reasons": []})
            slot["qty"] = max(slot["qty"], a.qty if a.qty is not None else _default_qty(item, r))
            if RANK[pr] > RANK[slot["priority"]]:
                slot["priority"] = pr
            slot["reasons"].append({"rule": rl.id, "group": rl.group, "why": a.why, "detail": hit.detail,
                                    "observed": hit.observed, "threshold": hit.threshold})
    return merged, warnings, triggered


def _apply_adjustments(merged, adjustments, r, warnings):
    applied = {"added": [], "removed": []}
    if not adjustments:
        return applied
    for a in adjustments.get("add", []):
        iid = a["item_id"]
        if iid not in catalog.ITEMS:
            warnings.append(f"Planner asked to add unknown item '{iid}'; ignored.")
            continue
        item = catalog.get(iid)
        qty = a.get("qty") or _default_qty(item, r)
        slot = merged.setdefault(iid, {"qty": 0, "priority": "optional", "reasons": []})
        slot["qty"] = max(slot["qty"], qty)
        pr = a.get("priority") or "recommended"
        if RANK[pr] > RANK[slot["priority"]]:
            slot["priority"] = pr
        slot["reasons"].append({"rule": "PLANNER", "group": "planner", "why": a.get("reason") or "Added by the planning agent",
                                "detail": "Added by the planning agent", "observed": None, "threshold": None})
        applied["added"].append({"item_id": iid, "qty": qty, "reason": a.get("reason")})
    for a in adjustments.get("remove", []):
        iid = a["item_id"]
        slot = merged.pop(iid, None)
        if slot is None:
            continue
        if slot["priority"] == "critical":
            warnings.append(f"Planner removed '{catalog.get(iid).name}', which rules marked critical: "
                            f"{a.get('reason') or 'no reason given'}.")
        applied["removed"].append({"item_id": iid, "reason": a.get("reason"), "was_priority": slot["priority"],
                                   "rules": sorted({x['rule'] for x in slot['reasons']})})
    return applied


def _assign_carriers(merged, r: Resolved, warnings):
    """Decide who carries each item and check the hand-carry load for one EVA team."""
    team = min(2, r.crew)
    cap = CARRY_CAP_KG_PER_PERSON * team
    rows = {}
    rover_in_kit = r.crewed_rover or "v_pressurized_rover" in merged
    for iid, slot in merged.items():
        item = catalog.get(iid)
        carrier = "vehicle" if _is_vehicle(item) else item.carried_by
        moved = None
        if carrier == "astronaut" and item.eva_carry > 0 and r.crewed_rover:
            carrier, moved = "rover", "Rides on the crewed rover instead of the astronaut's back"
        rows[iid] = {"carrier": carrier, "moved": moved}

    def load():
        total, unknown = 0.0, 0
        for iid, row in rows.items():
            it = catalog.get(iid)
            if row["carrier"] == "astronaut" and it.eva_carry > 0:
                if it.mass_kg is None:
                    unknown += 1
                else:
                    total += it.mass_kg * it.eva_carry
        return total, unknown

    total, unknown = load()
    adjusted = []
    if total > cap:
        movable = sorted((iid for iid, row in rows.items() if row["carrier"] == "astronaut" and catalog.get(iid).eva_carry > 0
                          and catalog.get(iid).mass_kg),
                         key=lambda i: (RANK[merged[i]["priority"]], -catalog.get(i).mass_kg * catalog.get(i).eva_carry))
        target = "rover"
        if not rover_in_kit:
            cart = catalog.get("m_hand_cart")
            merged.setdefault("m_hand_cart", {"qty": 1, "priority": "recommended", "reasons": [{
                "rule": "LOAD", "group": "safety", "why": "Hand-carried load is over the carry limit and no vehicle is in the kit",
                "detail": f"{total:.1f} kg against {cap:.1f} kg", "observed": f"{total:.1f} kg", "threshold": f"{cap:.1f} kg"}]})
            rows["m_hand_cart"] = {"carrier": "astronaut", "moved": None}
            target = "cart"
            total += cart.mass_kg
        for iid in movable:
            if total <= cap and target == "rover":
                break
            if iid == "m_hand_cart":
                continue
            it = catalog.get(iid)
            if target == "cart" and iid != "m_hand_cart":
                rows[iid] = {"carrier": "cart", "moved": "Carried on the hand cart"}
            else:
                rows[iid] = {"carrier": "rover", "moved": "Moved to the rover: the team's hand-carry cap was exceeded"}
            total -= it.mass_kg * it.eva_carry
            adjusted.append(iid)
        if target == "cart":
            total, unknown = load()
        else:
            total, unknown = load()
    over = total > cap
    if over:
        warnings.append(f"Hand-carried load is {total:.1f} kg for a team of {team}, over the {cap:.1f} kg limit, and "
                        "nothing more can be moved.")
    return rows, {"team_size": team, "cap_kg": round(cap, 1), "load_kg": round(total, 1), "items_without_mass": unknown,
                  "over_cap": over, "moved": adjusted,
                  "basis": "22.7 kg (50 lbm) tool and sample allowance per person in NASA's Mars suit study; the "
                           "weight of the suit itself is not counted",
                  "confidence": {"tag": "E", **CONFIDENCE["E"]}}


def build_manifest(ctx: MissionContext, adjustments: Optional[dict] = None, resolved: Optional[Resolved] = None):
    r = resolved or resolve(ctx)
    merged, warnings, triggered = _collect(r)
    applied = _apply_adjustments(merged, adjustments, r, warnings)
    rows, carry = _assign_carriers(merged, r, warnings)

    budget = size_consumables(r)
    lines = {ln["label"]: ln["value"] for g in budget["groups"] for ln in g["lines"]}
    # what one crew member uses on one EVA, shown on the consumables rows
    per_use = {"c_suit_o2": lines.get("Suit oxygen, one EVA (design rate)"),
               "c_suit_water": lines.get("Suit drinking water, one EVA"),
               "c_suit_cooling": lines.get("Suit cooling water, one EVA (Apollo basis)")}

    items, by_cat = [], {}
    mass_by_carrier, unknown_mass = {}, []
    for iid, slot in merged.items():
        item = catalog.get(iid)
        row = rows[iid]
        pub = item.public()
        mass_known = item.mass_kg is not None
        total_mass = round(item.mass_kg * slot["qty"], 3) if mass_known else None
        entry = {**pub, "qty": slot["qty"], "priority": slot["priority"], "priority_label": PRIORITY_LABEL[slot["priority"]],
                 "carried_by": row["carrier"], "moved_note": row["moved"], "total_mass_kg": total_mass,
                 "per_use_kg": per_use.get(iid),
                 "reasons": slot["reasons"], "rules": sorted({x["rule"] for x in slot["reasons"]})}
        items.append(entry)
        by_cat.setdefault(item.category, []).append(entry)
        if row["carrier"] != "vehicle":
            if mass_known:
                mass_by_carrier[row["carrier"]] = round(mass_by_carrier.get(row["carrier"], 0) + total_mass, 2)
            elif per_use.get(iid) is None and iid != "c_cabin":   # consumables are sized in the budget, not weighed here
                unknown_mass.append(item.name)

    for lst in by_cat.values():
        lst.sort(key=lambda e: (-RANK[e["priority"]], e["name"]))
    groups = [{"id": cid, "label": label, "items": by_cat[cid]} for cid, label in catalog.CATEGORIES if cid in by_cat]

    conf_counts = {t: 0 for t in CONFIDENCE}
    for e in items:
        conf_counts[e["confidence"]["tag"]] += 1
    proposals = [e["name"] for e in items if e["confidence"]["tag"] in ("N", "I") and e["priority"] != "optional"]

    flags = []
    if unknown_mass:
        flags.append(f"{len(unknown_mass)} items have no published mass, so the mass totals are a lower bound.")
    n_no_source = conf_counts["N"]
    if n_no_source:
        flags.append(f"{n_no_source} items have no published specification and are proposals, not specifications.")
    if r.assumptions:
        flags.append(f"{len(r.assumptions)} inputs were filled from defaults. See assumptions.")

    a = ARCHETYPES[r.archetype]
    return {
        "context": {"archetype": r.archetype, "archetype_label": a["label"], "archetype_summary": a["summary"],
                    "crew": r.crew, "teams": r.teams, "stay_sols": r.stay_sols, "stay_days": round(r.stay_days, 1),
                    "goals": sorted(r.goals), "hazards": sorted(r.hazards), "vehicle": r.vehicle,
                    "eva_hours": r.eva_hours, "eva_days": r.eva_days, "power": r.power, "region": r.region,
                    "sample_sites": r.sample_sites, "route": r.route.model_dump() if r.route else None,
                    "terrain": r.terrain.model_dump() if r.terrain else None},
        "assumptions": r.assumptions,
        "summary": {"items": len(items), "critical": sum(e["priority"] == "critical" for e in items),
                    "recommended": sum(e["priority"] == "recommended" for e in items),
                    "optional": sum(e["priority"] == "optional" for e in items),
                    "rules_checked": len(rule_mod.RULES), "rules_triggered": len(triggered),
                    "confidence_counts": conf_counts},
        "groups": groups,
        "items": items,
        "rules": triggered,
        "carry": carry,
        "mass": {"by_carrier_kg": mass_by_carrier, "items_without_mass": unknown_mass,
                 "note": "Vehicles are not summed. Consumables are sized separately in the budget."},
        "budget": budget,
        "warnings": list(dict.fromkeys(warnings)),
        "flags": flags,
        "adjustments": applied,
        "thin_evidence": proposals,
    }
