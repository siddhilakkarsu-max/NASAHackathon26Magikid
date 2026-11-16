"""Cloudflare Pages build (tools/build_pages.py): every page gets the server shim first, assets are versioned."""
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import build_pages  # noqa: E402

API = "https://100-20-2-83.sslip.io"


class BuildPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "dist"
        cls.info = build_pages.build(API, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_page_runs_the_shim_first_with_the_server_address(self):
        pages = sorted(self.out.rglob("*.html"))
        self.assertGreaterEqual(len(pages), 3)
        for page in pages:
            text = page.read_text(encoding="utf-8")
            first_script = text.lower().index("<script")
            self.assertIn("window.MARSWALK_API", text[first_script:first_script + 4000], page.name)
            self.assertIn(f'var API = "{API}"', text)
            self.assertNotIn("__MARSWALK_API__", text)
            charset = re.search(r"<meta\s+charset", text, re.I)
            if charset:
                self.assertLess(charset.start(), first_script, f"{page.name}: <meta charset> must stay first")

    def test_local_scripts_are_versioned_and_server_links_point_at_the_server(self):
        index = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertRegex(index, r'src="/maps_ui\.js\?v=[0-9a-f]{16}"')
        self.assertNotRegex(index, r'href="/api/')
        self.assertIn(f'href="{API}/api/weather/sources"', index)

    def test_files_and_metadata(self):
        self.assertTrue((self.out / "vendor" / "Cesium" / "Cesium.js").is_file())
        self.assertFalse(list(self.out.rglob(".DS_Store")))
        self.assertIn("/*.html", (self.out / "_headers").read_text())
        self.assertEqual(self.info["api"], API)
        self.assertLess(max(p.stat().st_size for p in self.out.rglob("*") if p.is_file()), 25 * 2**20)  # Pages limit

    def test_rebuild_replaces_only_its_own_output(self):
        build_pages.build(API, self.out)                         # a previous build is replaced
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "keep.txt").write_text("not a build")
            with self.assertRaises(SystemExit):
                build_pages.build(API, Path(other))
            self.assertTrue((Path(other) / "keep.txt").exists())

    def test_server_address_checks(self):
        self.assertEqual(build_pages.check_api(API + "/"), API)
        self.assertEqual(build_pages.check_api("http://127.0.0.1:8000"), "http://127.0.0.1:8000")
        for bad in ("http://100-20-2-83.sslip.io", "ftp://x", API + "/api", API + "?a=1", "not a url"):
            with self.assertRaises(SystemExit, msg=bad):
                build_pages.check_api(bad)


if __name__ == "__main__":
    unittest.main()
