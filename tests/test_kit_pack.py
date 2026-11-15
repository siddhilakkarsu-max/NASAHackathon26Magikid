"""
Tests for the gear page's packing list, CSV export and share link (frontend/kit-pack.js).
The JavaScript parts run under node when it is on PATH and are skipped otherwise.
"""
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

PACK_JS = ROOT / "frontend" / "kit-pack.js"
NODE = shutil.which("node")


def run_node(script, *args):
    out = subprocess.run([NODE, "-e", script, str(PACK_JS), *map(str, args)], capture_output=True, timeout=60)
    if out.returncode:
        raise AssertionError(out.stderr.decode("utf-8", "replace"))
    return out.stdout


class KitPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gear_server import server
        cls.c = TestClient(server)

    def test_page_loads_the_pack_files(self):
        html = self.c.get("/kit.html").text
        self.assertRegex(html, r'src="kit-pack\.js(?:\?v=[a-f0-9]{16})?"')
        self.assertRegex(html, r'href="kit-pack\.css(?:\?v=[a-f0-9]{16})?"')
        self.assertRegex(html, r'src="kit\.js(?:\?v=[a-f0-9]{16})?"')
        self.assertLess(html.index('src="kit.js'), html.index('src="kit-pack.js'))
        self.assertEqual(self.c.get("/kit-pack.js").status_code, 200)
        self.assertEqual(self.c.get("/kit-pack.css").status_code, 200)

    @unittest.skipUnless(NODE, "node is not on PATH")
    def test_csv_round_trips(self):
        m = self.c.post("/api/gear/kit", json={"context": {"archetype": "long_stay"}}).json()
        tricky = 'Sample bag, "sterile"\nlarge'
        m["groups"][0]["items"][0]["name"] = tricky
        n = sum(len(g["items"]) for g in m["groups"])
        self.assertEqual(n, len(m["items"]))
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "kit.json"
            src.write_text(json.dumps(m), encoding="utf-8")
            raw = run_node(
                "const p=require(process.argv[1]);const m=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));"
                "process.stdout.write(Buffer.from(p.kitToCsv(m),'utf8'))", src)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM")
        text = raw.decode("utf-8-sig")
        self.assertTrue(text.endswith("\r\n"))
        self.assertEqual(len(re.findall(r"(?<!\r)\n", text)), 1, "only the LF inside the quoted name is bare")
        self.assertEqual(text.count("\r\n"), n + 1)
        rows = list(csv.reader(io.StringIO(text, newline="")))
        self.assertEqual(rows[0], ["category", "item", "qty", "priority", "carried_by", "unit_mass_kg", "total_mass_kg",
                                   "evidence", "rules", "sources", "note"])
        self.assertEqual(len(rows) - 1, n)
        first = m["groups"][0]["items"][0]
        self.assertEqual(rows[1][1], tricky)
        self.assertEqual(rows[1][0], first["category_label"])
        self.assertEqual(rows[1][2], str(first["qty"]))
        self.assertEqual(rows[1][7], first["confidence"]["tag"])
        self.assertEqual(rows[1][8], " ".join(first["rules"]))
        self.assertEqual(rows[1][9], " | ".join(s["title"] for s in first["sources"]))
        names = {r[1] for r in rows[1:]}
        for it in m["items"][1:]:
            self.assertIn(it["name"], names)

    @unittest.skipUnless(NODE, "node is not on PATH")
    def test_share_url_and_signature(self):
        form = {"archetype": "long_stay", "crew": "4", "stay": "500", "useRoute": True, "region": "jezero",
                "vehicle": "astronaut", "baseLat": "18.4447", "baseLon": "77.4508", "targetLat": "18.5", "targetLon": "77.4",
                "hour": "11", "budget": "8", "ls": "250"}
        out = run_node(
            "const p=require(process.argv[1]);const f=JSON.parse(process.argv[2]);"
            "const m={context:{archetype:'x'},items:[{id:'b',qty:2},{id:'a',qty:1}]};"
            "const m2={context:{archetype:'x'},items:[{id:'a',qty:1},{id:'b',qty:2}]};"
            "const m3={context:{archetype:'x'},items:[{id:'a',qty:1},{id:'b',qty:3}]};"
            "console.log(JSON.stringify({pub:p.buildShareUrl(f,'published'),build:p.buildShareUrl(Object.assign({},f,{useRoute:false,ls:''}),'build'),"
            "s1:p.kitSignature(m),s2:p.kitSignature(m2),s3:p.kitSignature(m3)}))", json.dumps(form))
        r = json.loads(out)
        self.assertTrue(r["pub"].startswith("kit.html?"))
        for part in ("archetype=long_stay", "crew=4", "stay=500", "region=jezero", "vehicle=astronaut", "base=18.4447,77.4508",
                     "target=18.5,77.4", "hour=11", "budget=8", "ls=250", "tab=published"):
            self.assertIn(part, r["pub"])
        self.assertEqual(r["build"], "kit.html?archetype=long_stay&crew=4&stay=500")
        self.assertEqual(r["s1"], r["s2"])
        self.assertNotEqual(r["s1"], r["s3"])
        self.assertTrue(r["s1"].startswith("x-"))


if __name__ == "__main__":
    unittest.main()
