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
curl -L -O https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/ScienceInvestigationMaps_JPL/M20_JezeroCrater_CTXDEM_20m.tif
curl -L -O https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0.tif
curl -L -O https://planetarymaps.usgs.gov/mosaic/mars2020_trn/HiRISE/JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif
cd ..
python build_cube.py jezero
python build_cube.py jezero_hirise
```
The 25 cm HiRISE image mosaic (~7 GB) is not used: too large for the weekend.

## Data catalog – everything from the team doc
| Dataset (team doc) | In the app as | Status / how to get it |
|---|---|---|
| MOLA / HRSC-MOLA elevation | `elevation`, `slope`, `roughness`, `aspect` | automatic (USGS) |
| CTX 20 m + HiRISE 1 m DEMs (Human Exploration Zone / Mars 2020) | `elevation` (Jezero) | `data/` – see curl commands above |
| CTX / HiRISE imagery | 6 m photo + global 5 m CTX mosaic | automatic |
| THEMIS day/night IR | `themis_day`, `themis_night` | automatic (USGS WMS) |
| THEMIS thermal inertia, Jezero (calibrated) | `thermal_inertia`, `firmness`, ground type | `data/Jezero_Thermal_Inertia_v1.tiff` (Zenodo 4931348) |
| TES albedo (whole planet) | `albedo`, temperature model | automatic, or `data/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif` |
| CRISM minerals, Jezero landing area | `minerals`, `science` | `data/jezeroFinal.tif` (Zenodo 5575824) |
| MSL RAD (0.64 mSv/day at Gale) + elevation | `air_column_vs_gale` (radiation shielding) | computed from elevation |
| Dust storms (THEMIS dust maps / OpenMARS) | dusty-season warning from the Ls slider | built in; full forecasts = future work |
| Team albedo + TI table (259,900 rows) | `albedo`, `thermal_inertia` fallback | `data/mars_albedo_ti.txt` if available |
| TES dust cover index, neutron-spectrometer hydrogen, SHARAD ice | – | only coloured images found, no numeric files yet |
| AI4MARS / Mars-Bench | – | ML training sets (terrain classifier) – future work, not map layers |

Decision layer: **Mission suitability** = 0.45 x safety (slope + firmness) + 0.35 x science (CRISM detections)
+ 0.20 x radiation shielding (air column). Weights are in `suitability()` in `app.py`.

Extra downloads (run inside `data/`):
```bash
curl -L -o Jezero_Thermal_Inertia_v1.tiff "https://zenodo.org/records/4931348/files/Jezero_Thermal_Inertia_v1.tiff?download=1"
curl -L -o jezeroFinal.tif "https://zenodo.org/records/5575824/files/jezeroFinal.tif?download=1"
curl -L -O https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif
```
