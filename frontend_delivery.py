"""Serve matching frontend modules after an update, including in warm browsers."""
import hashlib
import html
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from starlette.datastructures import Headers
from starlette.responses import HTMLResponse
from starlette.staticfiles import NotModifiedResponse, StaticFiles


ASSET_REFERENCE = re.compile(
    r'(?P<prefix><(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*)'
    r'(?P<quote>[\"\x27])(?P<url>.*?)(?P=quote)', re.I | re.S)


class VersionedFrontend(StaticFiles):
    """Fingerprint local JS/CSS references; revalidate HTML and mutable code.

    The document ETag includes the rendered asset hashes, so changing a module
    invalidates cached HTML even when the HTML file itself was not edited.
    Imagery, models and other large files keep the normal StaticFiles behavior.
    """

    def _document(self, full_path):
        page = Path(full_path)
        root = Path(self.directory).resolve()

        def version(match):
            original = html.unescape(match['url'])
            url = urlsplit(original)
            if url.scheme or url.netloc or not url.path.lower().endswith(('.js', '.css')):
                return match[0]
            decoded = unquote(url.path)
            asset = (root / decoded.lstrip('/') if decoded.startswith('/') else page.parent / decoded).resolve()
            if not asset.is_relative_to(root) or not asset.is_file():
                return match[0]
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
            query = [(key, value) for key, value in parse_qsl(url.query, keep_blank_values=True) if key != 'v']
            query.append(('v', digest))
            versioned = urlunsplit(url._replace(query=urlencode(query)))
            return match['prefix'] + match['quote'] + html.escape(versioned, quote=True) + match['quote']

        return ASSET_REFERENCE.sub(version, page.read_text(encoding='utf-8'))

    def file_response(self, full_path, stat_result, scope, status_code=200):
        suffix = Path(full_path).suffix.lower()
        if suffix == '.html':
            content = self._document(full_path).encode('utf-8')
            headers = {'cache-control': 'no-cache',
                       'etag': '"' + hashlib.sha256(content).hexdigest() + '"'}
            tags = Headers(scope=scope).get('if-none-match', '')
            if status_code == 200 and any(tag.strip().removeprefix('W/') in ('*', headers['etag'])
                                          for tag in tags.split(',')):
                return NotModifiedResponse(headers)
            response = HTMLResponse(content, status_code=status_code, headers=headers)
            if scope['method'] == 'HEAD':
                response.body = b''  # Keep the GET Content-Length and ETag.
            return response
        response = super().file_response(full_path, stat_result, scope, status_code)
        if suffix in ('.js', '.css'):
            response.headers['Cache-Control'] = 'no-cache'
        return response
