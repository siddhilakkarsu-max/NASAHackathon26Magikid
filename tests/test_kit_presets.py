"""
The gear page's one-click scenarios (frontend/kit-presets.js): the page loads them, the files are
served, all seven scenarios exist and every traveller they name is a planner vehicle.

    python -m unittest tests.test_kit_presets
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import gear_server  # noqa: E402
from config import VEHICLES  # noqa: E402

PRESET_IDS = {"delta-walk", "delta-dust", "crew-rover", "opportunity", "spirit", "cave", "long-base"}


class KitPresetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(gear_server.server)
        cls.js = (ROOT / "frontend" / "kit-presets.js").read_text(encoding="utf-8")

    def test_page_loads_presets(self):
        r = self.client.get("/kit.html")
        self.assertEqual(r.status_code, 200)
        self.assertIn('src="kit-presets.js"', r.text)
        self.assertIn('href="kit-presets.css"', r.text)

    def test_files_served(self):
        for path in ("/kit-presets.js", "/kit-presets.css"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_all_presets_defined(self):
        ids = set(re.findall(r'\bid:\s*"([a-z-]+)"', self.js))
        self.assertTrue(PRESET_IDS <= ids, PRESET_IDS - ids)

    def test_vehicles_exist(self):
        keys = set(re.findall(r'route\(\s*"([a-z_]+)"', self.js))
        self.assertTrue(keys, "no vehicles found in kit-presets.js")
        self.assertTrue(keys <= set(VEHICLES), keys - set(VEHICLES))

    def test_season_sent_with_route(self):
        js = (ROOT / "frontend" / "kit.js").read_text(encoding="utf-8")
        self.assertIn('ls: +$("#ls").value', js)
        self.assertIn('id="ls"', self.client.get("/kit.html").text)


if __name__ == "__main__":
    unittest.main()
