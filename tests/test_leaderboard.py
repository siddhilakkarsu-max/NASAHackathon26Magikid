"""
Game leaderboard and callsigns (leaderboard.py): claim a callsign, post scores with its token, read the boards.
Uses a temporary state folder, never the real game_state/.

    python -m unittest tests.test_leaderboard
"""
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import gear_server  # noqa: E402
import leaderboard  # noqa: E402

MISSION = "olivine|on_foot|northern_summer|safety|r1"


class LeaderboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("MARSWALK_GAME_STATE_DIR")
        os.environ["MARSWALK_GAME_STATE_DIR"] = self.tmp.name
        self.pause = leaderboard.MIN_SECONDS_BETWEEN_SCORES
        leaderboard.MIN_SECONDS_BETWEEN_SCORES = 0
        self.client = TestClient(gear_server.server)

    def tearDown(self):
        leaderboard.MIN_SECONDS_BETWEEN_SCORES = self.pause
        if leaderboard._conn is not None:
            leaderboard._conn.close()
            leaderboard._conn = None
        if self.old is None:
            os.environ.pop("MARSWALK_GAME_STATE_DIR", None)
        else:
            os.environ["MARSWALK_GAME_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def claim(self, name):
        r = self.client.post("/api/game/players", json={"name": name})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def score(self, player, value, mission=MISSION, **extra):
        body = dict(name=player["name"], token=player["token"], mission=mission, goal="olivine",
                    vehicle="Astronaut on foot (suited)", route=1, difficulty="Astronaut", score=value,
                    grade="A", met_h=2.5, samples=3)
        body.update(extra)
        return self.client.post("/api/game/scores", json=body)

    def test_claim_and_duplicate(self):
        p = self.claim("Ares One")
        self.assertEqual(p["name"], "Ares One")
        self.assertGreater(len(p["token"]), 20)
        self.assertEqual(self.client.post("/api/game/players", json={"name": "ares one"}).status_code, 409)

    def test_bad_names(self):
        for name in ("ab", "x" * 17, "<script>", "Houston", " ", "bad!name", "-dash"):
            self.assertEqual(self.client.post("/api/game/players", json={"name": name}).status_code, 400, name)

    def test_score_needs_the_right_token(self):
        p = self.claim("Pilot1")
        self.assertEqual(self.score({"name": "Pilot1", "token": "wrong-token-123"}, 90).status_code, 403)
        self.assertEqual(self.score({"name": "Nobody", "token": p["token"]}, 90).status_code, 404)
        self.assertEqual(self.score(p, 90).status_code, 200)

    def test_score_ranges(self):
        p = self.claim("Pilot2")
        self.assertEqual(self.score(p, 101).status_code, 422)
        self.assertEqual(self.score(p, -1).status_code, 422)
        self.assertEqual(self.score(p, 80, grade="Z").status_code, 400)

    def test_rate_limit(self):
        p = self.claim("Pilot3")
        leaderboard.MIN_SECONDS_BETWEEN_SCORES = 60
        self.assertEqual(self.score(p, 70).status_code, 200)
        self.assertEqual(self.score(p, 71).status_code, 429)

    def test_boards_rank_best_run_per_player(self):
        a, b = self.claim("Alpha"), self.claim("Bravo")
        self.score(a, 70)
        r = self.score(a, 88).json()
        self.assertTrue(r["improved"])
        self.assertEqual((r["rank"], r["best"]), (1, 88.0))
        self.assertFalse(self.score(a, 60).json()["improved"])
        r = self.score(b, 95).json()
        self.assertEqual(r["rank"], 1)
        board = self.client.get("/api/game/leaderboard", params={"mission": MISSION}).json()
        self.assertEqual([(x["name"], x["score"]) for x in board["board"]], [("Bravo", 95.0), ("Alpha", 88.0)])
        self.assertEqual(board["players"], 2)
        self.score(a, 50, mission="ridge|four_wheel|northern_autumn|safety|r1")
        overall = self.client.get("/api/game/leaderboard").json()["board"]
        self.assertEqual([(x["name"], x["points"], x["missions"]) for x in overall],
                         [("Alpha", 138.0, 2), ("Bravo", 95.0, 1)])

    def test_state_survives_reopening(self):
        p = self.claim("Keeper")
        self.score(p, 77)
        leaderboard._conn.close()
        leaderboard._conn = None
        board = self.client.get("/api/game/leaderboard", params={"mission": MISSION}).json()["board"]
        self.assertEqual(board[0]["name"], "Keeper")
        self.assertTrue((Path(self.tmp.name) / "leaderboard.sqlite3").exists())

    def test_database_is_shared_with_a_new_application_process(self):
        player=self.claim("PersistentPilot")
        self.assertEqual(self.score(player,83).status_code,200)
        result=subprocess.run([sys.executable,"-c",
            "import json,leaderboard; print(json.dumps(leaderboard.leaderboard(mission='',limit=20)))"],
            cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        board=json.loads(result.stdout)["board"]
        self.assertEqual(board[0]["name"],"PersistentPilot")
        self.assertEqual(board[0]["points"],83)


if __name__ == "__main__":
    unittest.main()
