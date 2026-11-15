"""
Tests for the pinned-kit comparison on the gear page (frontend/kit-compare.js).

The diff logic runs under node when node is on PATH; otherwise that part is skipped.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

NODE_SCRIPT = """
const { compareKits, kitLabel } = require(process.argv[2]);
const fs = require("fs");
const a = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const b = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
console.log(JSON.stringify({ diff: compareKits(a, b), self: compareKits(a, a), label: kitLabel(a) }));
"""


class KitComparePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gear_server import server
        cls.c = TestClient(server)

    def test_page_loads_compare_files(self):
        html = self.c.get("/kit.html").text
        self.assertIn('src="kit-compare.js"', html)
        self.assertIn('href="kit-compare.css"', html)
        for f in ("/kit-compare.js", "/kit-compare.css"):
            self.assertEqual(self.c.get(f).status_code, 200, f)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_compare_kits_short_vs_long_stay(self):
        kits = {}
        for arch in ("short_stay", "long_stay"):
            r = self.c.post("/api/gear/kit", json={"context": {"archetype": arch}})
            self.assertEqual(r.status_code, 200)
            kits[arch] = r.json()
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, m in (("a.json", kits["short_stay"]), ("b.json", kits["long_stay"])):
                p = Path(tmp) / name
                p.write_text(json.dumps(m), encoding="utf-8")
                paths.append(str(p))
            script = Path(tmp) / "run.js"
            script.write_text(NODE_SCRIPT, encoding="utf-8")
            out = subprocess.run([shutil.which("node"), str(script), str(ROOT / "frontend" / "kit-compare.js"), *paths],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        res = json.loads(out.stdout)
        d = res["diff"]
        self.assertFalse(d["same"])
        self.assertTrue(d["added"], "long stay should add items")
        self.assertTrue(d["removed"] or d["qty"], "short stay items should be removed or change quantity")
        a_ids = {i["id"] for i in kits["short_stay"]["items"]}
        b_ids = {i["id"] for i in kits["long_stay"]["items"]}
        self.assertEqual({i["id"] for i in d["added"]}, b_ids - a_ids)
        self.assertEqual({i["id"] for i in d["removed"]}, a_ids - b_ids)
        items = next(f for f in d["figures"] if f["key"] == "items")
        self.assertEqual(items["pinned"], kits["short_stay"]["summary"]["items"])
        self.assertEqual(items["now"], kits["long_stay"]["summary"]["items"])
        self.assertTrue(items["changed"])
        self.assertTrue(res["self"]["same"])
        self.assertIn(kits["short_stay"]["context"]["archetype_label"], res["label"])


if __name__ == "__main__":
    unittest.main()
