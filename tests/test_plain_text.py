"""
Plain wording for everyone, technical detail behind " | " (shown in the page's advanced view), and the season slider.
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
import config  # noqa: E402
import search  # noqa: E402


class PlainNames(unittest.TestCase):
    def test_minerals_have_plain_and_scientific_names(self):
        self.assertEqual(config.MINERALS["clay"]["label"], "clay")
        self.assertIn("smectite", config.MINERALS["clay"]["science"])
        for m in config.MINERALS.values():
            self.assertNotIn("(", m["label"])

    def test_feature_labels_have_no_jargon(self):
        for f in search.FEATURES.values():
            for word in ("CRISM", "thermal inertia", "smectite", "/"):
                self.assertNotIn(word, f["label"])


class SeasonSlider(unittest.TestCase):
    def test_ls_maps_to_the_right_season(self):
        for ls, name, dusty in ((10, "spring", False), (120, "summer", False), (200, "autumn", True),
                                (300, "winter", True), (359.9, "winter", True)):
            s = config.SEASONS[config.season_for_ls(ls)]
            self.assertIn(name, s["label"].lower())
            self.assertEqual(s["ls"], round(ls % 360, 1))
            self.assertEqual(s["dust_risk"] >= 0.3, dusty)

    def test_options_list_only_the_four_seasons(self):
        r = TestClient(app.app).get("/api/mission/options").json()
        self.assertEqual(list(r["seasons"]), config.BASE_SEASONS)

    def test_mission_accepts_the_slider(self):
        if not (ROOT / "cubes" / "jezero.npz").exists():
            self.skipTest("no Jezero cube")
        r = TestClient(app.app).post("/api/mission", json={"region": "jezero", "goal": "flat firm ground",
                                                           "vehicle": "on_foot", "ls": 250})
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertIn("Ls 250", r.json()["settings"]["season"]["label"])


if __name__ == "__main__":
    unittest.main()
