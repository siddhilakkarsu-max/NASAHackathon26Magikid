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
python build_cube.py jezero                   # overwrites the demo cube (~29 m/px as set in config.py)
python build_cube.py jezero --px-per-deg 512  # ~115 m/px: the committed cube (small enough for git)
python build_cube.py global                   # whole planet, ~3.7 km/px (slower)
```
`config.py` lists the sources for each band and tries them in order:
1. a **local GeoTIFF** you downloaded (most reliable — uncomment the `file` line and set the path)
2. a **remote GeoTIFF** (reads only the Jezero window)
3. the **USGS WMS** map server

If a download fails, the script says which band was skipped. Elevation is required; everything else is optional.
Check the result by opening `cubes/jezero.tif` in QGIS (each band is labeled).

Datasets in the Jezero cube (all fetched automatically by `build_cube.py`; downloads are cached in `data/`):

| Band(s) | Dataset | Resolution | Source |
|---|---|---|---|
| `elevation` → `slope`, `aspect`, `roughness` | CTX DEM of Jezero (Mars 2020 TRN, USGS); MOLA–HRSC blend elsewhere | 20 m (200 m) | planetarymaps.usgs.gov/mosaic/mars2020_trn |
| `imagery` | CTX orthomosaic of Jezero | 6 m | same |
| `thermal_inertia` → `firmness` | THEMIS night-time thermal inertia, Huang 2026 (1 km browse version) | 1 km | zenodo.org/records/23527756 |
| `themis_night`, `themis_day` | THEMIS IR mosaics (USGS WMS) | 100 m | planetarymaps.usgs.gov |
| `clay`, `carbonate`, `olivine`, `pyroxene`, `sulfate`, `hydrated_silica`, `hydrated` | CRISM summary parameters (Viviano-Beck et al. 2014): 15 targeted observations (MTRDR) + the multispectral map tile (MRDR) | 18–180 m | PDS Geosciences via ode.rsl.wustl.edu |

- **Minerals:** each band holds the CRISM band depth for that mineral (e.g. `clay` = D2300). Parameters and
  detection thresholds are in `config.MINERALS`; add a mineral there and rebuild. Targeted observations are used
  where they exist, the 180 m map tile fills the rest; places CRISM never imaged stay empty.
- **Firmness** follows the thermal-inertia classes: <150 fine dust, 150–300 sand, 300–600 coarse/crusted,
  >600 bedrock (log scale, 0 → 1). Sub-km detail comes from the THEMIS night-IR picture.
- Not included yet: TES dust cover index / albedo, GRS/MONS hydrogen, SHARAD/MARSIS ice, OMEGA
  (no ready GeoTIFF found); the 100 m thermal inertia product (Science Data Bank, needs an account).

## 4. Add a new band (TES dust, hydrogen, …)
Add an entry to `SOURCES` in `config.py`, rerun `build_cube.py`. It automatically appears in the
pixel panel. To use it in the route cost, edit `cost_seconds_per_meter()` in `physics.py`.

## 5. Plan a mission (main panel)
Type a goal (**sample clay where water once flowed**, **olivine**, **carbonate in a valley**), pick the vehicle
(on foot, 2-wheel, 4-wheel, pressurized buggy), season and priority (safety / speed / energy), press **Plan mission**.
`mission.py` then:
1. reads the goal into target features (keywords, else the AI model) and lists the **tools** (by goal + essentials,
   total kg and W);
2. scores every pixel for the goal, removes Special Regions, slopes beyond the vehicle and very loose ground
   (thermal inertia < 150) and anything out of range of a safe landing spot, and keeps the **top 3 destinations B**;
3. gives each B the closest safe **landing spot A** (flat <5°, few rocks, thermal inertia ≥200, below −500 m,
   within 50° of the equator, all over a 500 m circle): **NASA candidate** if it lies in a known landing site /
   ellipse (`config.NASA_SITES`), else **Tool-found**; plus a **detail card** (target and data confidence,
   terrain, conditions, nearby resources, sampling spots, protection status, distance from A);
4. routes A → B on a cost map built from time, energy/oxygen, terrain risk and seasonal dust; Perseverance's
   **green** drives cost ×0.7, **yellow** ×1.5, **red** (beyond the vehicle) is blocked; then checks the round
   trip's oxygen and/or battery with tool mass, a 15–25 % reserve and a turnaround deadline, dropping failures;
5. scores the survivors 1–5 in a **decision matrix** (`config.MATRIX_CRITERIA`; the priority adds +10 to
   safety, time or resources) and recommends the best;
6. shows the winner colored by risk, #2/#3 faded, and explains why: the summary from the numbers appears at once,
   then the AI model's reasoning streams into a "AI reasoning" box and its explanation streams in word by word.
   When the AI reads the goal, its thinking streams live too (kept under "How … read the goal"). Change vehicle/priority/season, tick "stick to green tracks" or click #2/#3 to adjust; the new
   plan is compared with the previous one.

Rover tracks: `python fetch_tracks.py jezero` downloads Perseverance's real traverse (NASA/JPL mission maps).
All vehicle, suit, tool and landing numbers live in `config.py` (`MISSION_VEHICLES`, `SUIT`, `TOOLS`,
`LANDING_RULES`, `SEASONS`, `PRIORITIES`) and are first-order assumptions; tune them there.

## 6. Find a target by description (manual planning)
Type e.g. **valley with clay**, **flat firm ground near a cliff**, **sunny ridge close to base** or
**shelter without sand** into "describe the target" and press Enter. `search.py` scores every pixel for
each word (valley, ridge, flat, steep, firm, sand, sunny, shadow, shelter, clay, …), combines them, sets the
best passable spot as the target and lists the runners-up. With a base set, places you can reach and return
from within the EVA budget rank first.
- New word? Add it to a feature's `words` in `search.FEATURES`.
- **Minerals:** clay, carbonate, olivine, pyroxene, sulfate, opal/hydrated silica, "water" (water-bearing
  minerals) and "minerals" (any detection) use the CRISM bands, matching only above the detection limit. A region
  without CRISM bands falls back to the approximate zones in `config.SEARCH_ZONES`.
- Words the built-in parser doesn't know go to a **free AI model on OpenRouter** if `OPENROUTER_API_KEY` is set
  (free key at openrouter.ai, `export OPENROUTER_API_KEY=...` before starting uvicorn). It picks the current
  `:free` models automatically, falling back from one to the next; set `OPENROUTER_MODELS=a:free,b:free` to choose.
  Free models are limited to 20 requests/min and 50/day per account (1000/day after buying $10 of credits);
  there is no unlimited $0 text model. Known-word queries ("valley with clay") never use the AI, and answers are
  cached. Without a key, the search runs on the known words and lists the rest.
- Offline or over the free limit? Any OpenAI-compatible server works, e.g. Ollama:
  `OPENROUTER_BASE_URL=http://<host>:11434/v1 OPENROUTER_API_KEY=local OPENROUTER_MODELS=gemma4:26b-a4b`.
  Tested on a laptop with a 4 GB T1200 GPU: `gemma4:26b-a4b` ~9 s per query, `gemma4:e4b` ~4 s.
- The mission panel streams the AI's thinking. `AI_REASONING` sets the thinking effort (`low` by default, `none` to
  turn it off); `AI_THINK_SECONDS` (default 40) stops a model that is still thinking after that long and asks for
  the answer right away. With the local gemma4:26b a full mission with AI takes ~2 min (thinking is visible
  throughout); give Ollama at least an 8k context (`OLLAMA_CONTEXT_LENGTH=8192`) so the thinking fits.

## Who owns what
| File / function | Owner | What to improve |
|---|---|---|
| `physics.py` → `slip_fraction`, `speed_kmh`, `cost_seconds_per_meter` | Victoria, Gia | Slip table, metabolic/O₂ cost, weights |
| `physics.py` → `sun_position`, `illumination`, `surface_temp_k` | Jason | Replace the approximate temperature with the thermal model |
| `physics.py` → `shelter_seeds`, walk-back in `app.py` | Gia, Siddhi | Real shelter locations, O₂ budget instead of hours |
| `config.py` → `SOURCES`, `SCIENCE_TARGETS`, `VEHICLES` | Siddhi, Darren | Real data paths, CRISM targets, vehicle limits |
| `physics.py` → `endurance`, `config.py` → `consumables`, `CONSUMABLE_SOURCES` | Gk | Real EVA and cabin O₂ loads, rover power curves |
| `app.py` → `explanation` text | Darren, Jason | Hook an LLM in here for richer route reasoning |
| `frontend/index.html` | Gia, Victoria, Olivia | All styling and layout |

## API (for the front end team)
| Call | Returns |
|---|---|
| `GET /api/regions` | regions, bounds, bands, vehicles, science targets, `vehicle_specs` (rated hours + consumable limits) |
| `GET /api/pixel?lat=&lon=&region=` | every value stored in that pixel + ground type + confidence |
| `POST /api/layer/{slope|firmness|cost|illumination|temperature|shelter|elevation}` | PNG overlay + bounds + legend |
| `POST /api/plan` | route (lat/lon list), stats (distance, time, slope, **O₂/energy vs capacity**, max range), warnings, explanation, walk-back zone PNG |
| `POST /api/find` | best target spots for a text description (`"query": "valley with clay"`), why each matched, match heatmap PNG |
| `GET /api/mission/options` | vehicles, seasons, priorities, decision-matrix criteria and default weights |
| `POST /api/mission` | `{"goal", "vehicle", "season", "priority", "green_only"}` → settings, tools, 3 candidates (A, B, card, route, resources, scores), dropped, decision matrix totals, template explanation, science + off-limits PNGs, `id` |
| `POST /api/mission/stream` | the same plan as server-sent events with the AI's thinking live: `status`, `ai` (`phase`: goal / explain, `kind`: reasoning / content, `text`), `result` (the full plan), `explanation`, `done` |
| `POST /api/mission/{id}/explain` | the AI-written explanation for that plan (slower; falls back to the template) |
| `GET /api/tracks?region=&vehicle=` | rover drive segments classed green / yellow, km of each, red off-limits PNG for the vehicle |

Body for POST calls: `{"region":"jezero","vehicle":"astronaut","local_hour":11,"ls":90,"budget_hours":4}`
(+ `"base":{"lat":..,"lon":..}, "target":{...}` for `/api/plan`).

## Consumables: O₂ and energy against what the traveller actually carries

Every plan is costed as a **round trip** and compared with the vehicle's own capacity. `stats` reports
`o2_used_kg` / `o2_max_kg` / `o2_pct`, `energy_used_kwh` / `energy_max_kwh` / `energy_pct`, `max_range_km`,
and `limiting_factor` — whichever ceiling is closest to being hit.

| Traveller | Quantity | Rate | Carried | Basis |
|---|---|---|---|---|
| Astronaut on foot | O₂ | 0.085 kg/h | 0.68 kg | NASA figures, see below |
| Pressurized crew rover | Energy | 1.5 kW idle + 0.12 kWh/km | 20 kWh | **estimate**, see below |
| Curiosity-class rover | Energy | 0.15 kW idle + 3.33 kWh/km | 2.5 kWh | MMRTG figures, see below |

Both quantities scale with **time as well as distance**, which is why a rocky detour costs more without a
second terrain term: `cost_seconds_per_meter()` has already made that ground slower, so it simply takes longer.

**Where the numbers come from** (also returned per vehicle as `vehicle_specs[k].source`):

- **O₂, astronaut** — the ALS Baseline Values and Assumptions Document (NASA/JSC-47804) gives 0.076 kg/h for a
  closed-loop PLSS; the X-Hab PLSS model uses a 350 W baseline metabolic rate at ~20 kJ per litre of O₂, i.e.
  ~0.084 kg/h. 0.68 kg is the xEMU's 8 h design endurance at that rate, and the planner holds back the 1 h
  contingency the Artemis surface-suit requirement asks for (that is the `reserve` slider).
- **Endurance, astronaut** — xEMU is specified for 8 h of autonomous EVA; Artemis surface EVAs are planned at
  4–8 h, ~2 km radius at 2 km/h over level terrain.
- **Energy, Curiosity-class** — MSL's MMRTG produces ~110 W electrical, 2.5–2.7 kWh per sol (NASA/JPL). Loads:
  at least 150 W whenever awake, up to 500 W while driving (JPL), which at this profile's 0.15 km/h works out
  at ~3.3 kWh/km. So a sol of MMRTG output is genuinely about 0.3 km out-and-back — the rover is meant to
  look limited next to the crew rover, not broken.
- **Energy, pressurized crew rover** — a **labelled engineering estimate**; no published NASA figure was found
  for these loads. It is the "estimate" entry in `CONSUMABLE_SOURCES` in `config.py` and should be tuned.

Rules the planner applies:

- `rated_hours` is a hard per-vehicle ceiling, separate from the EVA budget. The budget slider's maximum
  follows the selected vehicle, so you cannot plan past its rating.
- `reserve` still applies: only `budget_hours × (1 − reserve)` counts as usable time.
- `max_range_km` is the furthest one-way distance you can reach **and** return from, on a full load, at the
  pace of the route you just planned.
- Routing itself is still time-based only. An over-capacity trip is drawn and flagged rather than refused —
  state-space pathfinding on remaining energy would be the next step, not something this pretends to do.

## Optional: Cesium Mars 3D terrain
The globe works without an account (NASA Mars Trek imagery). For 3D terrain, create a free
Cesium ion account, add **Cesium Mars** from the Asset Depot, and put your token and asset id
at the top of the `<script>` in `frontend/index.html`.

## Honest limits (say these if judges ask)
- Thermal inertia is the 1 km browse map (absolute level uncertain by ~12–24 %); sub-km firmness detail comes
  from the uncalibrated THEMIS night-IR picture.
- CRISM band depths show where a mineral's spectral signature is, not how much of it there is; the targeted
  observations (18 m) and the map tile (180 m) have different noise, so seams can appear at their edges.
- Surface temperature is a simple approximation, not a full thermal model.
- Walk-back assumes the return trip costs the same as the way out, and so does the consumables total.
- O₂ is a flat rate: uphill work is charged in **time** by the cost map, not by a separate metabolic term.
- Cabin O₂ for a crewed rover is not modelled — only the astronaut's suit supply is tracked.
- Pressurized-rover loads are estimates, and are labelled as such everywhere they appear.
- "Shelter" = within a few pixels of steep walls; real overhangs/lava tubes need HiRISE inspection.
- At ~110 m/px slopes are smoothed; HiRISE DEMs (1 m) give the real meter-scale hazards.
- Rover track colors are a proxy: green = Perseverance drove there; yellow = the rover recorded ≥12° tilt or the
  ground is steep/loose. JPL publishes no per-drive slip, and places rovers avoided aren't in the data; red is
  terrain beyond the chosen vehicle's limits. At Jezero most goals sit 8–20 km from the traverse, so routes rarely
  use it.
- The Mars 2020 landing ellipse is approximated as a 3.5 km circle around the actual landing site. No COSPAR
  Special Regions are known at Jezero, so that mask is empty there.
- Routes use Dijkstra (skimage MCP) on the cost grid: the same lowest-cost route A* finds, without its heuristic speed-up.
- Vehicle, suit, tool and energy numbers are first-order assumptions (see config.py).

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
