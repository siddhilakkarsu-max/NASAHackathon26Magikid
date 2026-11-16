"""Headless tests of the original planner/game route comparison bridge.

Synthetic grids here are test fixtures only; production captures the planner's
own cube and result. No fixture is exposed as a playable mission.
"""
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import game_routes as routes
import leaderboard
from config import MARS_RADIUS_M, SITE_HOURS


class Cube:
    region = "test_region"
    H = W = 10
    w = s = 0.
    n = e = .02
    provenance = ["Synthetic test fixture, not mission data"]
    rect = dict(west=w, east=e, south=s, north=n)
    pixel_m = (n/H*math.pi/180*MARS_RADIUS_M,
               e/W*math.pi/180*MARS_RADIUS_M*math.cos(math.radians(n/2)))

    def __init__(self):
        self.bands = dict(elevation=np.full((10,10), -2000., dtype="float32"),
                          slope=np.ones((10,10), dtype="float32"),
                          roughness=np.ones((10,10), dtype="float32"),
                          firmness=np.full((10,10), .8, dtype="float32"),
                          thermal_inertia=np.full((10,10), 350., dtype="float32"))

    @classmethod
    def point(cls,r,c):
        return dict(lat=cls.n-(r+.5)*cls.n/cls.H, lon=(c+.5)*cls.e/cls.W)


def plan(plan_id="original", vehicle="buggy", hour=12):
    points=[Cube.point(3,2),Cube.point(3,6)]
    return dict(id=plan_id,settings=dict(goal="Find clay near water",vehicle=dict(key=vehicle),
                  season=dict(key="northern_summer",ls=90),local_hour=hour,priority=dict(key="safety")),
                tools=dict(kg=10),candidates=[dict(A=points[0],B=points[-1],
                  route=dict(points=points,one_way_h=1,round_trip_h=3),
                  card=dict(sampling=[dict(**points[-1],what="clay")]))])


class GameRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"MARSWALK_GAME_STATE_DIR":self.tmp.name})
        self.env.start()
        # Patch this module's clock proxy, not the global time module used by
        # asyncio/TestClient; otherwise the test transport clock could freeze.
        self.clock=1000.
        self.timer=patch.object(routes,"time",wraps=routes.time)
        self.time=self.timer.start()
        self.time.monotonic.side_effect=lambda:self.clock
        self.app=FastAPI()
        self.app.include_router(leaderboard.router)
        self.app.include_router(routes.router)
        self.client=TestClient(self.app)
        self.cube=Cube()
        self.original=plan()
        routes.capture_plan(self.original,self.cube)

    def tearDown(self):
        self.client.close()
        self.timer.stop()
        for module in (routes,leaderboard):
            if module._conn is not None:
                module._conn.close()
                module._conn=None
        routes._terrain_cache.clear()
        self.env.stop()
        self.tmp.cleanup()

    def get(self,identifier="original"):
        r=self.client.get("/api/game/plans/"+identifier)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def evaluate(self,points=None,identifier="original"):
        return self.client.post(f"/api/game/plans/{identifier}/evaluate",
                                json=dict(candidate=0,points=points or self.original["candidates"][0]["route"]["points"]))

    def claim(self,name="PilotOne"):
        response=self.client.post("/api/game/players",json=dict(name=name))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def start(self,player=None,key="attempt-one",points=None):
        player=player or self.claim()
        response=self.client.post("/api/game/route-attempts",json=dict(
            player,plan_id="original",candidate=0,idempotency_key=key,
            points=points or self.original["candidates"][0]["route"]["points"]))
        self.assertEqual(response.status_code,200,response.text)
        return player,response.json()

    def progress(self,player,state,position=None,mode="driving",samples=0,dt=1):
        self.clock+=dt
        response=self.client.post(f"/api/game/route-attempts/{state['id']}/progress",json=dict(
            player,sequence=state["sequence"]+1,position=position or state["position"],mode=mode,samples=samples))
        return response

    def drive_to_objective(self,player,state,dt=1,sample=True):
        response=self.progress(player,state,dt=0)
        self.assertEqual(response.status_code,200,response.text)
        state=response.json()
        a,b=state["points"][0],state["points"][-1]
        # Every transmitted displacement is <60m and crosses known valid cells.
        for t in np.linspace(0,1,13)[1:]:
            point={k:a[k]+(b[k]-a[k])*float(t) for k in ("lat","lon")}
            response=self.progress(player,state,point,samples=int(sample and t==1),dt=dt)
            self.assertEqual(response.status_code,200,response.text)
            state=response.json()
        return state

    def finish_body(self,player,state,ticks=1200):
        return dict(player,ai_drive_ticks=ticks,route_hash=state["route_hash"],benchmark_version=routes.BENCHMARK_VERSION)

    def finish(self,player,state,ticks=1200):
        return self.client.post(f"/api/game/route-attempts/{state['id']}/finish",json=self.finish_body(player,state,ticks))

    def test_original_capture_preserves_id_goal_coordinates_and_is_immutable(self):
        saved=self.get()
        self.assertTrue(saved["available"],saved.get("reason"))
        self.assertEqual(saved["plan"]["id"],"original")
        self.assertEqual(saved["plan"]["settings"],self.original["settings"])
        self.assertEqual(saved["plan"]["candidates"],self.original["candidates"])
        for actual,expected in zip(saved["reference"]["points"],self.original["candidates"][0]["route"]["points"]):
            self.assertAlmostEqual(actual["lat"],expected["lat"],places=8)
            self.assertAlmostEqual(actual["lon"],expected["lon"],places=8)
        self.assertEqual(saved["plan"]["request_region"],"test_region")
        changed=copy.deepcopy(self.original)
        changed["settings"]["goal"]="Browser supplied change"
        self.cube.bands["elevation"][:]=2000
        routes.capture_plan(changed,self.cube)
        self.assertEqual(self.get()["plan"],saved["plan"])
        self.assertEqual(self.get()["terrain"]["dataset_id"],saved["terrain"]["dataset_id"])

    def test_grid_nodes_are_north_first_and_geographically_aligned(self):
        terrain=self.get()["terrain"]
        self.assertEqual(terrain["grid"]["shape"],[10,10])
        self.assertEqual(terrain["rect"]["north"],Cube.point(0,0)["lat"])
        self.assertEqual(terrain["rect"]["east"],Cube.point(9,9)["lon"])
        self.assertEqual(terrain["boundary"],self.cube.rect)
        self.assertEqual(terrain["grid"]["elevation_m"][0][0],-2000)
        self.assertAlmostEqual(terrain["grid"]["firmness"][0][0],.8)
        self.assertEqual(terrain["sources"],self.cube.provenance)

    def test_scores_repeat_and_do_not_depend_on_collinear_waypoint_density(self):
        first=self.evaluate().json()
        points=[Cube.point(3,2),Cube.point(3,4),Cube.point(3,6)]
        split=self.evaluate(points).json()
        self.assertEqual(first["metrics"],split["metrics"])
        self.assertEqual(first["reference_metrics"],first["metrics"])
        self.assertEqual(first["metrics"]["one_way_time_s"],first["metrics"]["simulated_time_s"])
        self.assertAlmostEqual(first["metrics"]["round_trip_time_s"],2*first["metrics"]["simulated_time_s"],delta=.0011)
        self.assertEqual(first["metrics"]["one_way_energy_wh"],first["metrics"]["energy_wh"])
        self.assertAlmostEqual(first["metrics"]["round_trip_energy_wh"],2*first["metrics"]["energy_wh"],delta=.0011)
        self.assertEqual(first["metrics"]["science_time_s"],SITE_HOURS*3600)
        self.assertEqual(first,self.evaluate().json())

    def test_longer_route_costs_more_and_slope_changes_time(self):
        straight=self.evaluate().json()["metrics"]
        detour=self.evaluate([Cube.point(3,2),Cube.point(1,4),Cube.point(3,6)]).json()["metrics"]
        self.assertGreater(detour["simulated_time_s"],straight["simulated_time_s"])
        self.assertGreater(detour["energy_wh"],straight["energy_wh"])
        self.cube.bands["slope"][:]=10
        routes.capture_plan(plan("steep"),self.cube)
        steep=self.evaluate(identifier="steep").json()["metrics"]
        self.assertGreater(steep["simulated_time_s"],straight["simulated_time_s"])

    def test_one_way_energy_counts_only_outbound_climbs(self):
        for col in range(10):
            self.cube.bands["elevation"][:,col]=-2000+10*col
        uphill=plan("uphill")
        downhill=copy.deepcopy(uphill)
        downhill["id"]="downhill"
        cand=downhill["candidates"][0]
        cand["route"]["points"].reverse()
        cand["A"],cand["B"]=cand["B"],cand["A"]
        routes.capture_plan(uphill,self.cube)
        routes.capture_plan(downhill,self.cube)
        up=self.evaluate(identifier="uphill").json()["metrics"]
        down=self.evaluate(cand["route"]["points"],identifier="downhill").json()["metrics"]
        self.assertGreater(up["one_way_energy_wh"],down["one_way_energy_wh"])
        self.assertAlmostEqual(up["round_trip_energy_wh"],up["one_way_energy_wh"]+down["one_way_energy_wh"],delta=.0011)
        self.assertEqual(up["round_trip_energy_wh"],down["round_trip_energy_wh"])

    def test_material_map_uses_existing_cube_and_preserves_nodata(self):
        self.cube.bands["thermal_inertia"][1,2]=np.nan
        self.cube.bands["firmness"][1,2]=np.nan
        getter=Mock(return_value=self.cube)
        with patch.dict(sys.modules,{"app":SimpleNamespace(get_cube=getter)}):
            response=self.client.get("/api/game/materials",params=dict(region="jezero"))
            self.assertEqual(response.status_code,200,response.text)
            terrain=response.json()["terrain"]
            self.assertEqual(terrain["rect"]["north"],Cube.point(0,0)["lat"])
            self.assertEqual(terrain["rect"]["east"],Cube.point(9,9)["lon"])
            self.assertEqual(terrain["sources"],self.cube.provenance)
            self.assertIsNone(terrain["grid"]["thermal_inertia"][1][2])
            self.assertIsNone(terrain["grid"]["firmness"][1][2])
            getter.assert_called_once_with("jezero")
            getter.reset_mock()
            self.assertEqual(self.client.get("/api/game/materials",params=dict(region="../secrets")).status_code,400)
            getter.assert_not_called()
            getter.side_effect=HTTPException(404,"Cube unavailable")
            self.assertEqual(self.client.get("/api/game/materials",params=dict(region="gale")).status_code,404)

    def test_material_zoom_preserves_native_planner_observations(self):
        values=np.arange(1024*1024,dtype=float).reshape(1024,1024)+1
        cube=SimpleNamespace(rect=self.cube.rect,pixel_m=(2.,2.),provenance=self.cube.provenance,
                             bands=dict(thermal_inertia=values))
        with patch.dict(sys.modules,{"app":SimpleNamespace(get_cube=Mock(return_value=cube))}):
            full=self.client.get("/api/game/materials").json()["terrain"]
            response=self.client.get("/api/game/materials",params=dict(west=.009,south=.009,east=.011,north=.011))
            self.assertEqual(response.status_code,200,response.text)
            close=response.json()["terrain"]
            self.assertEqual(full["display_resolution_m"],[4.,4.])
            self.assertEqual(close["display_resolution_m"],[2.,2.])
            self.assertEqual(close["sources"],cube.provenance)
            self.assertEqual(close["grid"]["thermal_inertia"][0][1]-close["grid"]["thermal_inertia"][0][0],1)
            self.assertEqual(close["grid"]["thermal_inertia"][1][0]-close["grid"]["thermal_inertia"][0][0],1024)
            for bounds in (dict(west=0),dict(west=.01,east=0,south=0,north=.01)):
                self.assertEqual(self.client.get("/api/game/materials",params=bounds).status_code,400)
            self.assertEqual(self.client.get("/api/game/materials",params=dict(west=1,east=2,south=1,north=2)).status_code,404)

    def test_material_grid_bounded_and_older_capture_remains_readable(self):
        record,_=routes._plan("original")
        routes._terrain(record["terrain"]).pop("firmness")
        self.assertNotIn("firmness",self.get()["terrain"]["grid"])
        self.assertTrue(self.get()["available"])
        cube=SimpleNamespace(rect=self.cube.rect,pixel_m=self.cube.pixel_m,provenance=self.cube.provenance,
                             bands=dict(thermal_inertia=np.full((1025,1300),350.)))
        with patch.dict(sys.modules,{"app":SimpleNamespace(get_cube=Mock(return_value=cube))}):
            response=self.client.get("/api/game/materials")
        self.assertEqual(response.status_code,200,response.text)
        grid=response.json()["terrain"]["grid"]
        self.assertLessEqual(max(grid["shape"]),512)
        self.assertNotIn("firmness",grid)

    def test_board_key_separates_vehicle_time_region_and_objectives(self):
        keys={self.get()["key"]}
        for identifier,vehicle,hour in (("different-hour","buggy",14),("different-vehicle","four_wheel",12)):
            routes.capture_plan(plan(identifier,vehicle,hour),self.cube)
            keys.add(self.get(identifier)["key"])
        self.cube.region="other_region"
        routes.capture_plan(plan("different-region"),self.cube)
        keys.add(self.get("different-region")["key"])
        self.cube.region="test_region"
        changed=plan("different-science")
        changed["candidates"][0]["card"]["sampling"][0]["what"]="olivine"
        routes.capture_plan(changed,self.cube)
        keys.add(self.get("different-science")["key"])
        self.assertEqual(len(keys),5)

    def test_same_mission_new_id_has_same_key(self):
        routes.capture_plan(plan("second-id"),self.cube)
        self.assertEqual(self.get()["key"],self.get("second-id")["key"])

    def test_changed_start_outside_boundary_and_missing_segment_are_rejected(self):
        points=self.original["candidates"][0]["route"]["points"]
        self.assertEqual(self.evaluate([Cube.point(2,2),points[-1]]).status_code,400)
        self.assertEqual(self.evaluate([points[0],dict(lat=.03,lon=.01),points[-1]]).status_code,400)
        self.cube.bands["elevation"][3,4]=np.nan
        routes.capture_plan(plan("gap"),self.cube)
        self.assertEqual(self.evaluate(identifier="gap").status_code,400)
        self.assertFalse(self.get("gap")["available"])
        self.assertIsNone(self.get("gap")["terrain"]["grid"]["elevation_m"][3][4])

    def test_steep_cell_touched_at_corner_is_not_skipped(self):
        self.cube.bands["slope"][3,3]=80
        original=plan("corner")
        original["candidates"][0]["route"]["points"]=[Cube.point(2,3),Cube.point(3,2)]
        routes.capture_plan(original,self.cube)
        self.assertFalse(self.get("corner")["available"])

    def test_missing_material_disables_ranking_but_preserves_mission_and_topography(self):
        self.cube.bands["thermal_inertia"][:]=np.nan
        routes.capture_plan(plan("missing-material"),self.cube)
        saved=self.get("missing-material")
        self.assertFalse(saved["available"])
        self.assertEqual(saved["plan"]["settings"]["goal"],"Find clay near water")
        self.assertIn("terrain",saved)
        self.assertEqual(saved["terrain"]["grid"]["elevation_m"][0][0],-2000)

    def test_auth_early_finish_and_unsupported_score_fields_rejected(self):
        player,state=self.start()
        self.assertEqual(self.finish(player,state).status_code,400)
        self.assertEqual(self.client.post(f"/api/game/route-attempts/{state['id']}/finish",json=dict(player,simulated_time_s=1)).status_code,422)
        self.assertEqual(self.finish(dict(player,token="wrong-token"),state).status_code,403)
        self.assertEqual(self.client.get("/api/game/route-leaderboard",params=dict(key=state["key"])).json()["board"],[])

    def test_teleport_paused_motion_dropped_updates_and_stale_sequence_rejected(self):
        player,state=self.start()
        self.assertEqual(self.progress(player,state,position=state["points"][-1]).status_code,400)
        state=self.progress(player,state,dt=0).json()
        self.assertEqual(self.progress(player,state,position=state["points"][-1],dt=.01).status_code,400)
        self.assertEqual(self.progress(player,state,position=Cube.point(3,3),dt=20).status_code,400)
        response=self.client.post(f"/api/game/route-attempts/{state['id']}/progress",json=dict(player,sequence=99,position=state["position"],mode="driving"))
        self.assertEqual(response.status_code,409)

    def test_pause_excludes_wall_time_and_repeated_packet_does_not_count_twice(self):
        player,state=self.start()
        state=self.progress(player,state,dt=0).json()
        state=self.progress(player,state,mode="paused",dt=2).json()
        self.assertEqual(state["active_drive_s"],2)
        self.clock+=100
        packet=dict(player,sequence=state["sequence"]+1,position=state["position"],mode="driving",samples=0)
        url=f"/api/game/route-attempts/{state['id']}/progress"
        first=self.client.post(url,json=packet)
        self.assertEqual(first.status_code,200,first.text)
        self.clock+=1
        self.assertEqual(self.client.post(url,json=packet).json(),first.json())
        self.assertEqual(first.json()["active_drive_s"],2)

    def test_paused_and_frozen_clock_packets_cannot_accumulate_roundoff_motion(self):
        player,state=self.start()
        anchor=state["position"].copy()
        deg_per_m=(Cube.e/Cube.W)/Cube.pixel_m[1]
        for mode in ("paused","driving"):
            state=self.progress(player,state,mode=mode,dt=0).json()
            for _ in range(20):
                small=dict(state["position"],lon=state["position"]["lon"]+.0004*deg_per_m)
                result=self.progress(player,state,position=small,mode=mode,dt=0)
                self.assertEqual(result.status_code,200,result.text)
                state=result.json()
                self.assertEqual(state["position"],anchor)
                self.assertEqual(state["active_drive_s"],0)
                self.assertFalse(state["visited_destination"])
            # The previous per-packet half-metre bonus allowed this indefinitely.
            moved=dict(anchor,lon=anchor["lon"]+.4*deg_per_m)
            self.assertEqual(self.progress(player,state,position=moved,mode=mode,dt=0).status_code,400)

    def test_tiny_positive_time_packets_have_no_per_packet_distance_bonus(self):
        player,state=self.start()
        state=self.progress(player,state,dt=0).json()
        start=state["position"].copy()
        deg_per_m=(Cube.e/Cube.W)/Cube.pixel_m[1]
        for _ in range(20):
            # 4cm / 1ms =40m/s: valid. The old +.5m bonus allowed 440m/s.
            moved=dict(state["position"],lon=state["position"]["lon"]+.04*deg_per_m)
            result=self.progress(player,state,position=moved,dt=.001)
            self.assertEqual(result.status_code,200,result.text)
            state=result.json()
            excess=dict(state["position"],lon=state["position"]["lon"]+.4*deg_per_m)
            self.assertEqual(self.progress(player,state,position=excess,dt=0).status_code,400)
        travelled=(state["position"]["lon"]-start["lon"])/deg_per_m
        self.assertAlmostEqual(travelled,.8,places=6)
        self.assertLessEqual(travelled,routes.MAX_DRIVE_M_S*state["active_drive_s"])

    def test_stationary_near_destination_does_not_complete_and_zero_route_unavailable(self):
        short=plan("nearby")
        first=short["candidates"][0]["route"]["points"][0]
        close=dict(first,lon=first["lon"]+10*(Cube.e/Cube.W)/Cube.pixel_m[1])
        short["candidates"][0]["route"]["points"]=[first,close]
        routes.capture_plan(short,self.cube)
        player=self.claim()
        start=self.client.post("/api/game/route-attempts",json=dict(player,plan_id="nearby",candidate=0,
            points=[first,close],idempotency_key="nearby-test"))
        self.assertEqual(start.status_code,200,start.text)
        state=self.progress(player,start.json(),dt=0).json()
        self.assertEqual(self.progress(player,state,dt=1,samples=1).status_code,400)
        self.assertFalse(state["visited_destination"])
        self.assertEqual(self.finish(player,state).status_code,400)
        zero=plan("zero-distance")
        zero["candidates"][0]["route"]["points"]=[first,first]
        routes.capture_plan(zero,self.cube)
        saved=self.get("zero-distance")
        self.assertFalse(saved["available"])
        self.assertEqual(saved["plan"]["id"],"zero-distance")

    def test_sample_claim_at_start_and_former_science_spot_before_b_rejected(self):
        player,state=self.start()
        state=self.progress(player,state,dt=0).json()
        premature=self.progress(player,state,dt=1,samples=1)
        self.assertEqual(premature.status_code,400,premature.text)
        self.assertIn("destination",premature.json()["detail"])
        unchanged=self.client.post(f"/api/game/route-attempts/{state['id']}/resume",json=player).json()
        self.assertEqual(unchanged["samples"],0)
        self.assertFalse(unchanged["visited_destination"])

        original=plan("science-along-route")
        site=Cube.point(3,4)
        original["candidates"][0]["card"]["sampling"]=[dict(site,what="clay")]
        routes.capture_plan(original,self.cube)
        result=self.client.post("/api/game/route-attempts",json=dict(player,plan_id=original["id"],candidate=0,
            idempotency_key="sample-at-original-site",points=original["candidates"][0]["route"]["points"]))
        self.assertEqual(result.status_code,200,result.text)
        state=self.progress(player,result.json(),dt=0).json()
        start=state["position"]
        for t in np.linspace(0,1,7)[1:]:
            position={k:start[k]+(site[k]-start[k])*float(t) for k in ("lat","lon")}
            response=self.progress(player,state,position=position,samples=0,dt=1)
            self.assertEqual(response.status_code,200,response.text)
            state=response.json()
        self.assertEqual(self.progress(player,state,samples=1,dt=1).status_code,400)
        self.assertEqual(state["samples"],0)
        self.assertFalse(state["visited_destination"])
        self.assertEqual(self.finish(player,state).status_code,400)

    def test_finish_persists_ties_and_ignores_driving_speed_for_rank(self):
        one,first=self.start()
        first=self.drive_to_objective(one,first,1)
        response=self.finish(one,first)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.finish(one,first).json(),response.json())
        two,second=self.start(self.claim("PilotTwo"))
        second=self.drive_to_objective(two,second,2)
        response=self.finish(two,second)
        self.assertEqual(response.status_code,200,response.text)
        routes._conn.close();routes._conn=None
        board=self.client.get("/api/game/route-leaderboard",params=dict(key=first["key"])).json()
        self.assertEqual(board["players"],2)
        self.assertEqual([entry["rank"] for entry in board["board"]],[1,1])
        self.assertNotEqual(board["board"][0]["actual_driving_time_s"],board["board"][1]["actual_driving_time_s"])
        self.assertEqual(board["board"][0]["ai_driving_time_s"],40)
        self.assertEqual(board["board"][0]["ai_driving_time_s"],board["board"][1]["ai_driving_time_s"])

    def test_one_destination_sample_finishes_without_return_and_freezes_clock(self):
        player,state=self.start()
        state=self.drive_to_objective(player,state,sample=False)
        self.assertTrue(state["visited_destination"])
        self.assertEqual(self.finish(player,state).status_code,400)  # Arrival alone is not science.
        state=self.progress(player,state,mode="paused",dt=0).json()
        driving=state["active_drive_s"]
        response=self.progress(player,state,mode="paused",samples=1,dt=30)
        self.assertEqual(response.status_code,200,response.text)
        complete=response.json()
        self.assertTrue(complete["objective_complete"])
        for coordinate in ("lat","lon"):
            self.assertAlmostEqual(complete["position"][coordinate],complete["points"][-1][coordinate],places=8)
        self.assertEqual(complete["mode"],"paused")
        self.assertEqual(complete["active_drive_s"],driving)
        # The exact completion packet can be retried after a lost response.
        duplicate=dict(player,sequence=complete["sequence"],position=complete["position"],mode="paused",samples=1)
        url=f"/api/game/route-attempts/{complete['id']}/progress"
        self.assertEqual(self.client.post(url,json=duplicate).json(),complete)
        self.assertEqual(self.progress(player,complete,samples=1,dt=10).status_code,409)
        moved=dict(complete["position"],lon=complete["position"]["lon"]-.0001)
        self.assertEqual(self.progress(player,complete,position=moved,mode="paused",samples=1,dt=10).status_code,400)
        self.assertEqual(self.progress(player,complete,mode="paused",samples=2).status_code,422)
        final=self.progress(player,complete,mode="paused",samples=1,dt=10)
        self.assertEqual(final.status_code,200,final.text)
        self.assertEqual(final.json()["active_drive_s"],driving)
        response=self.finish(player,final.json())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["status"],"finished")
        self.assertEqual(response.json()["position"],complete["position"])

    def test_old_round_trip_attempts_cannot_join_single_site_scores(self):
        with patch.object(routes,"MODEL_VERSION","planner-route-comparison-v1"):
            player,old=self.start()
        self.assertNotEqual(self.get()["key"],old["key"])
        for path in ("resume","finish"):
            response=self.client.post(f"/api/game/route-attempts/{old['id']}/{path}",json=self.finish_body(player,old) if path=="finish" else player)
            self.assertEqual(response.status_code,409,response.text)
            self.assertIn("previous mission format",response.json()["detail"])
        self.assertEqual(self.progress(player,old).status_code,409)
        duplicate=self.client.post("/api/game/route-attempts",json=dict(player,plan_id="original",candidate=0,
            points=old["points"],idempotency_key="attempt-one"))
        self.assertEqual(duplicate.status_code,409)
        retired=self.client.post(f"/api/game/route-attempts/{old['id']}/restart",json=player)
        self.assertEqual(retired.status_code,200,retired.text)
        self.assertEqual(retired.json()["status"],"invalidated")
        old_board=self.client.get("/api/game/route-leaderboard",params=dict(key=old["key"])).json()
        self.assertEqual(old_board["board"],[])
        self.assertIsNone(old_board["reference_metrics"])
        _,fresh=self.start(player,key="single-site-new")
        self.assertEqual(fresh["model_version"],routes.MODEL_VERSION)

    def test_saved_plan_from_previous_version_can_start_new_single_site_attempt(self):
        with patch.object(routes,"MODEL_VERSION","planner-route-comparison-v1"):
            routes.capture_plan(plan("previously-saved"),self.cube)
        record,_=routes._plan("previously-saved")
        terrain=routes._terrain(record["terrain"])
        self.assertEqual(terrain["metadata"]["model_version"],"planner-route-comparison-v1")
        terrain.pop("firmness")  # This display array was absent from old saved terrain.
        saved=self.get("previously-saved")
        self.assertTrue(saved["available"],saved.get("reason"))
        metrics=saved["reference"]["metrics"]
        self.assertEqual(metrics["simulated_time_s"],metrics["one_way_time_s"])
        response=self.client.post("/api/game/route-attempts",json=dict(self.claim(),plan_id="previously-saved",candidate=0,
            points=saved["reference"]["points"],idempotency_key="new-run-old-plan"))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["model_version"],routes.MODEL_VERSION)
        self.assertEqual(response.json()["metrics"],metrics)

    def test_new_route_invalidates_attempt_and_resume_stays_paused(self):
        player,first=self.start()
        _,same=self.start(player)
        self.assertEqual(first["id"],same["id"])
        _,second=self.start(player,key="attempt-two",points=[Cube.point(3,2),Cube.point(2,4),Cube.point(3,6)])
        self.assertEqual(self.finish(player,first).status_code,409)
        restored=self.client.post(f"/api/game/route-attempts/{second['id']}/resume",json=player).json()
        self.assertEqual(restored["mode"],"paused")
        self.assertEqual(restored["points"],second["points"])
        wrong=self.client.post("/api/game/route-attempts",json=dict(player,plan_id="original",candidate=0,idempotency_key="attempt-two",points=first["points"]))
        self.assertEqual(wrong.status_code,409)

    def test_finish_receipt_rank_is_not_limited_to_first_hundred_players(self):
        player,state=self.start(self.claim("ZzzPilot"))
        state=self.drive_to_objective(player,state)
        # Completed-score fixtures exercise pagination without simulating 101
        # additional games. The submitting player still completes through APIs.
        with routes._write() as db:
            row=db.execute("SELECT * FROM attempts WHERE id=?",(state["id"],)).fetchone()
            completed=json.loads(row["state"])
            completed.update(status="finished",mode="paused",ai_drive_ticks=1200,benchmark_version=routes.BENCHMARK_VERSION)
            for i in range(101):
                name=f"Other{i:03d}"
                db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)",
                           (name,name.lower(),name,row["plan_id"],row["candidate"],row["mission_key"],
                            "fixture-"+name,row["payload"],routes._json(completed)))
        finished=self.finish(player,state)
        self.assertEqual(finished.status_code,200,finished.text)
        self.assertEqual(finished.json()["rank"],1)
        with routes._write() as db:
            for row in db.execute("SELECT id,state FROM attempts WHERE name_lc LIKE 'other%'").fetchall():
                completed=json.loads(row["state"])
                completed["ai_drive_ticks"]-=30
                db.execute("UPDATE attempts SET state=? WHERE id=?",(routes._json(completed),row["id"]))
        _,second=self.start(player,key="after-first-hundred")
        second=self.drive_to_objective(player,second)
        finished=self.finish(player,second)
        self.assertEqual(finished.status_code,200,finished.text)
        self.assertEqual(finished.json()["rank"],102)
        public=self.client.get("/api/game/route-leaderboard",params=dict(key=state["key"],limit=100)).json()
        self.assertEqual(public["players"],102)
        self.assertEqual(len(public["board"]),100)

    def test_guest_can_choose_callsign_after_sampling_without_signup_before_play(self):
        guest=self.client.post('/api/game/route-guests',json={}).json()
        self.assertEqual(self.client.get('/api/game/leaderboard').json()['players'],0)
        _,state=self.start(guest)
        player=self.claim('AfterLanding')
        claim_url=f"/api/game/route-attempts/{state['id']}/claim"
        body=dict(player,guest_token=guest['token'])
        self.assertEqual(self.client.post(claim_url,json=body).status_code,400)
        self.assertEqual(self.progress(dict(guest,token='wrong-secret'),state).status_code,403)
        state=self.drive_to_objective(guest,state)
        self.assertEqual(self.finish(guest,state).status_code,400)
        self.assertEqual(self.client.post(claim_url,json=dict(body,guest_token='wrong-secret')).status_code,403)
        claimed=self.client.post(claim_url,json=body)
        self.assertEqual(claimed.status_code,200,claimed.text)
        self.assertEqual(self.client.post(claim_url,json=body).json(),claimed.json())
        self.assertEqual(self.finish(guest,state).status_code,400)
        self.assertEqual(self.finish(self.claim('ThiefPilot'),state).status_code,403)
        result=self.finish(player,claimed.json(),ticks=901)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['ai_drive_ticks'],901)
        self.assertAlmostEqual(result.json()['ai_driving_time_s'],901/30,places=6)
        self.assertEqual(self.finish(player,claimed.json(),ticks=1).json(),result.json(),'A retry cannot replace a recorded AI time')
        board=self.client.get('/api/game/route-leaderboard',params={'key':state['key']}).json()['board']
        self.assertEqual([r['name'] for r in board],['AfterLanding'])

    def test_ranking_uses_ai_ticks_even_when_player_driving_order_is_opposite(self):
        fast,first=self.start(self.claim('FastPlayer'))
        first=self.drive_to_objective(fast,first,dt=1)
        self.assertEqual(self.finish(fast,first,ticks=1500).status_code,200)
        slow,second=self.start(self.claim('SlowPlayer'))
        second=self.drive_to_objective(slow,second,dt=2)
        self.assertEqual(self.finish(slow,second,ticks=900).status_code,200)
        self.assertEqual(first['metrics'],second['metrics'],'The planner estimates are identical')
        board=self.client.get('/api/game/route-leaderboard',params={'key':first['key']}).json()['board']
        self.assertEqual([r['name'] for r in board],['SlowPlayer','FastPlayer'])
        self.assertEqual([r['ai_driving_time_s'] for r in board],[30,50])
        self.assertGreater(board[0]['actual_driving_time_s'],board[1]['actual_driving_time_s'])

    def test_ai_result_requires_valid_ticks_version_and_the_locked_route(self):
        player,state=self.start()
        state=self.drive_to_objective(player,state)
        endpoint=f"/api/game/route-attempts/{state['id']}/finish"
        body=self.finish_body(player,state)
        for ticks in (0,-1,1.5,True,54001):
            self.assertEqual(self.client.post(endpoint,json=dict(body,ai_drive_ticks=ticks)).status_code,422)
        self.assertEqual(self.client.post(endpoint,json=dict(body,benchmark_version='old')).status_code,422)
        self.assertEqual(self.client.post(endpoint,json=dict(body,route_hash='0'*64)).status_code,409)
        self.assertEqual(self.client.post(endpoint,json=body).status_code,200)

    def test_board_separates_difficulty_and_driving_mode(self):
        player,state=self.start()
        state=self.drive_to_objective(player,state)
        self.assertEqual(self.finish(player,state).status_code,200)
        query=dict(key=self.get()['key'],difficulty='astronaut',driving_mode='3d')
        self.assertEqual(self.client.get('/api/game/route-leaderboard',params=query).json()['players'],1)
        for change in ({'difficulty':'cadet'},{'driving_mode':'2d'}):
            self.assertEqual(self.client.get('/api/game/route-leaderboard',params=dict(query,**change)).json()['board'],[])


if __name__=="__main__":
    unittest.main()
