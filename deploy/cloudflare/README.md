# Hosting the front end on Cloudflare Pages

The pages (planner, game, kit) are served as a static site by Cloudflare Pages. All data, maps and AI requests go to
the public Marswalk server, by default **https://100-20-2-83.sslip.io** (the AWS Lightsail server in
`deploy/aws/`).

```
browser ── pages, scripts, 3D models ──▶ Cloudflare Pages (static, dist/)
        └─ /api, /murray, /terrain, … ──▶ https://100-20-2-83.sslip.io (FastAPI + Caddy)
```

## Build

```bash
python3 tools/build_pages.py                              # -> dist/ for https://100-20-2-83.sslip.io
python3 tools/build_pages.py --api https://other.server   # or set MARSWALK_API
```

The build needs only Python 3 (no packages). It does three things:
- **Copies the front end:** `frontend/` goes to `dist/`.
- **Redirects server calls:** it puts a small script (`tools/pages/api_shim.js`) first in every page. The front
  end calls the server with root paths like `/api/...`, `/murray/...` and `/terrain/...`. The script sends those
  requests to the server address, so the front-end code is the same as when the server hosts it.
- **Versions scripts and stylesheets:** it adds `?v=<hash>` to the page's script and stylesheet links, so a new
  deploy never mixes with old cached files.

## Deploy

### Option A: from your computer (Wrangler)

```bash
python3 tools/build_pages.py
npx wrangler login                                          # once
npx wrangler pages deploy dist --project-name marswalk      # creates the project the first time
```

The site is then at `https://marswalk.pages.dev`, and each deploy also gets its own preview URL.

### Option B: Cloudflare builds it from GitHub

In the Cloudflare dashboard, choose **Workers & Pages → Create → Pages → Connect to Git**, then select this repository
and enter:

| Setting | Value |
|---|---|
| Production branch | `main` |
| Build command | `python3 tools/build_pages.py` |
| Build output directory | `dist` |
| Environment variable | `SKIP_DEPENDENCY_INSTALL` = `1` (the build needs no packages, so skip the server's `requirements.txt`) |
| Environment variable (optional) | `MARSWALK_API` = `https://100-20-2-83.sslip.io` |

Every push to `main` then redeploys, and pull requests get preview URLs.

## Keep the server in step

The pages call the server's API, so deploy the same commit to the server when the API changes
(`deploy/aws/deploy.sh <ip> <key.pem>`). `dist/build-info.json` records which server and commit a build used.

The server must accept requests from the Pages site. `app.py` allows any origin (`CORSMiddleware`,
`allow_origins=["*"]`), and Caddy passes that through.

## Limits

- **Size:** 3 pages, about 400 files and 32 MB, well inside Pages' limits (20,000 files, 25 MB per file).
- **Server load:** only the static files move to Cloudflare. Map tiles, terrain, planning and the AI still run
  on the server, and the Claude key stays there in `ai.env`.
