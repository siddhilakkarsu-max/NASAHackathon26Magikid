"""
Tests for the gear system.   Run:  python -m unittest discover -s tests -v

Needs cubes/jezero.npz (the committed one is fine) for the tests that run the real planner.
"""
import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from gear import catalog, engine, rules, tools  # noqa: E402
from gear.context import ARCHETYPES, MissionContext, RouteStats, TerrainSignals  # noqa: E402
from gear.sources import SOURCES  # noqa: E402

BASE = {"lat": 18.4447, "lon": 77.4508}
TARGET = {"lat": 18.50, "lon": 77.40}


def ctx(**kw):
    return MissionContext(**kw)


class CatalogIntegrity(unittest.TestCase):
    def test_ids_unique_and_sources_exist(self):
        self.assertGreater(len(catalog.ITEMS), 90)
        for it in catalog.ITEMS.values():
            for s in it.sources:
                self.assertIn(s, SOURCES, f"{it.id} cites unknown source {s}")
            self.assertIn(it.conf, "VPEIN")
            self.assertIn(it.category, catalog.CATEGORY_LABEL)

    def test_numbers_are_not_invented(self):
        # a mass with no stated basis, or a basis with no mass, means someone guessed
        for it in catalog.ITEMS.values():
            if it.mass_kg is not None:
                self.assertIn(it.mass_basis, ("published", "analog", "derived"), it.id)
            else:
                self.assertEqual(it.mass_basis, "unknown", it.id)

    def test_every_item_a_rule_references_exists(self):
        for rl in rules.RULES:
            for m in re.finditer(r'A\(\s*"([a-z0-9_]+)"', inspect.getsource(rl.fn)):
                self.assertIn(m.group(1), catalog.ITEMS, f"rule {rl.id} adds unknown item {m.group(1)}")

    def test_rule_sources_exist(self):
        for rl in rules.RULES:
            for s in rl.sources:
                self.assertIn(s, SOURCES, rl.id)
        for key, (_v, _u, _c, srcs, _n) in rules.THRESHOLDS.items():
            for s in srcs:
                self.assertIn(s, SOURCES, key)

    def test_planner_vehicles_match_config(self):
        from config import VEHICLES
        keys = {i.planner_vehicle for i in catalog.ITEMS.values() if i.planner_vehicle}
        self.assertTrue(keys <= set(VEHICLES), keys - set(VEHICLES))
        self.assertIn("perseverance", VEHICLES)
        self.assertIn("perseverance", keys)

    def test_search(self):
        self.assertTrue(catalog.search("drill"))
        self.assertTrue(all(i.category == "drilling" for i in catalog.search(category="drilling")))
        strong = catalog.search(min_confidence="V")
        self.assertTrue(strong and all(i.conf == "V" for i in strong))


class Rules(unittest.TestCase):
    def kit(self, **kw):
        return engine.build_manifest(ctx(**kw))

    def ids(self, m):
        return {e["id"] for e in m["items"]}

    def triggered(self, m):
        return {r["id"] for r in m["rules"]}

    def test_every_archetype_builds(self):
        for a in ARCHETYPES:
            m = self.kit(archetype=a)
            self.assertGreater(m["summary"]["items"], 20, a)
            for e in m["items"]:
                self.assertGreaterEqual(e["qty"], 1)
                self.assertTrue(e["reasons"], f"{a}: {e['id']} has no reason")
                self.assertIn(e["priority"], ("critical", "recommended", "optional"))

    def test_stay_length_changes_the_kit(self):
        short = self.ids(self.kit(archetype="short_stay"))
        long_ = self.ids(self.kit(archetype="long_stay"))
        self.assertIn("v_pressurized_rover", short)
        self.assertNotIn("b_habitat", short)
        self.assertIn("b_habitat", long_)
        self.assertIn("b_exercise", long_)
        self.assertIn("r_shielding", long_)          # surface dose passes a quarter of the career limit
        self.assertNotIn("r_shielding", short)

    def test_goals_drive_instruments(self):
        bio = self.ids(self.kit(archetype="short_stay", goals=["biosignatures"]))
        self.assertTrue({"g_sterile_kit", "g_witness_tubes", "i_hand_nir", "i_hand_xrf"} <= bio)
        none = self.ids(self.kit(archetype="short_stay", goals=[]))
        self.assertNotIn("g_sterile_kit", none)
        self.assertNotIn("g_hammer", none)
        deep = self.ids(self.kit(archetype="drilling"))
        self.assertIn("d_drill_deep", deep)
        self.assertIn("d_drill_2m", deep)

    def test_sample_tube_counts_follow_the_protocol(self):
        m = self.kit(archetype="short_stay", goals=["biosignatures"], sample_sites=5)
        tubes = next(e for e in m["items"] if e["id"] == "g_sealed_tubes")
        witness = next(e for e in m["items"] if e["id"] == "g_witness_tubes")
        self.assertEqual(tubes["qty"], 35)           # 7 samples per site
        self.assertEqual(witness["qty"], 5)          # about 12 percent blanks

    def test_oxygen_check_uses_nasa_design_rate(self):
        route = RouteStats(distance_km=4.6, one_way_h=3.3, round_trip_h=6.55, o2_pct=82.0, max_slope_deg=5.0)
        m = self.kit(archetype="traverse", route=route)
        self.assertIn("S1", self.triggered(m))       # fits at 0.085 kg/h, not at 0.114 kg/h
        self.assertIn("v_pressurized_rover", self.ids(m))
        short = RouteStats(distance_km=1.0, one_way_h=0.4, round_trip_h=0.8, o2_pct=10.0, max_slope_deg=5.0)
        self.assertNotIn("S1", self.triggered(self.kit(archetype="traverse", route=short)))

    def test_shelter_time_rule(self):
        near = self.kit(archetype="traverse", route=RouteStats(one_way_h=0.4, round_trip_h=0.8, distance_km=1.0))
        far = self.kit(archetype="traverse", route=RouteStats(one_way_h=0.6, round_trip_h=1.2, distance_km=2.0))
        self.assertNotIn("S2", self.triggered(near))
        self.assertIn("S2", self.triggered(far))
        no_shelter = self.kit(archetype="traverse", base_has_shelter=False,
                              route=RouteStats(one_way_h=0.6, round_trip_h=1.2, distance_km=2.0))
        self.assertNotIn("S2", self.triggered(no_shelter))

    def test_slope_thresholds(self):
        def with_slope(s, loose=0.5, vehicle="astronaut"):
            return self.kit(archetype="traverse", vehicle=vehicle,
                            route=RouteStats(max_slope_deg=s, one_way_h=0.2, round_trip_h=0.4, distance_km=1.0),
                            terrain=TerrainSignals(max_slope_deg=s, loose_fraction=loose))
        flat = with_slope(8)
        self.assertFalse({"T1", "T3"} & self.triggered(flat))
        mid = with_slope(22)
        self.assertIn("T1", self.triggered(mid))
        self.assertIn("m_probe", self.ids(mid))
        self.assertNotIn("m_climbing_kit", self.ids(mid))
        steep = with_slope(35)
        self.assertIn("T3", self.triggered(steep))
        climbing = next(e for e in steep["items"] if e["id"] == "m_climbing_kit")
        self.assertEqual(climbing["priority"], "critical")
        firm = with_slope(22, loose=0.0)
        self.assertNotIn("T1", self.triggered(firm))
        rover = with_slope(22, vehicle="pressurized_rover")
        self.assertIn("T2", self.triggered(rover))   # beyond NASA's 15 degree pressurized-rover figure
        self.assertIn("m_recovery_gear", self.ids(rover))

    def test_hazards_send_robots_first(self):
        m = self.kit(archetype="cave")
        self.assertIn("T6", self.triggered(m))
        self.assertTrue({"m_aerial_scout", "v_perseverance", "m_climbing_kit", "helmet_lamp"} <= self.ids(m))
        self.assertTrue(any("proposal" in w for w in m["warnings"]))

    def test_cold_and_low_sun(self):
        m = self.kit(archetype="traverse", terrain=TerrainSignals(surface_temp_min_k=190.0, sun_elevation_deg=4.0))
        self.assertTrue({"T7", "T8"} <= self.triggered(m))
        self.assertIn("suit_thermal", self.ids(m))
        warm = self.kit(archetype="traverse", terrain=TerrainSignals(surface_temp_min_k=277.0, sun_elevation_deg=70.0))
        self.assertFalse({"T7", "T8"} & self.triggered(warm))

    def test_safety_items_are_critical(self):
        m = self.kit(archetype="short_stay")
        by_id = {e["id"]: e for e in m["items"]}
        for iid in ("suit_pgs", "h_storm_shelter", "h_spe_alarm", "med_core", "f_icr"):
            self.assertEqual(by_id[iid]["priority"], "critical", iid)

    def test_crewed_rover_carries_the_tools(self):
        m = self.kit(archetype="traverse", vehicle="pressurized_rover")
        by_id = {e["id"]: e for e in m["items"]}
        self.assertEqual(by_id["g_hammer"]["carried_by"], "rover")
        self.assertIn("g_tool_carrier", by_id)
        foot = {e["id"]: e for e in self.kit(archetype="traverse")["items"]}
        self.assertEqual(foot["g_hammer"]["carried_by"], "astronaut")

    def test_vehicles_are_not_summed(self):
        m = self.kit(archetype="short_stay")
        self.assertNotIn("vehicle", m["mass"]["by_carrier_kg"])

    def test_carry_overflow_moves_items_to_a_rover(self):
        saved = engine.CARRY_CAP_KG_PER_PERSON
        try:
            engine.CARRY_CAP_KG_PER_PERSON = 2.0
            m = self.kit(archetype="traverse", vehicle="pressurized_rover", goals=["geology", "biosignatures"])
            self.assertFalse(m["carry"]["over_cap"])
            m = self.kit(archetype="short_stay", goals=["geology", "biosignatures"])  # rover in kit via L1
            self.assertTrue(m["carry"]["moved"])
            self.assertFalse(m["carry"]["over_cap"])
        finally:
            engine.CARRY_CAP_KG_PER_PERSON = saved

    def test_carry_overflow_adds_a_cart_when_there_is_no_vehicle(self):
        saved = engine.CARRY_CAP_KG_PER_PERSON
        try:
            engine.CARRY_CAP_KG_PER_PERSON = 3.0
            m = self.kit(archetype="long_stay", goals=["geology"], hazards=[])
            by_id = {e["id"]: e for e in m["items"]}
            self.assertIn("m_hand_cart", by_id)
            self.assertEqual(by_id["g_hammer"]["carried_by"], "cart")
        finally:
            engine.CARRY_CAP_KG_PER_PERSON = saved

    def test_adjustments(self):
        adj = {"add": [{"item_id": "i_seismometer", "qty": 2, "reason": "Landing-site seismic survey"},
                       {"item_id": "no_such_item", "reason": "x"}],
               "remove": [{"item_id": "g_rake", "reason": "Fines only"}, {"item_id": "f_icr", "reason": "test"}]}
        m = engine.build_manifest(ctx(archetype="short_stay"), adj)
        by_id = {e["id"]: e for e in m["items"]}
        self.assertEqual(by_id["i_seismometer"]["qty"], 2)
        self.assertEqual(by_id["i_seismometer"]["reasons"][0]["rule"], "PLANNER")
        self.assertNotIn("g_rake", by_id)
        self.assertNotIn("f_icr", by_id)
        self.assertTrue(any("removed" in w and "critical" in w for w in m["warnings"]))
        self.assertTrue(any("unknown item" in w for w in m["warnings"]))
        self.assertEqual(len(m["adjustments"]["removed"]), 2)

    def test_budget_arithmetic(self):
        m = self.kit(archetype="short_stay", crew=2, stay_sols=10, eva_hours=6.0, eva_days=5)
        lines = {ln["label"]: ln for g in m["budget"]["groups"] for ln in g["lines"]}
        self.assertAlmostEqual(lines["Suit oxygen, one EVA (design rate)"]["value"], 0.684, places=3)
        self.assertAlmostEqual(lines["Suit oxygen over the whole stay (design rate)"]["value"], 0.114 * 6 * 5 * 2, places=2)
        self.assertAlmostEqual(m["budget"]["radiation"]["surface_dose_msv"], 0.67 * 10 * 1.0275, delta=0.1)
        self.assertIn("0.114", m["budget"]["planner_check"]["message"])

    def test_assumptions_are_reported(self):
        m = self.kit(archetype="drilling")
        self.assertTrue(any("planning default" in a for a in m["assumptions"]))
        full = engine.build_manifest(ctx(archetype="short_stay", crew=2, stay_sols=30, goals=[], hazards=[],
                                         power="battery", eva_hours=6, eva_days=10, sample_sites=0))
        self.assertFalse([a for a in full["assumptions"] if "default" in a and "Crew" in a])


class ToolContract(unittest.TestCase):
    def test_specs_are_valid_for_both_apis(self):
        for fmt in ("anthropic", "openai"):
            specs = tools.tool_specs(fmt)
            self.assertEqual(len(specs), len(tools.TOOLS))
            for s in specs:
                body = s if fmt == "anthropic" else s["function"]
                self.assertTrue(body["name"] and len(body["description"]) > 40)
                schema = body["input_schema"] if fmt == "anthropic" else body["parameters"]
                self.assertEqual(schema["type"], "object")
                self.assertNotIn("title", schema)

    def test_unknown_tool_and_bad_arguments(self):
        self.assertEqual(tools.call_tool("nope")["error"], "unknown_tool")
        bad = tools.call_tool("recommend_gear", {"context": {"archetype": "moon_base"}})
        self.assertEqual(bad["error"], "invalid_arguments")
        self.assertTrue(bad["details"])
        self.assertEqual(tools.call_tool("get_gear_item", {"item_id": "zzz"})["error"], "unknown_item")

    def test_each_tool_runs_without_a_route(self):
        self.assertTrue(tools.call_tool("list_mission_archetypes")["archetypes"])
        self.assertTrue(tools.call_tool("search_gear_catalog", {"query": "drill"})["items"])
        item = tools.call_tool("get_gear_item", {"item_id": "d_drill_2m"})
        self.assertEqual(item["item"]["id"], "d_drill_2m")
        self.assertIn("M3", [r["id"] for r in item["added_by_rules"]])
        self.assertTrue(tools.call_tool("list_gear_rules", {"group": "terrain"})["rules"])
        self.assertTrue(tools.call_tool("size_consumables", {"context": {"archetype": "short_stay"}})["groups"])
        carry = tools.call_tool("check_carry_load", {"items": [{"item_id": "g_hammer", "qty": 40}]})
        self.assertTrue(carry["over_cap"])
        summary = tools.call_tool("recommend_gear", {"context": {"archetype": "short_stay"}})
        self.assertIn("items", summary)
        self.assertNotIn("groups", summary)           # the summary form stays small for the agent
        self.assertLess(len(str(summary)), 40000)

    def test_adjustments_through_the_tool_interface(self):
        # validated input carries priority=None and qty=None explicitly; the engine must treat that as unset
        r = tools.call_tool("recommend_gear", {
            "context": {"archetype": "short_stay"}, "detail": "full",
            "adjustments": {"add": [{"item_id": "i_seismometer", "reason": "baseline"}],
                            "remove": [{"item_id": "g_rake", "reason": "not needed"}]}})
        self.assertNotIn("error", r, r)
        by_id = {e["id"]: e for e in r["items"]}
        self.assertEqual(by_id["i_seismometer"]["priority"], "recommended")
        self.assertEqual(by_id["i_seismometer"]["qty"], 1)
        self.assertNotIn("g_rake", by_id)

    def test_publish_is_stored(self):
        tools.PUBLISHED.update(manifest=None, published_at=None, note=None)
        tools.call_tool("recommend_gear", {"context": {"archetype": "traverse"}, "publish": True, "note": "unit test"})
        self.assertEqual(tools.PUBLISHED["note"], "unit test")
        self.assertEqual(tools.PUBLISHED["manifest"]["context"]["archetype"], "traverse")

    def test_route_context_runs_the_planner(self):
        r = tools.call_tool("get_route_context", {"region": "jezero", "vehicle": "astronaut", "base": BASE, "target": TARGET,
                                                  "budget_hours": 8})
        self.assertTrue(r["route_found"], r)
        self.assertGreater(r["route"]["distance_km"], 1)
        self.assertGreater(r["terrain"]["samples"], 3)
        self.assertTrue(0 <= r["terrain"]["loose_fraction"] <= 1)

    def test_route_flows_into_the_kit(self):
        m = tools.call_tool("recommend_gear", {"context": {"archetype": "traverse", "route_request": {
            "region": "jezero", "vehicle": "astronaut", "base": BASE, "target": TARGET, "budget_hours": 8}}})
        # exact distance depends on the cube's resolution, which changes whenever the data is rebuilt
        self.assertGreater(m["context"]["route"]["distance_km"], 3)
        self.assertGreater(m["context"]["route"]["round_trip_h"], 2)
        ids = {r["id"] for r in m["triggered_rules"]}
        self.assertTrue({"S1", "S2", "S3"} <= ids, ids)

    def test_unreachable_point_comes_back_as_data(self):
        r = tools.call_tool("get_route_context", {"region": "jezero", "vehicle": "astronaut", "base": {"lat": 0, "lon": 0},
                                                  "target": TARGET})
        self.assertIn("error", r)


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gear_server import server
        cls.c = TestClient(server)

    def test_tools_endpoints(self):
        r = self.c.get("/api/gear/tools?format=openai")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get("/api/gear/tools?format=nope").status_code, 400)
        r = self.c.post("/api/gear/tools/recommend_gear", json={"context": {"archetype": "isru"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.post("/api/gear/tools/recommend_gear", json={"context": {"archetype": "x"}}).status_code, 400)
        self.assertEqual(self.c.post("/api/gear/tools/get_gear_item", json={"item_id": "x"}).status_code, 404)

    def test_kit_and_published(self):
        tools.PUBLISHED.update(manifest=None, published_at=None, note=None)
        empty = self.c.get("/api/gear/published")
        self.assertEqual(empty.status_code, 200)
        self.assertIsNone(empty.json()["manifest"])
        k = self.c.post("/api/gear/kit", json={"context": {"archetype": "long_stay"}})
        self.assertEqual(k.status_code, 200)
        self.assertIn("groups", k.json())
        self.c.post("/api/gear/tools/recommend_gear", json={"context": {"archetype": "long_stay"}, "publish": True, "note": "n"})
        p = self.c.get("/api/gear/published")
        self.assertEqual(p.status_code, 200)
        self.assertEqual(p.json()["note"], "n")

    def test_reference_endpoints_and_page(self):
        cat = self.c.get("/api/gear/catalog").json()
        self.assertEqual(cat["count"], len(catalog.ITEMS))
        self.assertEqual(len(self.c.get("/api/gear/archetypes").json()["archetypes"]), len(ARCHETYPES))
        self.assertTrue(self.c.get("/api/gear/rules").json()["rules"])
        self.assertEqual(self.c.get("/kit.html").status_code, 200)
        self.assertEqual(self.c.get("/kit.css").status_code, 200)
        self.assertEqual(self.c.get("/kit.js").status_code, 200)
        self.assertEqual(self.c.get("/api/regions").status_code, 200)   # planner still reachable through the wrapper


class PerseveranceVehicle(unittest.TestCase):
    def test_in_the_vehicle_list_and_plans_a_route(self):
        import app as planner
        client = TestClient(planner.app)
        meta = client.get("/api/regions").json()
        self.assertIn("perseverance", meta["vehicles"])
        spec = meta["vehicle_specs"]["perseverance"]
        self.assertEqual(spec["max_slope"], 30.0)
        self.assertEqual(spec["energy_capacity_kwh"], 2.5)
        self.assertTrue(spec["source"])
        r = client.post("/api/plan", json={"region": "jezero", "vehicle": "perseverance", "budget_hours": 8,
                                           "base": BASE, "target": {"lat": 18.452, "lon": 77.444}})
        self.assertEqual(r.status_code, 200)
        stats = r.json()["stats"]
        self.assertIsNotNone(stats["energy_used_kwh"])
        self.assertIsNone(stats["o2_used_kg"])


if __name__ == "__main__":
    unittest.main()
