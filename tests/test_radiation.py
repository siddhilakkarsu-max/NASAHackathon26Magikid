"""Radiation data integrity, physical units, missingness, and API integration."""
import base64
import hashlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gear_state  # noqa: E402,F401
from fastapi.testclient import TestClient  # noqa: E402
import app  # noqa: E402
import mars_radiation as rad  # noqa: E402
from mars_weather import weather_layer  # noqa: E402


class RadiationModel(unittest.TestCase):
    def test_published_surface_row_and_all_pressure_knots(self):
        ref = rad.reference_data()
        source = rad.DATA_DIR / "PAPER1" / "figure11_eff_depth.txt"
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), ref["source_sha256"])
        original = np.loadtxt(source)
        surface = original[original[:, 0] == 0]
        self.assertEqual(surface.shape, (1, 19))
        self.assertEqual(ref["pressure_pa"], [82, 305, 529, 753, 975, 1200])
        for solar, start in [(400, 1), (700, 7), (1000, 13)]:
            annual = np.array(ref["scenarios"][str(solar)]["effective_dose_msv_per_year"])
            np.testing.assert_array_equal(annual, surface[0, start:start + 6])
            np.testing.assert_allclose(rad.dose_from_pressure(ref["pressure_pa"], solar),
                                       surface[0, start:start + 6] * 1000 / 8766, rtol=1e-12)

    def test_units_are_earth_hours_not_sols(self):
        ref = rad.reference_data()
        self.assertEqual(ref["year_hours"], 365.25 * 24)
        # A reference 8766 mSv/year is exactly 1000 µSv per Earth hour.
        fake = {"pressure_pa": [82, 1200], "year_hours": 8766,
                "scenarios": {"700": {"effective_dose_msv_per_year": [8766, 8766]}}}
        with patch.object(rad, "reference_data", return_value=fake):
            self.assertEqual(float(rad.dose_from_pressure(600)), 1000)

    def test_interpolation_and_no_extrapolation(self):
        for solar in (400, 700, 1000):
            knots = np.array(rad.reference_data()["pressure_pa"])
            ends = rad.dose_from_pressure(knots, solar)
            mid = rad.dose_from_pressure((knots[:-1] + knots[1:]) / 2, solar)
            np.testing.assert_allclose(mid, (ends[:-1] + ends[1:]) / 2)
            self.assertTrue(np.isnan(rad.dose_from_pressure([81.99, 1200.01, np.nan, np.inf], solar)).all())
        with self.assertRaises(ValueError):
            rad.dose_from_pressure(800, 580)

    def test_solar_scenarios_are_distinct_and_bounded(self):
        p = np.linspace(82, 1200, 100)
        minimum, middle, maximum = [rad.dose_from_pressure(p, s) for s in (400, 700, 1000)]
        self.assertTrue((minimum > middle).all())
        self.assertTrue((middle > maximum).all())
        self.assertTrue((maximum >= rad.SCALE[0]).all())
        self.assertTrue((minimum <= rad.SCALE[1]).all())

    def test_real_weather_season_time_and_missing_domain(self):
        base, p = rad.radiation_fields(11, 90)
        self.assertEqual(base.shape, (36, 72))
        np.testing.assert_allclose(p, weather_layer("surface_pressure", 11, 90))
        np.testing.assert_allclose(base, rad.dose_from_pressure(p), equal_nan=True)
        for alternate in (rad.radiation_fields(1, 90)[0], rad.radiation_fields(11, 270)[0]):
            self.assertGreater(float(np.nanmax(np.abs(base - alternate))), 0)
        np.testing.assert_allclose(rad.radiation_fields(0, 0)[0], rad.radiation_fields(24, 360)[0], equal_nan=True)
        self.assertTrue(np.array_equal(np.isfinite(base), np.isfinite(p) & (p >= 82) & (p <= 1200)))

    def test_dust_is_context_only_and_missing_pressure_stays_missing(self):
        def weather(name, hour, ls):
            return np.full((36, 72), 800 if name == "surface_pressure" else 0.1)
        with patch.object(rad, "weather_layer", side_effect=weather):
            clean = rad.sample_radiation(0, 0, 11, 90)
        def dusty(name, hour, ls):
            return np.full((36, 72), 800 if name == "surface_pressure" else 5)
        with patch.object(rad, "weather_layer", side_effect=dusty):
            storm = rad.sample_radiation(0, 0, 11, 90)
        self.assertEqual(clean["value"], storm["value"])
        self.assertNotEqual(clean["dust_opacity"], storm["dust_opacity"])
        for p in (np.nan, 1500):
            with patch.object(rad, "weather_layer", return_value=np.full((36, 72), p)):
                sample = rad.sample_radiation(0, 0, 11, 90)
            self.assertIsNone(sample["value"])
            self.assertTrue(sample["reason"])


class RadiationAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)

    def test_global_layer_does_not_require_regional_cube(self):
        results = []
        for solar in (400, 700, 1000):
            response = self.client.post("/api/layer/radiation_dose", json={"region": "no-cube", "radiation_solar_mv": solar, "radiation_spatial_contrast": False})
            self.assertEqual(response.status_code, 200, response.text[:200])
            result = response.json()
            self.assertEqual(result["legend"]["unit"], "µSv/h")
            self.assertEqual(result["rect"], {"west": -180, "east": 180, "north": 90, "south": -90})
            self.assertEqual(result["radiation"]["solar_modulation_mv"], solar)
            self.assertEqual(result["legend"]["colors"][0], "#762a83")
            self.assertEqual(result["legend"]["colors"][-1], "#1b7837")
            png = Image.open(io.BytesIO(base64.b64decode(result["image"].split(",", 1)[1])))
            self.assertEqual(png.size, (288, 144))
            field = rad.radiation_fields(11, 90, solar)[0]
            expected = np.isfinite(field).repeat(4, axis=0).repeat(4, axis=1)
            np.testing.assert_array_equal(np.asarray(png)[..., 3] > 0, expected)
            results.append(result)
        self.assertEqual(results[0]["legend"], results[-1]["legend"])
        self.assertNotEqual(results[0]["image"], results[-1]["image"])

    def test_spatial_contrast_changes_colors_not_doses_and_is_fixed_over_time(self):
        shared = self.client.post("/api/layer/radiation_dose", json={"radiation_spatial_contrast": False}).json()
        spatial = self.client.post("/api/layer/radiation_dose", json={}).json()
        later = self.client.post("/api/layer/radiation_dose", json={"ls": 270, "local_hour": 5}).json()
        self.assertEqual(shared["data_range"], spatial["data_range"])
        self.assertEqual(spatial["legend"], later["legend"])
        self.assertEqual(spatial["radiation"]["color_scale_mode"], "spatial")
        self.assertLess(spatial["legend"]["max"] - spatial["legend"]["min"], 2)
        self.assertNotEqual(shared["image"], spatial["image"])

    def test_sample_matches_native_cell_and_wraps_at_poles_seam(self):
        for solar in (400, 700, 1000):
            for lat, lon in [(90, -180), (-90, 180), (18.38, 77.58), (0, 0)]:
                res = self.client.post("/api/layer/radiation_dose/sample", json={"lat": lat, "lon": lon, "radiation_solar_mv": solar})
                self.assertEqual(res.status_code, 200)
                value = rad.radiation_fields(11, 90, solar)[0][app.global_cell(lat, lon, (36, 72))]
                self.assertEqual(res.json()["value"], round(float(value), 2) if np.isfinite(value) else None)
        left = self.client.post("/api/layer/radiation_dose/sample", json={"lat": 20, "lon": -180}).json()
        right = self.client.post("/api/layer/radiation_dose/sample", json={"lat": 20, "lon": 180}).json()
        self.assertEqual(left, right)

    def test_invalid_scenarios_and_positions(self):
        for body in [{"radiation_solar_mv": 580}, {"ls": 361}, {"local_hour": -1}]:
            self.assertEqual(self.client.post("/api/layer/radiation_dose", json=body).status_code, 422)
        self.assertEqual(self.client.post("/api/layer/radiation_dose/sample", json={"lat": 91, "lon": 0}).status_code, 422)

    def test_method_document_is_served(self):
        res = self.client.get("/api/radiation/method")
        self.assertEqual(res.status_code, 200)
        self.assertIn("2021JE007157", res.text)


if __name__ == "__main__":
    unittest.main()
