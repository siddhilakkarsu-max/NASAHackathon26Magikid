"""Map service regressions: Windows text decoding and HiRISE spatial queries."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import murray


def footprint_index(rings):
    starts = [0]
    for ring in rings:
        starts.append(starts[-1] + len(ring))
    return {"boxes": np.array([[min(x for x, y in r), min(y for x, y in r),
                                max(x for x, y in r), max(y for x, y in r)] for r in rings]),
            "coords": np.concatenate(rings), "starts": np.array(starts),
            "ids": np.array([f"TEST_{i}" for i in range(len(rings))])}


class MurrayServices(unittest.TestCase):
    def test_public_catalog_caps_ctx_at_real_five_meter_cache(self):
        # The upstream generic metadata lists 17, but real tiles stop at 12.
        # This public catalogue drives both whole-globe and sharp-box imagery.
        layers = {layer["id"]: layer for layer in murray.murray_layers()["layers"]}
        ctx = layers["ctx"]
        self.assertEqual(ctx["max_level"], 12)
        self.assertIn("/CTX1/MapServer/tile/", ctx["url"])
        meters_per_pixel = 2 * math.pi * murray.MARS_R / (512 * 2 ** (ctx["max_level"] + 1))
        self.assertAlmostEqual(meters_per_pixel, 5.0875, delta=0.01)
        self.assertEqual(layers["terrain"]["max_level"], 7)

    def test_quad_source_east_edge_rounds_before_longitude_wrapping(self):
        source = {"features": [{"properties": {"Quad": "E176_N0", "Data": "https://example.org/tile"},
                               "geometry": {"coordinates": [[[176, 4], [180.0000000000001, 4],
                                                               [180.0000000000001, 0], [176, 0], [176, 4]]]}}]}
        with patch.object(murray, "_raw", return_value=source):
            tile = murray._quads()["features"][0]
        self.assertEqual(tile["geometry"]["coordinates"][0], [[176, 4], [180, 4], [180, 0], [176, 0], [176, 4]])
        self.assertEqual(tile["properties"]["name"], "E176_N0")

    def test_cached_quad_at_dateline_does_not_cover_opposite_hemisphere(self):
        # Older cached rings wrapped the floating-point east edge to -180.
        tile = {"type": "Feature", "properties": {"name": "E176_N0", "link": "https://example.org/tile"},
                "geometry": {"type": "Polygon", "coordinates": [[[176, 4], [-180, 4], [-180, 0], [176, 0], [176, 4]]]}}
        with tempfile.TemporaryDirectory() as temp, patch.object(murray, "CACHE", Path(temp)), patch.object(murray, "_quad_boxes", None):
            (Path(temp) / "quads.geojson").write_text(json.dumps({"features": [tile]}), encoding="utf-8")
            for lon in (178, 180, -180):
                self.assertEqual(murray.murray_quad_at(2, lon)["name"], "E176_N0")
            for lat, lon in ((2, 0), (2, -178), (89, 178), (-89, 178)):
                self.assertIsNone(murray.murray_quad_at(lat, lon)["name"])

    def test_quad_at_invalid_point_rejected_before_reading_cache(self):
        with patch.object(murray, "murray_features") as features:
            for lat, lon in ((91, 0), (0, 181), (float("nan"), 0), (0, float("inf"))):
                with self.assertRaises(HTTPException) as raised:
                    murray.murray_quad_at(lat, lon)
                self.assertEqual(raised.exception.status_code, 422)
            features.assert_not_called()

    def test_utf8_iau_names_load_on_windows_and_survive_caching(self):
        data = {"type": "FeatureCollection", "features": [{"type": "Feature",
                "properties": {"name": "Test \u010f crater", "origin": "J\u00fcrgen", "diameter": 3,
                               "type": "Crater, craters"},
                "geometry": {"type": "Point", "coordinates": [323, -27]}}]}
        with tempfile.TemporaryDirectory() as temp, patch.object(murray, "CACHE", Path(temp)):
            raw = Path(temp) / "raw" / "mars-nomenclature.geojson"
            raw.parent.mkdir()
            raw.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            response = murray.murray_features("names")
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.body)
            feature = result["features"][0]
            self.assertEqual(feature["properties"]["name"], "Test \u010f crater")
            self.assertEqual(feature["geometry"]["coordinates"], [-37, -27])
            self.assertEqual(json.loads(murray.murray_features("names").body), result)

    def test_hirise_view_crossing_dateline_includes_both_sides(self):
        rings = [[[179, 0], [179.5, 0], [179.5, 1], [179, 0]],
                 [[-179.5, 0], [-179, 0], [-179, 1], [-179.5, 0]],
                 [[0, 0], [1, 0], [1, 1], [0, 0]]]
        with patch.object(murray, "_hirise_index", return_value=footprint_index(rings)):
            response = murray.murray_hirise(178, -1, -178, 2)
            self.assertEqual(response["total"], 2)
            self.assertEqual({f["properties"]["name"] for f in response["features"]}, {"TEST_0", "TEST_1"})
            limited = murray.murray_hirise(178, -1, -178, 2, limit=1)
            self.assertTrue(limited["truncated"])
            self.assertEqual(len(limited["features"]), 1)

    def test_hirise_point_must_be_inside_footprint_not_just_box(self):
        diamond = [[0, 1], [1, 0], [2, 1], [1, 2], [0, 1]]
        with patch.object(murray, "_hirise_index", return_value=footprint_index([diamond])):
            self.assertEqual(murray.murray_hirise_at(0.1, 0.1)["total"], 0)
            self.assertEqual(murray.murray_hirise_at(1, 1)["total"], 1)
            self.assertEqual(murray.murray_hirise_at(1, 0)["total"], 1)

    def test_hirise_point_in_dateline_footprint_not_opposite_side(self):
        ring = [[179.5, 0], [-179.5, 0], [-179.5, 1], [179.5, 1], [179.5, 0]]
        with patch.object(murray, "_hirise_index", return_value=footprint_index([ring])):
            for lon in (179.75, -179.75, 180, -180):
                self.assertEqual(murray.murray_hirise_at(0.5, lon)["total"], 1)
            self.assertEqual(murray.murray_hirise_at(0.5, 0)["total"], 0)

    def test_dateline_footprint_view_does_not_claim_greenwich_coverage(self):
        ring = [[179.5, 0], [-179.5, 0], [-179.5, 1], [179.5, 1], [179.5, 0]]
        with patch.object(murray, "_hirise_index", return_value=footprint_index([ring])):
            self.assertEqual(murray.murray_hirise(-1, -1, 1, 2)["total"], 0)
            self.assertEqual(murray.murray_hirise(179.75, -1, -179.75, 2)["total"], 1)
            self.assertEqual(murray.murray_hirise(-180, -1, -179.75, 2)["total"], 1)
            self.assertEqual(murray.murray_hirise(179.75, -1, 180, 2)["total"], 1)

    def test_nonexistent_terrain_tiles_never_fetch_upstream(self):
        with patch.object(murray, "_fetch") as fetch:
            for z, y, x in ((8, 100, 364), (-1, 0, 0), (7, 128, 0), (7, 0, 256), (0, -1, 0), (0, 0, -1)):
                with self.assertRaises(HTTPException) as raised:
                    murray.murray_elevation_tile(z, y, x)
                self.assertEqual(raised.exception.status_code, 404)
            fetch.assert_not_called()

    def test_invalid_bounds_and_limits_rejected_before_loading_index(self):
        with patch.object(murray, "_hirise_index") as index:
            for change in ({"west": float("nan")}, {"north": 91}, {"limit": 0}, {"limit": -1}, {"limit": 1501}):
                params = {"west": -1, "south": -1, "east": 1, "north": 1, **change}
                with self.assertRaises(HTTPException) as raised:
                    murray.murray_hirise(**params)
                self.assertEqual(raised.exception.status_code, 422)
            with self.assertRaises(HTTPException) as raised:
                murray.murray_hirise_at(91, 0)
            self.assertEqual(raised.exception.status_code, 422)
            index.assert_not_called()

    def test_empty_place_catalog_has_no_invented_name(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(murray, "CACHE", Path(temp)), patch.object(murray, "_places", None):
            (Path(temp) / "names.geojson").write_text('{"features":[]}', encoding="utf-8")
            self.assertIsNone(murray.place_name(0, 0))


if __name__ == "__main__":
    unittest.main()
