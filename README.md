# Marswalk Planner — Python back end + Cesium front end

Every pixel of Mars holds a vector of values (elevation, slope, roughness, ground firmness, …).
User inputs (time of day, season, vehicle, EVA budget) are applied per pixel to produce
a cost map, a safe route, a walk-back zone and a time-to-shelter map.

```
build_cube.py  ──►  cubes/<region>.npz  ──►  app.py (FastAPI, all the math)  ──►  frontend/index.html (Cesium globe)
```

## 1. Set up (once)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Run it right away with demo data
```bash
python make_demo_cube.py          # FAKE Jezero-shaped terrain so everyone can start building
uvicorn app:app --reload --port 8000
```
Open http://localhost:8000 → the globe flies to Jezero. Pick a layer, set a base and a target, press **Plan route**.

## 3. Swap in real NASA data
```bash
python build_cube.py jezero       # overwrites the demo cube
python build_cube.py global       # whole planet, ~3.7 km/px (slower)
```
`config.py` lists the sources for each band and tries them in order:
1. a **local GeoTIFF** you downloaded (most reliable — uncomment the `file` line and set the path)
2. a **remote GeoTIFF** (reads only the Jezero window)
3. the **USGS WMS** map server

If a download fails, the script says which band was skipped. Elevation is required; everything else is optional.
Check the result by opening `cubes/jezero.tif` in QGIS (each band is labeled).

Good GeoTIFFs to download (USGS Astrogeology):
- Mars MGS MOLA – MEX HRSC Blended DEM Global 200m v2 (elevation)
- THEMIS IR Night / Day global mosaics (100 m)
- HiRISE / CTX DEMs for Jezero from the Mars Human Exploration Zone DEM archive (much sharper slopes)

## 4. Add a new band (CRISM minerals, TES dust, hydrogen, …)
Add an entry to `SOURCES` in `config.py`, rerun `build_cube.py`. It automatically appears in the
pixel panel. To use it in the route cost, edit `cost_seconds_per_meter()` in `physics.py`.

## 5. Find a target by description
Type e.g. **valley with clay**, **flat firm ground near a cliff**, **sunny ridge close to base** or
**shelter without sand** into "describe the target" and press Enter. `search.py` scores every pixel for
each word (valley, ridge, flat, steep, firm, sand, sunny, shadow, shelter, clay, …), combines them, sets the
best passable spot as the target and lists the runners-up. With a base set, places you can reach and return
from within the EVA budget rank first.
- New word? Add it to a feature's `words` in `search.FEATURES`.
- **Clay** has no band yet, so it uses the approximate zone in `config.SEARCH_ZONES` (Jezero delta). Add a
  CRISM clay map as a band named `clay` and the search uses it per pixel instead (same for `carbonate`, `olivine`, …).
- Words the built-in parser doesn't know go to a **free AI model on OpenRouter** if `OPENROUTER_API_KEY` is set
  (free key at openrouter.ai, `export OPENROUTER_API_KEY=...` before starting uvicorn). It picks the current
  `:free` models automatically, falling back from one to the next; set `OPENROUTER_MODELS=a:free,b:free` to choose.
  Free models are limited to 20 requests/min and 50/day per account (1000/day after buying $10 of credits);
  there is no unlimited $0 text model. Known-word queries ("valley with clay") never use the AI, and answers are
  cached. Without a key, the search runs on the known words and lists the rest.
- Offline or over the free limit? Any OpenAI-compatible server works, e.g. Ollama:
  `OPENROUTER_BASE_URL=http://<host>:11434/v1 OPENROUTER_API_KEY=local OPENROUTER_MODELS=gemma4:26b-a4b`.
  Tested on a laptop with a 4 GB T1200 GPU: `gemma4:26b-a4b` ~9 s per query, `gemma4:e4b` ~4 s.

## Who owns what
| File / function | Owner | What to improve |
|---|---|---|
| `physics.py` → `slip_fraction`, `speed_kmh`, `cost_seconds_per_meter` | Victoria, Gia | Slip table, metabolic/O₂ cost, weights |
| `physics.py` → `sun_position`, `illumination`, `surface_temp_k` | Jason | Replace the approximate temperature with the thermal model |
| `physics.py` → `shelter_seeds`, walk-back in `app.py` | Gia, Siddhi | Real shelter locations, O₂ budget instead of hours |
| `config.py` → `SOURCES`, `SCIENCE_TARGETS`, `VEHICLES` | Siddhi, Darren | Real data paths, CRISM targets, vehicle limits |
| `app.py` → `explanation` text | Darren, Jason | Hook an LLM in here for richer route reasoning |
| `frontend/index.html` | Gia, Victoria, Olivia | All styling and layout |

## API (for the front end team)
| Call | Returns |
|---|---|
| `GET /api/regions` | regions, bounds, bands, vehicles, science targets |
| `GET /api/pixel?lat=&lon=&region=` | every value stored in that pixel + ground type + confidence |
| `POST /api/layer/{slope|firmness|cost|illumination|temperature|shelter|elevation}` | PNG overlay + bounds + legend |
| `POST /api/plan` | route (lat/lon list), stats, warnings, explanation, walk-back zone PNG |
| `POST /api/find` | best target spots for a text description (`"query": "valley with clay"`), why each matched, match heatmap PNG |

Body for POST calls: `{"region":"jezero","vehicle":"astronaut","local_hour":11,"ls":90,"budget_hours":4}`
(+ `"base":{"lat":..,"lon":..}, "target":{...}` for `/api/plan`).

## Optional: Cesium Mars 3D terrain
The globe works without an account (NASA Mars Trek imagery). For 3D terrain, create a free
Cesium ion account, add **Cesium Mars** from the Asset Depot, and put your token and asset id
at the top of the `<script>` in `frontend/index.html`.

## Honest limits (say these if judges ask)
- THEMIS night IR is used as a **proxy** for thermal inertia (warm at night = rock, cold = loose sand).
- Surface temperature is a simple approximation, not a full thermal model.
- Walk-back assumes the return trip costs the same as the way out.
- "Shelter" = within a few pixels of steep walls; real overhangs/lava tubes need HiRISE inspection.
- At ~230 m/px slopes are smoothed; HiRISE DEMs (1 m) give the real meter-scale hazards.

## HiRISE / CTX close-ups of Jezero (official Mars 2020 landing products, USGS)
Two map levels are set up in `config.py`:
- `jezero` – whole crater at ~29 m/px from the **CTX 20 m elevation** + **CTX 6 m image** (downloaded automatically)
- `jezero_hirise` – landing site + delta at ~10 m/px from the **HiRISE 1 m elevation** (1.8 GB, download first)

```bash
mkdir -p data && cd data
curl -O https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/ScienceInvestigationMaps_JPL/M20_JezeroCrater_CTXDEM_20m.tif
curl -O https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0.tif
curl -O https://planetarymaps.usgs.gov/mosaic/mars2020_trn/HiRISE/JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif
cd ..
python build_cube.py jezero
python build_cube.py jezero_hirise
```
The 25 cm HiRISE image mosaic (~7 GB) is not used: too large for the weekend.
