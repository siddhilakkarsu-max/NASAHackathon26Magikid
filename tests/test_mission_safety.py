"""Mission planner safety: landing standoff from B, time of day, storm shelter and walk-back checks."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mission  # noqa: E402
from app import get_cube  # noqa: E402
from config import LANDING_RULES  # noqa: E402

GOAL = "sample clay where water once flowed"


class MissionSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cube = get_cube("jezero")
        cls.walk = mission.plan(cls.cube, GOAL, "on_foot")
        cls.ride = mission.plan(cls.cube, GOAL, "four_wheel")

    def test_landing_spot_is_never_on_the_target(self):
        for res in (self.walk, self.ride):
            for c in res["candidates"]:
                self.assertGreaterEqual(c["A"]["dist_km"] * 1000, LANDING_RULES["min_standoff_m"] - 1)
                self.assertGreater(c["route"]["distance_km"], 0)

    def test_every_route_has_a_shelter_check(self):
        for c in self.walk["candidates"]:
            self.assertIn("shelter_min", c["safety"])
            self.assertTrue(c["card"]["safety"])

    def test_walk_back_only_for_vehicles(self):
        self.assertTrue(all("walkback_ok" not in c["safety"] for c in self.walk["candidates"]))
        self.assertTrue(all("walkback_ok" in c["safety"] for c in self.ride["candidates"]))

    def test_time_of_day_is_used(self):
        early = mission.plan(self.cube, GOAL, "on_foot", local_hour=6.25)
        self.assertEqual(early["settings"]["local_hour"], 6.25)
        self.assertLess(early["settings"]["sun_elevation"], self.walk["settings"]["sun_elevation"])
        self.assertTrue(any("sun is only" in n for n in early["notes"]))


if __name__ == "__main__":
    unittest.main()
