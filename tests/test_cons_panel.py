"""
The main page's Consumables panel reads these /api/plan stats keys; a rename on either side breaks this test.
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

# Every stats key renderConsumables / barRow / whyLines read in frontend/index.html
PANEL_KEYS = ["o2_used_kg", "o2_max_kg", "o2_pct", "o2_usable_kg",
              "energy_used_kwh", "energy_max_kwh", "energy_pct", "energy_usable_kwh",
              "reserve_pct", "terrain_o2_factor", "slope_o2_factor",
              "elevation_gain_m", "elevation_loss_m", "climb_kwh", "power_source",
              "dust_opacity", "sunlight_pct", "recharge_sols", "recharge_h",
              "within_budget", "max_range_km", "limiting_factor"]


class ConsumablesPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client = TestClient(app.app)

        def plan(vehicle, ls):
            r = client.post("/api/plan", json={"region": "jezero", "vehicle": vehicle, "ls": ls,
                                               "base": BASE, "target": TARGET})
            assert r.status_code == 200, r.text
            return r.json()["stats"]

        cls.walk = plan("astronaut", 90)
        cls.rover = plan("pressurized_rover", 250)
        cls.html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    def test_stats_keys_present(self):
        for stats in (self.walk, self.rover):
            self.assertIsNotNone(stats)
            for key in PANEL_KEYS:
                self.assertIn(key, stats)

    def test_astronaut_values(self):
        s = self.walk
        self.assertEqual(s["reserve_pct"], 15)
        self.assertAlmostEqual(s["o2_usable_kg"], s["o2_max_kg"] * 0.85, delta=0.01)
        for key in ("terrain_o2_factor", "slope_o2_factor", "elevation_gain_m", "elevation_loss_m"):
            self.assertIsNotNone(s[key], key)
        self.assertEqual(s["power_source"], "suit")
        self.assertIsNone(s["energy_used_kwh"])

    def test_rover_values(self):
        s = self.rover
        self.assertEqual(s["reserve_pct"], 20)               # dust-storm season
        for key in ("energy_usable_kwh", "climb_kwh", "dust_opacity", "sunlight_pct", "recharge_h"):
            self.assertIsNotNone(s[key], key)
        self.assertEqual(s["power_source"], "battery")
        self.assertIsNone(s["o2_used_kg"])

    def test_page_reads_every_key(self):
        for key in PANEL_KEYS:
            self.assertIn(f"s.{key}", self.html, key)
        self.assertIn("function whyLines(s)", self.html)
        self.assertIn('class="tick"', self.html)


if __name__ == "__main__":
    unittest.main()
