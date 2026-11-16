"""A plan must never leave the page waiting forever, and loaded areas must not eat the server's memory."""
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gear_state  # noqa: E402,F401  (before gear: keeps the real state file untouched)
from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402

REQ = {"region": "jezero", "goal": "sample clay near the delta", "vehicle": "on_foot", "ls": 90, "local_hour": 11}


def stream(client):
    with client.stream("POST", "/api/mission/stream", json=REQ) as r:
        return r.status_code, r.read().decode()


class PlanStream(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)

    def test_unexpected_failure_becomes_an_error_event(self):
        with patch.object(app.mission, "plan", side_effect=RuntimeError("boom")):
            code, body = stream(self.client)
        self.assertEqual(code, 200)
        self.assertIn('"type": "error"', body)
        self.assertIn("RuntimeError: boom", body)

    def test_slow_planning_sends_keepalives(self):
        def slow(*a, **k):
            time.sleep(0.35)
            raise ValueError("no cube data")             # ends the plan quickly after the wait
        with patch.object(app, "STREAM_KEEPALIVE_S", 0.1), patch.object(app.mission, "plan", side_effect=slow):
            _, body = stream(self.client)
        self.assertIn(": working", body)
        self.assertIn('"type": "error"', body)


class AreaBuilds(unittest.TestCase):
    def test_a_stuck_build_is_stopped_and_reported(self):
        region = "site_1_2"
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        log = ROOT / "cubes" / ".build_test_stuck.log"
        log.write_text("STAGE layers 5\n")
        try:
            with patch.dict(app._builds, {region: {"proc": proc, "log": log, "started": time.time() - 400}}):
                st = app._build_status(region)
            self.assertEqual(st["status"], "failed")
            self.assertIsNotNone(proc.poll())                # the process was ended
            self.assertIn("took longer", st["log"][-1])
        finally:
            proc.kill(); log.unlink(missing_ok=True)

    def test_loaded_area_keeps_one_array_for_all_bands(self):
        cube = app.Cube("jezero")
        bases = {id(b.base) for b in cube.bands.values()}
        self.assertEqual(len(bases), 1)                       # not one full copy per band (20× the memory)


if __name__ == "__main__":
    unittest.main()
