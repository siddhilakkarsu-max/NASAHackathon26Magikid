"""
Tests for judging loose ground and dust from measured thermal inertia.   Run:  python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gear import engine, rules, tools  # noqa: E402
from gear.context import MissionContext, RouteStats, TerrainSignals  # noqa: E402
from gear.sources import SOURCES  # noqa: E402

BASE = {"lat": 18.4447, "lon": 77.4508}
TARGET = {"lat": 18.50, "lon": 77.40}
ROUTE = RouteStats(max_slope_deg=8.0, one_way_h=0.2, round_trip_h=0.4, distance_km=1.0)


def kit(vehicle="astronaut", **terrain):
    return engine.build_manifest(MissionContext(archetype="traverse", vehicle=vehicle, route=ROUTE,
                                                terrain=TerrainSignals(max_slope_deg=8.0, **terrain)))


def hits(m):
    return {r["id"]: r for r in m["rules"]}


def ids(m):
    return {e["id"] for e in m["items"]}


class ThermalInertiaRules(unittest.TestCase):
    def test_loose_ground_from_thermal_inertia(self):
        sandy = kit(loose_fraction=0.0, ti_samples=30, ti_mean=230.0, ti_loose_fraction=0.8, sand_fraction=0.8,
                    dust_fraction=0.0)
        self.assertIn("T4", hits(sandy))
        self.assertIn("thermal inertia", hits(sandy)["T4"]["detail"])
        firm = kit(loose_fraction=0.9, ti_samples=30, ti_mean=450.0, ti_loose_fraction=0.05, sand_fraction=0.05,
                   dust_fraction=0.0)
        self.assertNotIn("T4", hits(firm))

    def test_falls_back_to_firmness(self):
        for samples in (0, None, 2):
            m = kit(loose_fraction=0.5, ti_samples=samples, ti_loose_fraction=0.0)
            self.assertIn("T4", hits(m), samples)
            self.assertIn("night-IR firmness", hits(m)["T4"]["detail"])
        self.assertNotIn("T4", hits(kit(loose_fraction=0.1)))

    def test_steep_loose_ground_uses_thermal_inertia(self):
        def steep(**t):
            return engine.build_manifest(MissionContext(
                archetype="traverse", route=RouteStats(max_slope_deg=22.0, one_way_h=0.2, round_trip_h=0.4, distance_km=1.0),
                terrain=TerrainSignals(max_slope_deg=22.0, **t)))
        self.assertIn("T1", hits(steep(loose_fraction=0.0, ti_samples=10, ti_loose_fraction=0.6)))
        self.assertNotIn("T1", hits(steep(loose_fraction=0.9, ti_samples=10, ti_loose_fraction=0.0)))

    def test_fine_dust_rule(self):
        dusty = kit(ti_samples=20, ti_mean=130.0, dust_fraction=0.6, ti_loose_fraction=0.9)
        self.assertIn("T13", hits(dusty))
        self.assertTrue({"suit_dust_removal", "h_hepa", "i_air_monitor"} <= ids(dusty))
        self.assertNotIn("T13", hits(kit(ti_samples=20, dust_fraction=0.1)))
        self.assertNotIn("T13", hits(kit(ti_samples=0, dust_fraction=0.9)))
        solar = kit(vehicle="mer", ti_samples=20, dust_fraction=0.6)
        self.assertTrue(any(x["rule"] == "T13" for x in next(e for e in solar["items"]
                                                              if e["id"] == "p_array_cleaning")["reasons"]))
        nuclear = kit(vehicle="perseverance", ti_samples=20, dust_fraction=0.6)
        self.assertIn("T13", hits(nuclear))
        self.assertNotIn("p_array_cleaning", ids(nuclear))

    def test_threshold_sources_exist(self):
        for key, (_v, _u, _c, srcs, _n) in rules.THRESHOLDS.items():
            for s in srcs:
                self.assertIn(s, SOURCES, key)
        self.assertEqual(rules.THRESHOLDS["ti_dust"][0], 150)
        self.assertEqual(rules.THRESHOLDS["ti_sand"][0], 300)


class RealRoute(unittest.TestCase):
    def test_route_reports_thermal_inertia(self):
        r = tools.call_tool("get_route_context", {"region": "jezero", "vehicle": "astronaut", "base": BASE,
                                                  "target": TARGET, "budget_hours": 8})
        self.assertTrue(r["route_found"], r)
        t = r["terrain"]
        self.assertGreaterEqual(t["ti_samples"], 3)
        self.assertTrue(50 <= t["ti_mean"] <= 2000, t["ti_mean"])
        self.assertLessEqual(t["ti_min"], t["ti_mean"])
        for k in ("dust_fraction", "sand_fraction", "ti_loose_fraction"):
            self.assertTrue(0 <= t[k] <= 1, (k, t[k]))
        self.assertAlmostEqual(t["dust_fraction"] + t["sand_fraction"], t["ti_loose_fraction"], places=6)


if __name__ == "__main__":
    unittest.main()
