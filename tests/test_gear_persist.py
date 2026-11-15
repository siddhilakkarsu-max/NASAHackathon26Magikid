"""The published kit survives a server restart: saved to disk on publish, restored on load."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gear_state  # noqa: E402,F401  (before gear: keeps the real state file untouched)
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from gear import tools  # noqa: E402

ENV = "MARSWALK_GEAR_STATE_DIR"
PUBLISH = {"context": {"archetype": "traverse"}, "publish": True, "note": "x"}


class Persist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gear_server import server
        cls.c = TestClient(server)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gear_state_")
        self.old_env = os.environ.get(ENV)
        self.old_published = dict(tools.PUBLISHED)
        os.environ[ENV] = os.path.join(self.tmp, "state")
        tools.PUBLISHED.update(manifest=None, published_at=None, note=None, source=None)

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = self.old_env
        tools.PUBLISHED.clear()
        tools.PUBLISHED.update(self.old_published)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def restart(self):
        tools.PUBLISHED.update(manifest=None, published_at=None, note=None, source=None)
        tools.load_published()

    def test_state_path_follows_env(self):
        self.assertEqual(tools.state_path(), Path(self.tmp) / "state" / "published_kit.json")

    def test_publish_writes_the_file(self):
        r = tools.call_tool("recommend_gear", PUBLISH)
        self.assertNotIn("error", r, r)
        path = tools.state_path()
        self.assertTrue(path.is_file())
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["note"], "x")
        self.assertEqual(saved["manifest"]["context"]["archetype"], "traverse")
        self.assertEqual(saved["published_at"], tools.PUBLISHED["published_at"])
        self.assertEqual([p.name for p in path.parent.iterdir()], ["published_kit.json"])  # no temp files left

    def test_restart_restores_the_kit_from_disk(self):
        tools.call_tool("recommend_gear", PUBLISH)
        before = self.c.get("/api/gear/published").json()
        self.assertEqual(before["source"], "memory")
        self.restart()
        after = self.c.get("/api/gear/published").json()
        self.assertEqual(after["source"], "disk")
        self.assertEqual(after["note"], "x")
        self.assertEqual(after["published_at"], before["published_at"])
        self.assertEqual(after["manifest"], before["manifest"])

    def test_numpy_values_round_trip(self):
        tools._publish({"context": {"archetype": "t"}, "o2": np.float64(1.5), "n": np.int64(3),
                        "v": np.array([1.0, 2.0])}, "np")
        self.restart()
        m = tools.PUBLISHED["manifest"]
        self.assertEqual((m["o2"], m["n"], m["v"]), (1.5, 3, [1.0, 2.0]))
        self.assertIsInstance(m["o2"], float)
        self.assertEqual(self.c.get("/api/gear/published").json()["manifest"]["o2"], 1.5)

    def test_missing_empty_or_corrupt_file_means_nothing_published(self):
        path = tools.state_path()
        self.restart()  # missing
        self.assertIsNone(tools.PUBLISHED["manifest"])
        path.parent.mkdir(parents=True)
        for text in ("", "{not json", "[1, 2]", '{"manifest": "nope"}'):
            path.write_text(text, encoding="utf-8")
            if text.startswith("{not"):
                with self.assertLogs("gear.tools", level="WARNING"):
                    self.restart()
            else:
                self.restart()
            p = self.c.get("/api/gear/published")
            self.assertEqual(p.status_code, 200)
            self.assertIsNone(p.json()["manifest"], text)
            self.assertIsNone(p.json()["source"], text)

    def test_delete_clears_memory_and_file(self):
        tools.call_tool("recommend_gear", PUBLISH)
        self.assertTrue(tools.state_path().is_file())
        d = self.c.delete("/api/gear/published")
        self.assertEqual(d.status_code, 200)
        self.assertEqual(d.json(), {"manifest": None, "published_at": None, "note": None, "source": None})
        self.assertFalse(tools.state_path().exists())
        self.restart()
        self.assertIsNone(self.c.get("/api/gear/published").json()["manifest"])
        self.assertEqual(self.c.delete("/api/gear/published").status_code, 200)  # deleting twice is fine

    def test_unwritable_path_does_not_break_publishing(self):
        blocker = Path(self.tmp) / "a_file"
        blocker.write_text("not a folder", encoding="utf-8")
        os.environ[ENV] = str(blocker / "state")
        with self.assertLogs("gear.tools", level="WARNING"):
            r = tools.call_tool("recommend_gear", PUBLISH)
        self.assertNotIn("error", r, r)
        self.assertTrue(r["published"])
        self.assertEqual(tools.PUBLISHED["note"], "x")
        self.assertEqual(self.c.get("/api/gear/published").json()["source"], "memory")

    def test_agent_tool_list_is_unchanged(self):
        self.assertEqual(len(tools.tool_specs()), 8)


if __name__ == "__main__":
    unittest.main()
