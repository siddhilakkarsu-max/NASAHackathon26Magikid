"""
Planning outside Jezero: named sites, site_<lat>_<lon> regions and the build endpoints (no real builds run here).
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


class BuildProgress(unittest.TestCase):
    """The loading bar's numbers come from the builder's log lines."""
    LOG = ["Region 'site_1_2': 410 x 410 px, bounds (...)", "STAGE layers 5",
           "  [ok] elevation     from terrain (1.0s)", "  [ok] themis_night  from wms (1.2s)",
           "  [--] themis_day    skipped. Tried: wms"]

    def test_terrain_stage_counts_layers_and_leaves_room_for_the_save(self):
        p = app._build_progress(self.LOG, False, "terrain", 0, 0)
        self.assertEqual((p["layers_done"], p["layers_total"]), (3, 5))
        self.assertAlmostEqual(p["terrain_progress"], 3 / 6, places=3)
        self.assertEqual(p["minerals_progress"], 0.0)

    def test_mineral_stage_after_the_terrain_is_saved(self):
        log = self.LOG + ["  [ok] albedo        from download", "  [ok] thermal_inertia from download",
                          "Saved cubes/site_1_2.npz", "STAGE terrain ready; reading CRISM minerals next",
                          "  CRISM: 3 products over the region", "    [ok] a.lbl", "  [ok] crism  clay"]
        p = app._build_progress(log, True, "minerals", 1, 3)
        self.assertEqual((p["layers_done"], p["terrain_progress"]), (5, 1.0))   # the crism line isn't a layer
        self.assertAlmostEqual(p["minerals_progress"], 1 / 4, places=3)
        self.assertEqual(app._build_progress(log, True, "done", 3, 3)["minerals_progress"], 1.0)

    def test_old_log_without_layer_count(self):
        self.assertEqual(app._build_progress(self.LOG[2:], False, "terrain", 0, 0)["terrain_progress"], 0.0)


class SiteRegions(unittest.TestCase):
    def test_quadrangles(self):
        # Jezero is in MC-13 Syrtis Major, Gale and Gusev in MC-23 Aeolis, Meridiani in MC-19 Margaritifer Sinus
        self.assertEqual(config.mc_quadrangle(18.4, 77.4), 13)
        self.assertEqual(config.mc_quadrangle(-4.6, 137.4), 23)
        self.assertEqual(config.mc_quadrangle(-14.6, 175.5), 23)
        self.assertEqual(config.mc_quadrangle(-1.9, -5.5), 19)
        self.assertEqual(config.mc_quadrangle(40, -160), 2)
        self.assertEqual(config.mc_quadrangle(80, 0), 1)
        self.assertEqual(config.mc_quadrangle(-70, 0), 30)

    def test_site_id_round_trip(self):
        name = config.site_id(-4.5895, 137.4417)
        self.assertEqual(name, "site_-4.59_137.44")
        b = config.region_box(name)
        self.assertAlmostEqual((b["west"] + b["east"]) / 2, 137.44)
        self.assertAlmostEqual((b["south"] + b["north"]) / 2, -4.59)
        self.assertAlmostEqual(b["east"] - b["west"], config.SITE_SIZE_DEG)

    def test_longitudes_wrap(self):
        self.assertEqual(config.site_id(10, 200), "site_10_-160")

    def test_named_sites_and_unknown(self):
        self.assertIsNotNone(config.region_box("gale"))
        self.assertIsNotNone(config.region_box("jezero"))
        self.assertIsNone(config.region_box("atlantis"))
        self.assertIsNone(config.region_box("site_95_0"))

    def test_landing_sites_count_as_nasa_candidates(self):
        self.assertEqual(config.NASA_SITES["gale"][0]["kind"], "past landing site")

    def test_builder_uses_the_3d_terrain_outside_jezero(self):
        import build_cube
        self.assertEqual(build_cube.sources_for("site_-40_-100")["elevation"][0]["kind"], "terrain")
        self.assertNotEqual(build_cube.sources_for("jezero")["elevation"][0]["kind"], "terrain")

    def test_builder_picks_the_quadrangle_ti_tile(self):
        import build_cube
        self.assertIn("MC23", build_cube.sources_for("gale")["thermal_inertia"][0]["path"])
        self.assertIn("MC13", build_cube.sources_for("site_20_70")["thermal_inertia"][0]["path"])
        # Jezero keeps its calibrated map first
        self.assertIn("Jezero", build_cube.sources_for("jezero")["thermal_inertia"][0]["path"])


class SiteEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)

    def test_site_list(self):
        r = self.client.get("/api/sites").json()
        self.assertIn("gale", [s["site"] for s in r["sites"]])

    def test_build_needs_a_place(self):
        self.assertEqual(self.client.post("/api/sites/build", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/sites/build", json={"site": "atlantis"}).status_code, 400)
        self.assertEqual(self.client.post("/api/sites/build", json={"lat": 95, "lon": 0}).status_code, 422)

    def test_status_of_unbuilt_site(self):
        r = self.client.get("/api/sites/build/site_1_2").json()
        if not r["ready"]:
            self.assertEqual(r["status"], "not built")
        self.assertEqual(self.client.get("/api/sites/build/atlantis").status_code, 404)

    def test_jezero_cube_is_reused_inside_jezero(self):
        if (ROOT / "cubes" / "jezero.npz").exists():
            self.assertEqual(app.covering_cube(18.4, 77.5)["region"], "jezero")
        self.assertIsNone(app.covering_cube(-40.0, -100.0) if not any(
            m["region"].startswith("site_-40") for m in app.cube_metas()) else None)

    def test_regions_have_labels(self):
        for r in self.client.get("/api/regions").json()["regions"]:
            self.assertTrue(r["label"])


if __name__ == "__main__":
    unittest.main()
