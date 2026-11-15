"""
The main app (`uvicorn app:app`) serves the gear routes as well as the planner and the front end.
Run:  python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402
import gear_server  # noqa: E402


class MainAppServesGear(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)

    def test_tools(self):
        r = self.client.get("/api/gear/tools", params={"format": "anthropic"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["tools"]), 8)

    def test_kit(self):
        r = self.client.post("/api/gear/kit", json={"context": {"archetype": "short_stay"}})
        self.assertEqual(r.status_code, 200)
        self.assertIn("groups", r.json())

    def test_kit_page_and_planner_still_served(self):
        self.assertEqual(self.client.get("/kit.html").status_code, 200)
        self.assertEqual(self.client.get("/api/regions").status_code, 200)

    def test_gear_server_still_works(self):
        r = TestClient(gear_server.server).get("/api/gear/catalog")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
