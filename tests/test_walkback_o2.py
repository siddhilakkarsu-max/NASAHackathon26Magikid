"""
Walk-back zone limited by the suit's oxygen (and a rover's battery) as well as the time budget.
Run:  python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gear_state  # noqa: E402,F401  (before gear: keeps the real state file untouched)
from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402

BASE = {"lat": 18.4447, "lon": 77.4508}
TARGET = {"lat": 18.50, "lon": 77.40}


class WalkbackOxygen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)

    def plan(self, **kw):
        body = {"region": "jezero", "vehicle": "astronaut", "base": BASE, "target": TARGET, **kw}
        r = self.client.post("/api/plan", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_oxygen_binds_a_full_eva(self):
        # No extra time reserve: 8 h of EVA time outlasts the suit's usable O2 (6.8 h flat at Ls 90)
        winter, storms = self.plan(ls=90, budget_hours=8, reserve=0.0), self.plan(ls=250, budget_hours=8, reserve=0.0)
        for res in (winter, storms):
            self.assertTrue(res["walkback_image"].startswith("data:image/png"))
            self.assertEqual(res["walkback_basis"], "oxygen")
            area = res["walkback_area_km2"]
            self.assertGreater(area["zone"], 0)
            self.assertLess(area["oxygen"], area["time"])
            self.assertLessEqual(area["zone"], area["oxygen"])
            self.assertIsNone(res["walkback_energy_usable_kwh"])
        self.assertEqual((winter["walkback_reserve_pct"], storms["walkback_reserve_pct"]), (15, 20))
        self.assertGreater(winter["walkback_o2_usable_kg"], storms["walkback_o2_usable_kg"])
        self.assertLessEqual(storms["walkback_area_km2"]["zone"], winter["walkback_area_km2"]["zone"])

    def test_short_budget_is_time_bound(self):
        res = self.plan(ls=90, budget_hours=1)
        self.assertEqual(res["walkback_basis"], "time")
        area = res["walkback_area_km2"]
        self.assertGreater(area["zone"], 0)
        self.assertEqual(area["zone"], area["time"])

    def test_zone_oxygen_matches_the_route(self):
        # The zone costs O2 along the same paths and with the same model as the planned route
        req = app.PlanRequest(base=BASE, target=TARGET, budget_hours=8, ls=90)
        c = app.get_cube("jezero")
        v, *_, cost = app.conditions_layers(c, req)
        start, goal = c.rc(BASE["lat"], BASE["lon"]), c.rc(TARGET["lat"], TARGET["lon"])
        _, amounts, usable, reserve = app._walkback_round_trip(c, v, "astronaut", cost, start, 90, 8 * 3600)
        res = self.plan(ls=90, budget_hours=8)
        self.assertAlmostEqual(float(amounts["oxygen"][goal]), res["stats"]["o2_used_kg"], places=2)
        self.assertAlmostEqual(usable["oxygen"], res["stats"]["o2_usable_kg"], places=2)
        self.assertEqual(reserve, 0.15)

    def test_rover_battery(self):
        res = self.plan(vehicle="pressurized_rover", ls=250, budget_hours=8, reserve=0.1)
        self.assertEqual(res["walkback_basis"], "energy")
        self.assertIsNotNone(res["walkback_energy_usable_kwh"])
        self.assertIsNone(res["walkback_o2_usable_kg"])
        self.assertLess(res["walkback_area_km2"]["energy"], res["walkback_area_km2"]["time"])


if __name__ == "__main__":
    unittest.main()
