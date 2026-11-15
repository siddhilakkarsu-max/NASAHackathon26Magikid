"""
The survival game (frontend/game.html) and its Play launcher (frontend/game-launch.js): both are served,
the game is one self-contained file, its baked missions are real planner output, and the planner still
returns every field the game reads.

    python -m unittest tests.test_game
"""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import gear_server  # noqa: E402
from config import MISSION_VEHICLES, PRIORITIES, SEASONS, VEHICLES  # noqa: E402

HANDOFF_KEY = "marswalk.game.mission"
DEATHS = ("oxygen", "battery", "integrity", "tools", "offlimits", "storm")


class GameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(gear_server.server)
        cls.html = (ROOT / "frontend" / "game.html").read_text(encoding="utf-8")
        cls.launch = (ROOT / "frontend" / "game-launch.js").read_text(encoding="utf-8")
        cls.script = re.search(r"<script>([\s\S]*)</script>", cls.html).group(1)
        start = cls.html.index("const BAKED = [") + len("const BAKED = [")
        end = cls.html.index("\n];", start)
        cls.baked = json.loads("[" + cls.html[start:end] + "]")

    def test_served(self):
        for path in ("/game.html", "/game-launch.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_single_self_contained_file(self):
        self.assertIsNone(re.search(r"<script[^>]+src=", self.html))
        self.assertIsNone(re.search(r"<link[^>]+rel=[\"']?stylesheet", self.html))
        self.assertEqual(len(re.findall(r"<script>", self.html)), 1)
        # the only network calls are this app's own API
        for url in re.findall(r"fetch\(\s*['\"]([^'\"]+)", self.script):
            self.assertTrue(url.startswith("/api/"), url)

    def test_script_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        r = subprocess.run([node, "--check"], input=self.script, capture_output=True,
                           text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr[:500])

    def test_launcher_behavior(self):
        """The selected plan survives edited controls, dynamic regions, and storage failure."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        r = subprocess.run([node, str(ROOT / "docs" / "game" / "launcher_test.js")],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_baked_missions_are_playable_plans(self):
        self.assertGreaterEqual(len(self.baked), 3)
        self.assertGreaterEqual(len({m["settings"]["vehicle"]["key"] for m in self.baked}), 3)
        for m in self.baked:
            self.assertIn(m["settings"]["vehicle"]["key"], MISSION_VEHICLES)
            self.assertTrue(m["tools"]["items"])
            self.assertTrue(m["candidates"])
            for c in m["candidates"]:
                self.assertGreaterEqual(len(c["route"]["points"]), 2)
                self.assertTrue(c["resources"]["items"])
                self.assertIn("h", c["resources"]["turnaround"])

    def test_vehicle_table_matches_planner(self):
        """The game's VEH table must carry the planner's current numbers (config.MISSION_VEHICLES)."""
        for key, v in MISSION_VEHICLES.items():
            row = re.search(r"\n\s*%s:\s*\{([^}]*)\}" % key, self.script)
            self.assertIsNotNone(row, key)
            got = dict(re.findall(r"(\w+):\s*(-?[\d.]+)", row.group(1)))
            want = dict(max_slope=v["max_slope"], range_km=v["range_km"], base=v["base_speed_kmh"],
                        sand=v["sand_penalty"], rough=v["rough_penalty"], mass=v["mass_kg"],
                        bat=v.get("battery_wh") or 0, whkm=v.get("wh_per_km") or 0, hotel=v.get("hotel_w") or 0)
            for k, w in want.items():
                self.assertAlmostEqual(float(got[k]), float(w), msg=f"{key}.{k}")

    def test_planner_keys_and_deaths_present(self):
        for key in list(MISSION_VEHICLES) + list(SEASONS) + list(PRIORITIES):
            self.assertIn(key, self.script, key)
        for cause in DEATHS:
            self.assertRegex(self.script, r"\b%s: \['" % cause)

    def test_planner_elements_present(self):
        for word in ("Decision matrix", "TURN BACK", "reserve", "walk-back", "rover tracks", "off-limits",
                     "science", "dust", "WIND", "Pa", "kit.html", "index.html", "HOUSTON"):
            self.assertIn(word.lower(), self.html.lower(), word)

    def test_first_person_3d_with_2d_fallback(self):
        """The 3D view is raw WebGL inside the same file, and the 2D renderer stays as the fallback."""
        for word in ("function render3d(", "function g3Init(", "getContext('webgl'", "function h3(",
                     "Q.get('view') === '2d'", "if (G3.on) { render3d(dt); return; }", "requestPointerLock"):
            self.assertIn(word, self.script, word)
        self.assertIn('<canvas id="gl"', self.html)
        self.assertIn('<canvas id="cv"', self.html)
        self.assertNotIn("THREE.", self.script)

    def test_dialogue_is_light_by_default(self):
        """Blocking Houston scenes are cut down unless ?story=1 asks for the full scripts."""
        self.assertIn("get('story') === '1'", self.script)
        self.assertIn("SCENE_RADIO = { storm: 1, arrival: 1, objective: 1, abandon: 1 }", self.script)
        self.assertIn("if (STORY && !G.skip && !prefs.intro)", self.script)

    def test_vehicle_driving_and_dismount(self):
        """Vehicles steer and carry momentum, the crew can step off and mount again, and B always has a sample."""
        for word in ("function dismount(", "function mount(", "function g3Parked(", "function g3Driving(",
                     "DRIVE_ACCEL", "MOUNT_M", "k === snapK", "if (kl === 'v')"):
            self.assertIn(word, self.script, word)

    def test_leaderboard_client_and_ready_button(self):
        """The game posts to the leaderboard API, and the planner gets a "mission ready" launch button."""
        for word in ("/api/game/players", "/api/game/scores", "/api/game/leaderboard", "marswalk.game.player",
                     "function lbSubmit(", "R.bot || R.fast"):
            self.assertIn(word, self.script, word)
        self.assertIn('id="lb"', self.html)
        for word in ('"playFab"', "playFabPulse", "MISSION READY"):
            self.assertIn(word, self.launch, word)

    def test_one_model_per_vehicle(self):
        """Riding and parked use the same full vehicle model, built once per vehicle (no view-only half models)."""
        for word in ("function g3VehModel(", "G3.vmod[key] = MB.a.slice(0, MB.n)", "const src = G3.vmod[W.veh.key]",
                     "SEAT: { two_wheel:", "look(yawDeg, pitchDeg)"):
            self.assertIn(word, self.script, word)
        for old in ("mk('four_wheel'", "mk('two_wheel'", "mk('buggy'"):
            self.assertNotIn(old, self.script, old)

    def test_handoff_contract(self):
        self.assertIn(HANDOFF_KEY, self.html)
        self.assertIn(HANDOFF_KEY, self.launch)
        self.assertIn("game.html?src=planner", self.launch)
        self.assertIn("src=planner", self.html.replace("'planner'", "=planner"))

    def test_kit_page_loads_launcher(self):
        self.assertRegex(self.client.get("/kit.html").text,
                         r'<script src="game-launch\.js(?:\?v=[a-f0-9]{16})?" defer></script>')
        for key in ("astronaut", "unpressurized_rover", "pressurized_rover"):
            self.assertIn(key, VEHICLES)
            self.assertIn(key, self.launch)
        for key in ("on_foot", "four_wheel", "buggy"):
            self.assertIn(key, self.launch)

    def test_planner_still_returns_what_the_game_reads(self):
        s = self.baked[0]["settings"]
        r = self.client.post("/api/mission", json=dict(
            region="jezero", goal=s["goal"], vehicle=s["vehicle"]["key"], season=s["season"]["key"],
            priority=s["priority"]["key"], green_only=False))
        self.assertEqual(r.status_code, 200, r.text[:300])
        m = r.json()
        for k in ("settings", "tools", "candidates", "dropped", "notes", "rect", "explanation", "id"):
            self.assertIn(k, m)
        for k in ("goal", "targets", "vehicle", "season", "priority", "weights", "criteria", "local_hour"):
            self.assertIn(k, m["settings"])
        self.assertTrue(m["candidates"])
        c = m["candidates"][0]
        for k in ("A", "B", "route", "resources", "card", "scores", "total", "rank"):
            self.assertIn(k, c)
        self.assertEqual(set(c["route"]["points"][0]) >= {"lat", "lon", "risk", "green"}, True)
        for k in ("distance_km", "one_way_h", "round_trip_h", "max_slope"):
            self.assertIn(k, c["route"])
        for k in ("reserve_pct", "binding", "items", "turnaround"):
            self.assertIn(k, c["resources"])
        for k in ("name", "unit", "capacity", "used", "left_pct"):
            self.assertIn(k, c["resources"]["items"][0])
        for k in ("name", "kg", "w", "why"):
            self.assertIn(k, m["tools"]["items"][0])


if __name__ == "__main__":
    unittest.main()
