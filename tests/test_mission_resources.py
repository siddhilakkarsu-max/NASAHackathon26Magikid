"""Mission planner resources: the way out and the way back costed separately (physics.path_resources)."""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import physics  # noqa: E402


class PathResources(unittest.TestCase):
    def test_flat_path_costs_the_same_both_ways(self):
        p = physics.path_resources(np.zeros(6), np.full(5, 20.0), 0.001, walker=True, slope_deg=np.zeros(5))
        self.assertAlmostEqual(p["out"], p["back"])
        self.assertAlmostEqual(p["out"], 0.1)
        self.assertAlmostEqual(p["slope_factor"], 1.0)
        self.assertEqual(p["gain_m"], 0.0)
        self.assertEqual(p["climb_wh_out"], 0.0)

    def test_walking_up_costs_more_out_than_back(self):
        z = np.arange(0.0, 11.0, 2.0)                       # 10 m up over 100 m: a 10 % grade
        p = physics.path_resources(z, np.full(5, 20.0), 0.001, walker=True)
        self.assertGreater(p["out"], p["back"])
        self.assertAlmostEqual(p["gain_m"], 10.0)
        self.assertAlmostEqual(p["loss_m"], 0.0)
        ratio = float(physics.minetti_cw(0.1) / physics.minetti_cw(0.0))
        self.assertAlmostEqual(p["out"], 0.1 * ratio)
        self.assertAlmostEqual(p["back"], 0.1 * float(physics.minetti_cw(-0.1) / physics.minetti_cw(0.0)))
        # the reversed path is the same walk: its way out is this path's way back
        r = physics.path_resources(z[::-1], np.full(5, 20.0), 0.001, walker=True)
        self.assertAlmostEqual(r["out"], p["back"])
        self.assertAlmostEqual(r["back"], p["out"])
        # out and back together match round_trip_walk's slope factor
        self.assertAlmostEqual(p["slope_factor"], (ratio + float(physics.minetti_cw(-0.1)) / 2.5) / 2)

    def test_planner_slope_slowdown_is_taken_back_out(self):
        slope = np.full(5, 10.0)
        p = physics.path_resources(np.zeros(6), np.full(5, 20.0), 0.001, walker=True, slope_deg=slope)
        self.assertAlmostEqual(p["out"], 0.1 * float(physics.walker_slope_slowdown(10.0)))

    def test_vehicle_climb_is_m_g_h_per_leg(self):
        z = np.array([0.0, 50.0, 100.0, 80.0])              # up 100 m, down 20 m
        p = physics.path_resources(z, np.full(3, 100.0), 0.1, mass_kg=1000.0)
        self.assertAlmostEqual(p["climb_wh_out"], 1000 * physics.MARS_G * 100 / 3600)
        self.assertAlmostEqual(p["climb_wh_back"], 1000 * physics.MARS_G * 20 / 3600)
        self.assertAlmostEqual(p["climb_wh_out"], 1000 * physics.climb_energy_kwh(1000.0, 100.0))
        self.assertAlmostEqual(p["out"], p["back"])           # driving energy itself is the same both ways
        self.assertAlmostEqual(p["climb_out_wh"].sum(), p["climb_wh_out"])

    def test_missing_elevation_and_empty_path(self):
        p = physics.path_resources(np.array([0.0, np.nan, 0.0]), np.full(2, 10.0), 1.0)
        self.assertTrue(np.isfinite(p["out"]))
        e = physics.path_resources(np.zeros(1), np.zeros(0), 1.0, walker=True)
        self.assertEqual(e["out"], 0.0)
        self.assertEqual(e["slope_factor"], 1.0)


class MissionPlanResources(unittest.TestCase):
    OLD_ITEM = {"name", "unit", "capacity", "used", "left_pct", "ok", "source"}
    OLD_RES = {"reserve_pct", "binding", "ok", "items", "turnaround"}

    @classmethod
    def setUpClass(cls):
        import app
        import mission
        import search
        cls.mission = mission
        cls.cube = app.get_cube("jezero")
        cls.spec = (search.keyword_parse("clay"), "keywords", [])

    def plan(self, vehicle, season="northern_summer"):
        return self.mission.plan(self.cube, "clay", vehicle, season, "safety", goal_spec=self.spec)

    def check(self, res):
        self.assertTrue(res["candidates"])
        for c in res["candidates"]:
            R = c["resources"]
            self.assertTrue(self.OLD_RES <= set(R))
            self.assertTrue({"h", "lat", "lon", "at_B"} <= set(R["turnaround"]))
            self.assertEqual(R["model"], "minetti")
            self.assertTrue(R["model_source"])
            self.assertIn("elevation_gain_m", R)
            for it in R["items"]:
                self.assertTrue(self.OLD_ITEM <= set(it))
                self.assertAlmostEqual(it["used"], it["out"] + it["back"] + it["site"], delta=0.02)

    def test_on_foot(self):
        res = self.plan("on_foot")
        self.check(res)
        o2 = res["candidates"][0]["resources"]["items"][0]
        self.assertEqual(o2["name"], "oxygen")
        for k in ("slope_factor", "slope_factor_out", "slope_factor_back", "load_factor"):
            self.assertIn(k, o2)

    def test_rover_climbs_and_recharge(self):
        res = self.plan("buggy")
        self.check(res)
        bat = res["candidates"][0]["resources"]["items"][0]
        self.assertEqual(bat["name"], "battery")
        self.assertGreaterEqual(bat["climb_wh"], 0)
        self.assertEqual(bat["power_source"], "battery")
        self.assertIsNotNone(bat["recharge_h"])
        bike = self.plan("two_wheel")["candidates"][0]["resources"]["items"]
        self.assertEqual([i["name"] for i in bike], ["oxygen", "battery"])
        self.assertIsNone(bike[1]["recharge_h"])               # no known power source for the scout bike

    def test_dust_season_reserve_is_at_least_20_pct(self):
        for p in ("safety", "speed", "energy"):
            self.assertGreaterEqual(self.mission._reserve(p, "northern_autumn"), 0.20)
            self.assertGreaterEqual(self.mission._reserve(p, "northern_summer"), 0.15)
        res = self.plan("on_foot", "northern_autumn")
        self.assertGreaterEqual(res["candidates"][0]["resources"]["reserve_pct"], 20)


if __name__ == "__main__":
    unittest.main()
