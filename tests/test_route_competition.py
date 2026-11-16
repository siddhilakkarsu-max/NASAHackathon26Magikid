"""Deterministic scientific comparison rules and authenticated attempt state.

Uses temporary SQLite databases and explicit planar fixtures. The real measured
dataset gets a separate smoke test; no fixture is ever served as mission data.
"""
import copy
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import competition_terrain as terrain_module
import leaderboard as players
import route_competition as competition


def plane(grade_x=0, grade_y=0, missing=None, steep=None, thermal=300):
    size, spacing = 61,10.0
    yy,xx = np.mgrid[0:size,0:size]
    elevation = grade_x*xx*spacing+grade_y*(size-1-yy)*spacing
    valid = np.ones((size,size),dtype=bool)
    slope = np.full((size,size),math.degrees(math.atan(math.hypot(grade_x,grade_y))))
    if missing:
        valid[missing] = False
    if steep:
        slope[steep] = 40
    manifest = dict(dataset_version="test-plane-v1",artifact={"sha256":"fixture-plane"},
                    name="Explicit test fixture",grid={"resolution_m":spacing},
                    projection={"origin_easting_m":0,"origin_northing_m":0},
                    geographic_bounds={},elevation={},slope={},thermal_inertia={},limitations=[])
    return terrain_module.Terrain(manifest,elevation,valid,slope,np.full((size,size),thermal),np.ones((size,size),bool))


class CompetitionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ,{"MARSWALK_GAME_STATE_DIR":self.tmp.name})
        self.env.start()
        self.terrain = plane()
        self.terrain_patch = patch.object(competition,"_terrain",lambda:self.terrain)
        self.terrain_patch.start()
        self.start_patch = patch.object(competition,"START",[100.0,100.0])
        self.start_patch.start()
        self.now = 1000.0
        self.clock_patch = patch.object(competition.time,"time",lambda:self.now)
        self.clock_patch.start()
        app = FastAPI()
        app.include_router(players.router)
        app.include_router(competition.router)
        self.client = TestClient(app)
        self.player = self.claim("Rover One")
        self.mission = competition._create_mission(competition.MissionRequest(
            goal="A concrete survey",destination=[400,100],required_stops=[[200,100],[300,100]]))
        self.route = [[100,100],[200,100],[300,100],[400,100]]

    def tearDown(self):
        for module in (players,competition):
            if module._conn is not None:
                module._conn.close()
                module._conn = None
                module._conn_path = None
        self.clock_patch.stop()
        self.start_patch.stop()
        self.terrain_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def claim(self,name):
        response = self.client.post("/api/game/players",json={"name":name})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def start(self,player=None,key="confirm-route-01",route=None):
        response = self.client.post("/api/competition/attempts",json=dict(player or self.player,
            mission_id=self.mission["id"],route=route or self.route,idempotency_key=key))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def progress(self,attempt,position,mode="driving",elapsed=0.5,player=None):
        self.now += elapsed
        return self.client.post(f"/api/competition/attempts/{attempt['id']}/progress",json=dict(
            player or self.player,sequence=attempt["sequence"]+1,mode=mode,position=position))

    def drive(self,attempt,player=None,step_seconds=.5):
        response = self.progress(attempt,attempt["position"],player=player)
        self.assertEqual(response.status_code,200,response.text)
        attempt = response.json()
        while attempt["position"][0] < 400:
            target = [min(400,attempt["position"][0]+8),100]
            response = self.progress(attempt,target,player=player,elapsed=step_seconds)
            self.assertEqual(response.status_code,200,response.text)
            attempt = response.json()
        return attempt

    def finish(self,attempt,player=None):
        return self.client.post(f"/api/competition/attempts/{attempt['id']}/finish",json=player or self.player)

    def test_flat_model_has_independent_expected_time_and_energy(self):
        scored = competition.evaluate_route(self.mission,self.route)
        self.assertEqual(scored["metrics"]["distance_m"],300)
        self.assertEqual(scored["metrics"]["simulated_time_s"],7500)
        self.assertAlmostEqual(scored["metrics"]["energy_wh"],110*7500/3600,places=3)
        dense = [[x,100] for x in range(100,401)]
        self.assertEqual(scored,competition.evaluate_route(self.mission,dense))

    def test_directional_grade_and_positive_climb_energy(self):
        self.terrain = plane(grade_x=.1)
        scored = competition.evaluate_route(self.mission,self.route)
        expected_time = math.hypot(300,30)/.04*2
        expected_energy = 110*expected_time/3600+30*899*3.71/.7/3600
        self.assertAlmostEqual(scored["metrics"]["simulated_time_s"],expected_time,places=3)
        self.assertAlmostEqual(scored["metrics"]["energy_wh"],expected_energy,places=3)

    def test_short_turn_cannot_hide_elevation_excursion_between_stations(self):
        self.terrain = plane(grade_x=.2)
        mission = dict(self.mission,start=[100,100],destination=[100,200],required_stops=[])
        route = [[100,100],[102,100],[100,102],[100,200]]
        scored = competition.evaluate_route(mission,route)
        rise = self.terrain.sample(102,100)["elevation_m"]-self.terrain.sample(100,100)["elevation_m"]
        expected = competition._travel_seconds(2,rise)+competition._travel_seconds(math.sqrt(8),-rise)+98/.04
        self.assertAlmostEqual(scored["metrics"]["simulated_time_s"],expected,places=3)
        self.assertGreater(scored["metrics"]["energy_wh"],scored["metrics"]["simulated_time_s"]*110/3600+.5)

    def test_thermal_inertia_never_changes_route_score(self):
        before = competition.evaluate_route(self.mission,self.route)
        self.terrain = plane(thermal=5)
        self.assertEqual(before,competition.evaluate_route(self.mission,self.route))

    def test_identity_excludes_goal_wording_and_personalized_route(self):
        another = competition._create_mission(competition.MissionRequest(
            goal="Completely different prose",destination=[400,100],required_stops=[[200,100],[300,100]]))
        self.assertEqual(self.mission["id"],another["id"])
        self.assertEqual(self.mission["goal"],"A concrete survey")
        self.assertEqual(another["goal"],"Completely different prose")
        self.assertEqual(competition._mission(self.mission["id"])["goal"],"A concrete survey")
        self.assertEqual(self.mission["reference"],another["reference"])
        altered = competition._create_mission(competition.MissionRequest(
            destination=[400,120],required_stops=[[200,100],[300,100]]))
        self.assertNotEqual(self.mission["id"],altered["id"])
        personalized = [[100,100],[200,100],[250,120],[300,100],[400,100]]
        competition.evaluate_route(self.mission,personalized)
        self.assertEqual(competition._mission(self.mission["id"])["reference"],self.mission["reference"])

    def test_segments_cannot_cross_missing_steep_or_outside_cells(self):
        # Vertices are safe; an interior native cell rejects the entire segment.
        for changed in (plane(missing=(50,25)),plane(steep=(50,25))):
            self.terrain = changed
            with self.assertRaises(HTTPException) as caught:
                competition.evaluate_route(self.mission,[[100,100],[400,100]])
            self.assertEqual(caught.exception.status_code,400)
        self.terrain = plane()
        for bad in ([[100,100],[-1,100],[400,100]],[[100,100],[400,200]],[[101,100],[400,100]]):
            with self.assertRaises(HTTPException):
                competition.evaluate_route(self.mission,bad)

    def test_ordered_objectives_and_finite_input(self):
        bad = [[100,100],[100,180],[310,180],[310,100],[200,100],[200,40],[400,40],[400,100]]
        with self.assertRaises(HTTPException):
            competition.evaluate_route(self.mission,bad)
        response = self.client.post(f"/api/competition/missions/{self.mission['id']}/evaluate",json={"route":[[100,100],["NaN",100],[400,100]]})
        self.assertEqual(response.status_code,422)

    def test_authentication_and_attempt_ownership(self):
        attempt = self.start()
        stranger = self.claim("Other Rover")
        response = self.progress(attempt,attempt["position"],player=stranger)
        self.assertEqual(response.status_code,403)
        wrong = dict(self.player,token="wrong-secret-token")
        self.assertEqual(self.finish(attempt,wrong).status_code,403)
        response = self.client.get(f"/api/competition/attempts/{attempt['id']}",headers={"X-Callsign":self.player["name"],"Authorization":"Bearer x"})
        self.assertEqual(response.status_code,401)

    def test_confirm_is_idempotent_and_changes_invalidate_previous_attempt(self):
        first = self.start()
        self.assertEqual(first,self.start())
        response = self.client.post("/api/competition/attempts",json=dict(self.player,mission_id=self.mission["id"],
            route=[[100,100],[200,100],[250,110],[300,100],[400,100]],idempotency_key="confirm-route-01"))
        self.assertEqual(response.status_code,409)
        new = self.start(key="confirm-route-02")
        self.assertNotEqual(new["id"],first["id"])
        self.assertEqual(self.finish(first).status_code,409)
        self.assertEqual(new["distance_m"],0)

    def test_cannot_finish_early_or_submit_client_score(self):
        attempt = self.start()
        self.assertEqual(self.finish(attempt).status_code,400)
        response = self.client.post(f"/api/competition/attempts/{attempt['id']}/finish",json=dict(self.player,score=1,active_drive_s=1))
        self.assertEqual(response.status_code,422)
        self.assertEqual(self.client.get("/api/competition/leaderboard",params={"mission_id":self.mission["id"]}).json()["board"],[])

    def test_progress_rejects_teleport_sequence_skip_and_time_during_pause(self):
        attempt = self.start()
        self.assertEqual(self.progress(attempt,[108,100]).status_code,400)
        response = self.progress(attempt,[100,100])
        self.assertEqual(response.status_code,200,response.text)
        attempt = response.json()
        self.assertEqual(self.progress(attempt,[300,100]).status_code,400)
        self.now += .5
        response = self.client.post(f"/api/competition/attempts/{attempt['id']}/progress",json=dict(self.player,
            sequence=attempt["sequence"]+2,mode="driving",position=[100,100]))
        self.assertEqual(response.status_code,409)
        response = self.progress(attempt,[100,100],mode="paused",elapsed=0)
        self.assertEqual(response.status_code,200,response.text)
        attempt = response.json()
        self.assertEqual(self.progress(attempt,[108,100],elapsed=20).status_code,400)

    def test_grade_speed_limit_applies_to_driving(self):
        self.terrain = plane(grade_x=.1)
        attempt = self.start()
        attempt = self.progress(attempt,[100,100]).json()
        self.assertEqual(self.progress(attempt,[108,100]).status_code,400)
        response = self.progress(attempt,[103,100],elapsed=0)
        self.assertEqual(response.status_code,200,response.text)

    def test_long_heartbeat_gap_and_refresh_grant_no_motion_or_active_time(self):
        attempt = self.start()
        attempt = self.progress(attempt,[100,100]).json()
        self.assertEqual(self.progress(attempt,[108,100],elapsed=3).status_code,400)
        refreshed = self.client.post(f"/api/competition/attempts/{attempt['id']}/resume",json=self.player).json()
        self.assertEqual(refreshed["mode"],"paused")
        self.assertEqual(refreshed["active_drive_s"],0)
        self.assertEqual(refreshed["position"],[100,100])

    def test_progress_retry_does_not_double_count_time_or_stops(self):
        attempt = self.start()
        attempt = self.progress(attempt,[100,100]).json()
        body = dict(self.player,sequence=attempt["sequence"]+1,mode="driving",position=[108,100])
        self.now += .5
        first = self.client.post(f"/api/competition/attempts/{attempt['id']}/progress",json=body)
        self.assertEqual(first.status_code,200,first.text)
        self.now += .2
        repeated = self.client.post(f"/api/competition/attempts/{attempt['id']}/progress",json=body)
        self.assertEqual(first.json(),repeated.json())

    def test_exact_corridor_rejects_shortcut_even_when_endpoints_are_near(self):
        route = [[0,0],[0,100],[100,100]]
        self.assertFalse(competition._swept_in_corridor(route,[0,20],[80,100],0,200))
        self.assertTrue(competition._swept_in_corridor(route,[0,80],[20,100],0,200))

    def test_finish_is_idempotent_and_equal_scores_share_rank(self):
        first = self.drive(self.start())
        response = self.finish(first)
        self.assertEqual(response.status_code,200,response.text)
        result = response.json()
        self.assertEqual(result["rank"],1)
        self.assertEqual(result["metrics"]["simulated_time_s"],7500)
        self.assertEqual(result,self.finish(first).json())
        second_player = self.claim("Second Rover")
        second = self.start(player=second_player,key="another-confirm-01")
        self.now += 25
        second = self.drive(second,second_player,step_seconds=1.0)
        self.assertEqual(self.finish(second,second_player).json()["rank"],1)
        self.assertGreater(second["active_drive_s"],first["active_drive_s"])
        third_player = self.claim("Third Rover")
        detour = [[100,100],[200,100],[250,120],[300,100],[400,100]]
        third = self.drive(self.start(player=third_player,key="third-confirm-01",route=detour),third_player)
        self.assertEqual(self.finish(third,third_player).json()["rank"],3)
        board = self.client.get("/api/competition/leaderboard",params={"mission_id":self.mission["id"]}).json()["board"]
        self.assertEqual([row["rank"] for row in board],[1,1,3])
        self.assertEqual(len(board),3)
        self.assertEqual(self.client.get("/api/game/leaderboard").json()["board"],[])

    def test_resume_and_results_survive_database_reopen(self):
        attempt = self.drive(self.start())
        result = self.finish(attempt).json()
        competition._conn.close()
        competition._conn = None
        response = self.client.get(f"/api/competition/attempts/{attempt['id']}",headers={
            "X-Callsign":self.player["name"],"Authorization":"Bearer "+self.player["token"]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),result)

    def test_changed_model_or_terrain_cannot_reuse_old_mission(self):
        changed = copy.deepcopy(self.mission)
        changed["terrain_identity"]["dataset_sha256"] = "different"
        with self.assertRaises(HTTPException) as caught:
            competition.evaluate_route(changed,self.route)
        self.assertEqual(caught.exception.status_code,409)
        changed = copy.deepcopy(self.mission)
        changed["model"]["base_speed_m_s"] = 100
        with self.assertRaises(HTTPException) as caught:
            competition.evaluate_route(changed,self.route)
        self.assertEqual(caught.exception.status_code,409)


class MeasuredTerrainSmokeTest(unittest.TestCase):
    def test_default_objectives_and_graph_route_use_available_measured_terrain(self):
        terrain = terrain_module.load_terrain()
        route = []
        for a,b in zip([competition.START]+[p["xy"] for p in competition.CATALOG[:-1]], [p["xy"] for p in competition.CATALOG]):
            leg = competition._graph_route(terrain,a,b)
            route.extend(leg if not route else leg[1:])
        mission = dict(start=competition.START,destination=competition.CATALOG[-1]["xy"],
            required_stops=[dict(id=f"s{i}",xy=p["xy"],radius_m=30) for i,p in enumerate(competition.CATALOG[:-1])],
            terrain_identity=competition._terrain_identity(terrain),model=competition.MODEL)
        scored = competition.evaluate_route(mission,route,terrain)
        self.assertTrue(600 < scored["metrics"]["distance_m"] < 1500)
        self.assertGreater(scored["metrics"]["energy_wh"],0)
        self.assertEqual(scored,competition.evaluate_route(mission,route,terrain))


if __name__ == "__main__":
    unittest.main()
