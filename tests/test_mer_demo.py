"""
The two MER scenarios on the gear page (frontend/kit-presets.js "opportunity" and "spirit") read the
route straight from the preset file and check the plan is a believable one-sol MER drive: it fits
the rover's drive window, uses less than one sol of array energy, and dust season slows recharging.

    python -m unittest tests.test_mer_demo
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import VEHICLES  # noqa: E402
from gear import tools  # noqa: E402

JS = (ROOT / "frontend" / "kit-presets.js").read_text(encoding="utf-8")


def _point(name):
    m = re.search(rf"\b{name}\s*=\s*\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]", JS)
    assert m, f"{name} not found in kit-presets.js"
    return {"lat": float(m.group(1)), "lon": float(m.group(2))}


def _preset(pid):
    """The preset's route(...) call: vehicle, target constant, Ls."""
    m = re.search(rf'id:\s*"{pid}".*?route:\s*route\(\s*"(\w+)"\s*,\s*(\w+)\s*,\s*([\d.]+)', JS, re.S)
    assert m, f"preset {pid} has no route"
    return m.group(1), _point(m.group(2)), float(m.group(3))


def _plan(vehicle, target, ls):
    # same defaults the preset's route() helper sends: hour 11, budget 8 h
    r = tools.call_tool("get_route_context", {"region": "jezero", "vehicle": vehicle, "base": _point("LANDING"),
                                              "target": target, "local_hour": 11, "budget_hours": 8, "ls": ls})
    assert r.get("route"), r
    return r["route"]


class MerDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans = {}
        for pid in ("opportunity", "spirit"):
            vehicle, target, ls = _preset(pid)
            cls.plans[pid] = (vehicle, target, ls, _plan(vehicle, target, ls))

    def test_presets_use_mer(self):
        for pid, (vehicle, *_rest) in self.plans.items():
            self.assertEqual(vehicle, "mer", pid)

    def test_energy_under_one_sol(self):
        for pid, (*_x, rt) in self.plans.items():
            self.assertGreater(rt["energy_pct"], 0, pid)
            self.assertLess(rt["energy_pct"], 100, pid)

    def test_round_trip_fits_drive_window(self):
        window = VEHICLES["mer"]["rated_hours"]
        for pid, (*_x, rt) in self.plans.items():
            self.assertGreater(rt["round_trip_h"], 0, pid)
            self.assertLessEqual(rt["round_trip_h"], window, pid)

    def test_dust_season_slows_recharge(self):
        vehicle, target, ls, storm = self.plans["opportunity"]
        self.assertEqual(ls, 250)
        clear = _plan(vehicle, target, 90)
        self.assertIsNotNone(storm["recharge_sols"])
        self.assertIsNotNone(clear["recharge_sols"])
        self.assertGreater(storm["recharge_sols"], clear["recharge_sols"])
        self.assertLessEqual(clear["recharge_sols"], 1.0)


if __name__ == "__main__":
    unittest.main()
