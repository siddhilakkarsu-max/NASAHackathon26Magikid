"""Cache regressions: a new document must not reuse incompatible old scripts."""
import hashlib
import html
from pathlib import Path
import re
import tempfile
import unittest

from starlette.applications import Starlette
from starlette.testclient import TestClient
from frontend_delivery import VersionedFrontend


class FrontendDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'index.html').write_text('<script src="/light.js"></script><link rel="stylesheet" href="theme.css">')
        (self.root / 'light.js').write_text('window.version = 1;')
        (self.root / 'theme.css').write_text('body { color: red; }')
        app = Starlette()
        app.mount('/', VersionedFrontend(directory=self.root, html=True))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_local_assets_have_content_versions_and_revalidate(self):
        document = self.client.get('/')
        self.assertEqual(document.headers['cache-control'], 'no-cache')
        for filename in ['light.js', 'theme.css']:
            digest = hashlib.sha256((self.root / filename).read_bytes()).hexdigest()[:16]
            self.assertIn(filename + '?v=' + digest, document.text)
            code = self.client.get('/' + filename + '?v=' + digest)
            self.assertEqual(code.status_code, 200)
            self.assertEqual(code.headers['cache-control'], 'no-cache')
            cached = self.client.get('/' + filename + '?v=' + digest, headers={'If-None-Match': code.headers['etag']})
            self.assertEqual(cached.status_code, 304)
            self.assertEqual(cached.headers['cache-control'], 'no-cache')

    def test_script_only_update_changes_document_etag_and_url(self):
        old = self.client.get('/')
        previous_mtime = (self.root / 'index.html').stat().st_mtime_ns
        (self.root / 'light.js').write_text('window.version = 2;')
        updated = self.client.get('/', headers={'If-None-Match': old.headers['etag']})
        self.assertEqual(updated.status_code, 200)
        self.assertNotEqual(old.headers['etag'], updated.headers['etag'])
        self.assertNotEqual(old.text, updated.text)
        self.assertEqual(previous_mtime, (self.root / 'index.html').stat().st_mtime_ns)
        self.assertEqual(self.client.get('/', headers={'If-None-Match': 'W/' + updated.headers['etag']}).status_code, 304)

    def test_head_and_conditional_html_keep_correct_metadata(self):
        document = self.client.get('/index.html')
        head = self.client.head('/')
        self.assertEqual(head.content, b'')
        self.assertEqual(head.headers['content-length'], str(len(document.content)))
        self.assertEqual(head.headers['etag'], document.headers['etag'])
        cached = self.client.get('/', headers={'If-None-Match': document.headers['etag']})
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b'')
        self.assertEqual(cached.headers['cache-control'], 'no-cache')
        # A timestamp alone cannot prove that this HTML's dependencies match.
        self.assertEqual(self.client.get('/', headers={'If-Modified-Since': 'Sun, 15 Nov 2099 00:00:00 GMT'}).status_code, 200)

    def test_nested_relative_paths_queries_and_external_links(self):
        folder = self.root / 'guide'; folder.mkdir()
        (folder / 'index.html').write_text('''<script defer src='../light.js?mode=one&amp;v=old#anchor'></script>
<link href="https://example.org/theme.css" rel="stylesheet">
<script src="//example.org/script.js"></script><script src="/missing.js"></script>''')
        response = self.client.get('/guide/')
        reference = html.unescape(re.search("src='([^']+)'", response.text)[1])
        self.assertRegex(reference, r'^\.\./light.js\?mode=one&v=[a-f0-9]{16}#anchor$')
        self.assertIn('https://example.org/theme.css', response.text)
        self.assertIn('//example.org/script.js', response.text)
        self.assertIn('src="/missing.js"', response.text)

    def test_large_assets_keep_normal_cache_and_range_behavior(self):
        (self.root / 'model.glb').write_bytes(b'0123456789')
        response = self.client.get('/model.glb', headers={'Range': 'bytes=2-5'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b'2345')
        self.assertNotIn('cache-control', response.headers)

    def test_unsafe_paths_are_not_fingerprinted_or_served(self):
        (self.root / 'index.html').write_text('<script src="/../../outside.js"></script>')
        self.assertNotIn('?v=', self.client.get('/').text)
        self.assertEqual(self.client.get('/%2e%2e/outside.js').status_code, 404)
