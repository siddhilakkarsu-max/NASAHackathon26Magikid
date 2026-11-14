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
- THEMIS night IR is used as a **proxy** for thermal inertia (warm at night = rock, cold = loose sand).
- **Simulated surface temperature** uses TES broadband albedo and apparent thermal inertia. The overview uses 0.5° cells, with finer 0.125° TES inputs when zoomed in on the global layer. Unavailable thermal inertia is transparent.
- The model uses the selected Mars local solar hour and solar longitude (`Ls`) to compute diurnal solar heating. It approximates thermal emission and subsurface conduction, including heat retained after sunset. It uses spatially and seasonally varying OpenMARS visible column dust opacity. The calculation assumes level terrain, emissivity 0.95, and fixed downwelling longwave flux of 25 W/m². It has no seasonal frost model, and its absolute temperature has not been calibrated to Jezero observations.
- Primary grid sources are [NASA PDS TES albedo](https://pds-geosciences.wustl.edu/missions/mgs/tesspecial.html) and [NASA PDS TES apparent thermal inertia](https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html). The thermal grid uses observation-backed TES nighttime values where available, with observation-backed TES daytime values filling remaining supported cells.
- Walk-back and consumables estimates assume the return trip costs the same as the way out.
- O₂ is modeled at a flat rate. Uphill terrain increases time and therefore oxygen use.
- The oxygen budget applies to the astronaut’s suit supply. The crew rover’s cabin oxygen is outside the model.
- Pressurized-rover loads are engineering estimates.
- Shelter denotes terrain near steep slopes. Confirm that a site can provide actual cover with higher-resolution imagery.
- At roughly 230 m per pixel, the slope map smooths out meter-scale hazards.

## Weather layers and data

The **Global weather** group includes simulated ground temperature, an OpenMARS ground-temperature reference, near-surface air temperature, surface pressure, wind speed, animated wind arrows, and seasonal infrared dust opacity. Arrowheads follow the horizontal wind field, with motion sped up for display. The background shows speed and the animation can be paused. Hover for native-cell coordinates and values, or click to keep a reading in the panel. The **Overlay opacity** slider exposes the NASA Viking imagery underneath. The hour control applies the same local solar hour at each longitude. These layers represent historical or climatological scenarios.

**Weather timeline** accepts start and end sols (days within a Martian year), with a scrubber for individual sols. Playback skips frames on long ranges. The seasonal sol-to-`Ls` conversion comes from the LMD climatology file's daily coordinates.

The globe uses a bundled, downsampled [NASA/JPL Mars Trek Viking MDIM 2.1 mosaic](https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=mars) plus higher-resolution network tiles at closer zoom. CesiumJS 1.147.0 is bundled under its included Apache License. Global ground temperatures start with a 0.5° overview. When the view is close enough, the app computes only the visible region plus a small margin using 0.125° TES inputs (about 7.4 km north–south) and displays the range for that view. Missing thermal inertia is transparent at both scales. The OpenMARS atmosphere and ground-temperature reference stay at their 5° source resolution. Wind glyph density rises with zoom while following the same 5° wind field. Interface references include [NASA Worldview](https://worldview.earthdata.nasa.gov/), [NASA GIBS](https://nasa-gibs.github.io/gibs-api-docs/access-advanced-topics/), and [earth/nullschool](https://earth.nullschool.net/).

- **Air, pressure, wind and visible dust:** [Holmes, Lewis and Patel, OpenMARS](https://doi.org/10.21954/ou.rd.c.4278950), retrieved from [Bhattacharya's ARCO-OpenMARS conversion](https://doi.org/10.57967/hf/8741), CC BY 4.0. The app uses twelve approximately ten-sol windows from Mars Year 29, a 5° grid, and twelve two-hour samples per sol. Air temperature and winds are from the lowest available model level (sigma ≈ 0.9995). The app averages within each window, interpolates cyclically between windows and hours, and computes wind speed and direction from the interpolated components.
- **Displayed dust opacity:** [LMD climatology scenario](https://www-mars.lmd.jussieu.fr/mars/dust_scenarios/), derived from the [Montabone et al. dust climatology](https://www-mars.lmd.jussieu.fr/mars/dust_climatology/) (CC BY-SA 3.0). It is 9.3 μm absorption opacity normalized to 610 Pa, so its map depends on season alone. The ground model uses the OpenMARS visible-band field for sunlight attenuation.
- **Reference ground temperature:** The `tsurf` field from the same twelve OpenMARS Mars Year 29 windows provides an independently modeled ground-temperature comparison at 5°. The finer TES-driven simulation uses observed surface-property inputs and the same coarse dust forcing, and still assumes 25 W/m² of downwelling longwave radiation.
- `thermal_data/weather.npz` contains the processed grids for offline computation. To rebuild it with Internet access, install `blosc2` and `zstandard` in addition to the normal requirements and run `python build_weather.py`. The builder uses curl and downloads only the twelve required reanalysis windows.
- The app's **Weather data and source inventory** link provides the reviewed catalog. Its role column indicates which numerical archives and imagery were used and which sources are references or validation candidates.

### Independent check at Jezero

NASA PDS Mars 2020 MEDA Sol 30 derived TIRS data were evaluated in thirteen local true solar time windows around `Ls` 20.35°. Upward IR4 longwave flux was converted to brightness temperature with the instrument team's convention, `T = (flux / σ)^(1/4)`. The TES-driven model's kinetic temperature was converted to emitted brightness using its assumed emissivity of 0.95. Against these windows the mean absolute differences were 16.57 K at 0.5° and 16.92 K at 0.125°. The OpenMARS reference had a 4.45 K mean absolute difference in this check. That comparison uses a different weather year (MY29 versus MY36) and compares its modeled surface temperature with IR4 brightness. Rover spot-scale readings and modeled grid cells also represent different areas. The Jezero check is a local diagnostic and does not establish global accuracy. [NASA PDS MEDA archive](https://pds-atmospheres.nmsu.edu/data_and_services/atmospheres_data/PERSEVERANCE/meda.html) · [Instrument-team flux method](https://doi.org/10.1029/2022JE007537)

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
