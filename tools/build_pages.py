"""Build the front end as a static site for Cloudflare Pages, talking to a public Marswalk server.

    python3 tools/build_pages.py                                   # -> dist/, server https://100-20-2-83.sslip.io
    python3 tools/build_pages.py --api https://my-server.example   # another server (or MARSWALK_API=...)

What it does (standard library only, so it runs on Cloudflare's build machine as is):
- copies frontend/ to dist/;
- puts tools/pages/api_shim.js first in every page: the pages call the server with root paths ("/api/…",
  "/murray/…" tiles, "/terrain/…"), and the shim sends those to the server instead of to Pages;
- fingerprints local .js/.css references (?v=<hash>), like the server does, so a new deploy is never mixed
  with modules cached from an older one;
- writes _headers (HTML always revalidated) and build-info.json (server, commit, time).
The server must allow cross-origin requests; app.py does (CORSMiddleware, allow_origins=["*"]).
See deploy/cloudflare/README.md.
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHIM = Path(__file__).resolve().parent / "pages" / "api_shim.js"
DEFAULT_API = "https://100-20-2-83.sslip.io"
MARKER = ".marswalk-pages-build"
SERVER_PATHS = ("api", "murray", "terrain", "cubes", "tiles", "ctxtiles")
ASSET_REFERENCE = re.compile(r'(?P<prefix><(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*)'
                             r'(?P<quote>["\'])(?P<url>.*?)(?P=quote)', re.I | re.S)
SERVER_LINK = re.compile(r'(\bhref\s*=\s*)(["\'])(/(?:%s)(?:/[^"\']*)?)\2' % "|".join(SERVER_PATHS), re.I)


def check_api(url):
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1")
    if parts.scheme not in ("https",) + (("http",) if local else ()) or not parts.netloc or parts.query or parts.fragment:
        sys.exit(f"--api must be an https:// server address (http only for localhost), got {url!r}")
    if parts.path not in ("", "/"):
        sys.exit("--api must be the server's root address (no path)")
    return url.rstrip("/")


def version_assets(page, root, text):
    """<script src> / <link href> to local .js/.css get ?v=<content hash> (same idea as frontend_delivery.py)."""
    def version(match):
        url = urlsplit(html.unescape(match["url"]))
        if url.scheme or url.netloc or not url.path.lower().endswith((".js", ".css")):
            return match[0]
        decoded = unquote(url.path)
        asset = (root / decoded.lstrip("/") if decoded.startswith("/") else page.parent / decoded).resolve()
        if not asset.is_relative_to(root) or not asset.is_file():
            return match[0]
        query = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True) if k != "v"]
        query.append(("v", hashlib.sha256(asset.read_bytes()).hexdigest()[:16]))
        versioned = urlunsplit(url._replace(query=urlencode(query)))
        return match["prefix"] + match["quote"] + html.escape(versioned, quote=True) + match["quote"]
    return ASSET_REFERENCE.sub(version, text)


def insert_shim(text, shim):
    """The shim must run before any other script: right after <meta charset> (kept first), else after <head>."""
    tag = f"<script>{shim}</script>\n"
    charset = re.search(r"<meta\s+charset[^>]*>\s*", text, re.I)
    if charset:
        return text[:charset.end()] + tag + text[charset.end():]
    head = re.search(r"<head\b[^>]*>\s*", text, re.I)
    if not head:
        raise ValueError("page has no <head>")
    return text[:head.end()] + tag + text[head.end():]


def commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return os.environ.get("CF_PAGES_COMMIT_SHA", "")[:7] or None


def build(api, out):
    if out.exists():
        if not (out / MARKER).exists():
            sys.exit(f"{out} exists and isn't a previous build; refusing to delete it")
        shutil.rmtree(out)
    shutil.copytree(FRONTEND, out, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
    shim = SHIM.read_text(encoding="utf-8").replace("__MARSWALK_API__", api)
    if "</script" in shim.lower():
        raise ValueError("the shim can't contain </script>")
    pages = sorted(out.rglob("*.html"))
    for page in pages:
        text = version_assets(page, out.resolve(), page.read_text(encoding="utf-8"))
        text = SERVER_LINK.sub(lambda m: f"{m[1]}{m[2]}{api}{m[3]}{m[2]}", text)   # plain links to server pages
        page.write_text(insert_shim(text, shim), encoding="utf-8")
    (out / "_headers").write_text(
        "# Cloudflare Pages: pages always revalidate; their .js/.css references carry a content hash.\n"
        "/*.html\n  Cache-Control: no-cache\n/\n  Cache-Control: no-cache\n"
        "/vendor/*\n  Cache-Control: public, max-age=86400\n", encoding="utf-8")
    info = {"api": api, "commit": commit(), "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    (out / "build-info.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    (out / MARKER).write_text("generated by tools/build_pages.py; safe to delete\n", encoding="utf-8")
    files = sum(1 for p in out.rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"Built {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}: {len(pages)} pages, {files} files, "
          f"{size / 1e6:.1f} MB; server {api}")
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default=os.environ.get("MARSWALK_API", DEFAULT_API),
                    help=f"public server address (default: $MARSWALK_API or {DEFAULT_API})")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="output folder (default: dist/)")
    args = ap.parse_args(argv)
    build(check_api(args.api), Path(args.out).resolve())


if __name__ == "__main__":
    main()
