"""
Each mission-planner candidate card links to the gear page ("Gear for this mission"). The link maps the
mission vehicle (config.MISSION_VEHICLES) to a gear-page traveller (config.VEHICLES) with the
MISSION_GEAR_VEHICLE table in frontend/index.html, and reads Ls and the local hour from the mission response.

    python -m unittest tests.test_mission_gear_link
"""
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gear_state  # noqa: E402,F401  (before gear: keeps the real state file untouched)
from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402
from config import MISSION_VEHICLES, SEASONS, VEHICLES  # noqa: E402

HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
OMITTED = set()   # mission vehicles deliberately left out (the gear page then uses its default traveller)


def _mapping():
    m = re.search(r"const MISSION_GEAR_VEHICLE\s*=\s*\{(.*?)\};", HTML, re.S)
    assert m, "MISSION_GEAR_VEHICLE not found in index.html"
    return dict(re.findall(r'(\w+)\s*:\s*"(\w+)"', m.group(1)))


def _href(mission, cand, region):
    """What missionGearHref(c) in index.html builds for a candidate."""
    s = mission["settings"]
    q = {"archetype": "traverse", "region": region}
    v = _mapping().get(s["vehicle"]["key"])
    if v:
        q["vehicle"] = v
    q.update(base=f"{cand['A']['lat']},{cand['A']['lon']}", target=f"{cand['B']['lat']},{cand['B']['lon']}",
             ls=s["season"]["ls"], hour=s["local_hour"])
    return "kit.html?" + urlencode(q)


def _kit_context(href):
    """The context kit.js readForm() sends after prefillFromURL() read these params (default budget 8 h)."""
    q = {k: v[0] for k, v in parse_qs(href.split("?", 1)[1]).items()}
    pt = lambda s: dict(zip(("lat", "lon"), (round(float(x), 4) for x in s.split(","))))  # noqa: E731
    vehicle = q.get("vehicle", "astronaut")
    return {"archetype": q["archetype"], "vehicle": vehicle, "region": q["region"],
            "route_request": {"region": q["region"], "vehicle": vehicle, "local_hour": float(q["hour"]),
                              "budget_hours": 8, "ls": float(q["ls"]), "base": pt(q["base"]), "target": pt(q["target"])}}


class MissionGearLinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)

    def test_link_on_card(self):
        self.assertIn("Gear for this mission", HTML)
        self.assertIn("missionGearHref(c)", HTML)

    def test_every_mission_vehicle_mapped_or_omitted(self):
        mapping = _mapping()
        self.assertEqual(set(mapping) | OMITTED, set(MISSION_VEHICLES))
        self.assertFalse(set(mapping) & OMITTED)
        for k, v in mapping.items():
            self.assertIn(v, VEHICLES, k)
        # suited mission vehicles map to suited travellers, the pressurized buggy to the pressurized rover
        for k, v in mapping.items():
            suited = VEHICLES[v].get("consumable_source") in ("suit_o2", "lrv_battery")
            self.assertEqual(suited, MISSION_VEHICLES[k]["suited"], k)

    def test_kit_page_served(self):
        self.assertEqual(self.client.get("/kit.html").status_code, 200)

    def test_mission_link_builds_a_routed_kit(self):
        for vehicle, season in (("on_foot", "northern_summer"), ("four_wheel", "northern_autumn")):
            r = self.client.post("/api/mission", json={"region": "jezero", "goal": "clay", "vehicle": vehicle,
                                                        "season": season})
            self.assertEqual(r.status_code, 200, r.text)
            m = r.json()
            self.assertEqual(m["settings"]["season"]["ls"], SEASONS[season]["ls"])
            self.assertEqual(m["settings"]["vehicle"]["key"], vehicle)
            self.assertTrue(m["candidates"], vehicle)
            href = _href(m, m["candidates"][0], "jezero")
            kit = self.client.post("/api/gear/kit", json={"context": _kit_context(href)})
            self.assertEqual(kit.status_code, 200, kit.text)
            ctx = kit.json()["context"]
            self.assertIsNotNone(ctx["route"], href)
            self.assertEqual(ctx["vehicle"], _mapping()[vehicle])


if __name__ == "__main__":
    unittest.main()
