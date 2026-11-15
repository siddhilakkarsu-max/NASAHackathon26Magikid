"""The route planner's crewed vehicles (config.VEHICLES) and the mission planner's (config.MISSION_VEHICLES)
describe the same three vehicles, so they must carry the same numbers, and every mission range must fit
in the battery it is driven on."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import (CONSUMABLE_RESERVE, CONSUMABLE_SOURCES, MISSION_VEHICLE_OF, MISSION_VEHICLES,  # noqa: E402
                    PRIORITIES, SEASONS, VEHICLE_POWER, VEHICLES, WALKER)
import mission  # noqa: E402

SHARED = ("label", "max_slope", "base_speed_kmh", "suit_factor", "sand_penalty", "rough_penalty", "uses_slip_table")


def largest_reserve():
    """The biggest reserve the mission planner can hold back (any priority, any season)."""
    return max(mission._reserve(p, s) for p in PRIORITIES for s in SEASONS)


class VehicleLists(unittest.TestCase):
    def test_pairs(self):
        self.assertEqual(MISSION_VEHICLE_OF, {"on_foot": "astronaut", "four_wheel": "unpressurized_rover",
                                              "buggy": "pressurized_rover"})
        for m in MISSION_VEHICLE_OF:
            self.assertIn(m, MISSION_VEHICLES)

    def test_shared_fields_are_equal(self):
        for m, r in MISSION_VEHICLE_OF.items():
            mv, rv = MISSION_VEHICLES[m], VEHICLES[r]
            for f in SHARED:
                self.assertEqual(mv[f], rv[f], f"{m}.{f} vs {r}.{f}")

    def test_battery_and_loads_in_matching_units(self):
        for m, r in MISSION_VEHICLE_OF.items():
            mv, c = MISSION_VEHICLES[m], VEHICLES[r].get("consumables") or {}
            if "energy_capacity_kwh" not in c:
                self.assertIsNone(mv["battery_wh"], m)
                continue
            self.assertAlmostEqual(mv["battery_wh"], 1000 * c["energy_capacity_kwh"], places=3, msg=m)
            self.assertAlmostEqual(mv["wh_per_km"], 1000 * c["energy_per_km_kwh"], places=3, msg=m)
            self.assertAlmostEqual(mv["hotel_w"], 1000 * c["energy_idle_kw"], places=3, msg=m)

    def test_mass(self):
        for m, r in MISSION_VEHICLE_OF.items():
            want = VEHICLE_POWER[r]["mass_kg"] if r in VEHICLE_POWER else WALKER["body_kg"] + WALKER["suit_kg"]
            self.assertEqual(MISSION_VEHICLES[m]["mass_kg"], want, m)

    def test_suited_matches_the_crewed_profile(self):
        for m, r in MISSION_VEHICLE_OF.items():
            self.assertEqual(MISSION_VEHICLES[m]["suited"], "o2_rate_kg_per_h" in VEHICLES[r]["consumables"], m)

    def test_range_fits_the_battery_after_the_reserve(self):
        """Out and back at range_km on flat firm ground (drive energy + hotel load while driving at the base
        speed + the hour on site) must fit in the battery after the largest reserve the planner can hold."""
        keep = 1 - largest_reserve()
        self.assertGreaterEqual(largest_reserve(), max(CONSUMABLE_RESERVE["normal"], CONSUMABLE_RESERVE["dust_season"]))
        for k, v in MISSION_VEHICLES.items():
            if not v["battery_wh"]:
                continue
            km = 2 * v["range_km"]
            wh = km * v["wh_per_km"] + v["hotel_w"] * (km / v["base_speed_kmh"] + mission.SITE_HOURS)
            self.assertLessEqual(wh, v["battery_wh"] * keep, f"{k}: {wh:.0f} Wh for {v['range_km']} km out and back")

    def test_paired_profiles_are_sourced(self):
        for r in MISSION_VEHICLE_OF.values():
            src = VEHICLES[r]["consumable_source"]
            self.assertNotEqual(src, "estimate", r)
            self.assertTrue(CONSUMABLE_SOURCES.get(src), r)


if __name__ == "__main__":
    unittest.main()
