# Architecture

## What the app does

Marswalk Planner is our NASA Space Apps 2026 entry for "Interplanetary Survival Guide: Martian Map".
It stacks orbital data for a piece of Mars into one grid (a "cube"), where every pixel holds elevation, slope,
ground firmness, minerals and more. A FastAPI back end turns that grid into map layers, safe routes, walk-back
zones and oxygen / battery budgets for a chosen traveller, season and time of day. A mission planner reads a goal
in plain words ("sample clay where water once flowed") and recommends a landing spot, destination and route; a
gear page says what to carry. A Cesium globe in the browser only displays what the back end returns.

## Data pipeline

```
build_cube.py <region>  --> cubes/<region>.npz  (+ cubes/<region>.tif to check in QGIS)
build_weather.py        --> thermal_data/weather.npz            (OpenMARS + LMD dust, rebuilt rarely)
thermal_detail.py <in>  --> thermal_data/tes_detail_8ppd.npz    (TES 0.125 deg albedo + thermal inertia)
fetch_tracks.py jezero  --> cubes/jezero_tracks.json            (Perseverance traverse, NASA/JPL MMGIS)
murray.py (on demand)   --> cubes/murraycache/                  (Murray Lab feature layers, HiRISE index, 3D terrain tiles)
app.py /ctxtiles        --> cubes/tilecache/                    (coloured 5 m CTX tiles)
```

- **Cubes.** `build_cube.py` resamples every source onto one lat/lon grid (`config.region_box()`), trying each
  source listed in `config.SOURCES` / `REGION_SOURCES` in order (local file, remote GeoTIFF, download, WMS, table).
  It then derives `slope`, `aspect`, `roughness`, `air_column_vs_gale`, `science` and `firmness` (`_derive()`).
  CRISM mineral bands (`config.MINERALS`) come from PDS Geosciences ODE and arrive last; the cube is saved once
  without them ("STAGE terrain ready") and again with them. A `.npz` holds `band_names`, `bands`,
  `coverage_fraction`, `bounds` and `provenance`. `cubes/jezero.npz` (~115 m/px) is committed.
- **Anywhere on Mars.** A region named `site_<lat>_<lon>` (or a name in `config.SITES`) is a 0.8 deg box built on
  request by `POST /api/sites/build`, which runs `build_cube.py` in a child process. Its elevation comes from the
  globe's own 3D terrain (Esri MDEM200M LERC tiles, `build_cube.terrain_into_grid()` via `murray.py`) and its
  thermal inertia from that quadrangle's THEMIS tile (`config.themis_ti()`).
- **Weather and climate.** `thermal_data/weather.npz` (twelve OpenMARS Mars Year 29 windows on a 5 deg grid, plus
  the LMD dust climatology) is read by `mars_weather.py`. `surface_temperature.py` simulates ground temperature on
  the 0.5 deg grid in `thermal_data/mars_grid.zip`; `thermal_detail.py` does the same at 0.125 deg for the visible
  box. `mars_radiation.py` interpolates the published AtRIS dose table (`radiation_data/`) at OpenMARS pressure.
- **Rover tracks.** `fetch_tracks.py` saves Perseverance's drives and its tilt at each waypoint; `mission.tracks()`
  classes them green (no strain signs) or yellow (rover tilt or terrain slope >= 12 deg, or thermal inertia < 200),
  using `config.TRACK_RULES`.
- **Murray Lab / CTX.** `murray.py` relays the Murray Lab viewer's layers: image tiles load straight from Esri's
  OnMars services in the browser; 3D terrain, GeoJSON layers and the HiRISE index go through the server and are
  cached. `/ctxtiles` colours the 5 m CTX mosaic with the Viking colour mosaic.

Sources and links for every dataset: [DATA_SOURCES.md](DATA_SOURCES.md).

## Request flow for the three main features

### 1. Manual route: `POST /api/plan`

1. `get_cube(region)` loads the cube (cached, reloaded when the file changes).
2. `conditions_layers()`: sun position and slope illumination (`physics.sun_position`, `illumination`) and the
   travel cost grid in seconds per metre (`physics.cost_seconds_per_meter`: Tobler walking or the MSL slip table,
   sand and roughness penalties, impassable beyond the vehicle's `max_slope`).
3. `_walkback_round_trip()`: time from base to every pixel along the time-optimal tree, plus the round-trip suit
   O2 (Minetti slope cost) and battery (drive + idle + m g h climbs); the walk-back zone is where time AND O2 AND
   energy fit after their reserves.
4. `physics.best_route()`: lowest-cost path (Dijkstra, scikit-image MCP).
5. `consumables_block()`: round-trip O2 / energy with the return leg as the route reversed
   (`physics.route_profile`, `round_trip_walk`, `climb_energy_kwh`), the 15 % / 20 % (dust season) reserve, dust
   and sunlight (`physics.dust_opacity`, `daily_sunlight_fraction`), range and the binding limit.
6. Returns route points (for the hover card), stats, warnings, explanation and the walk-back PNG.

### 2. Mission planner: `POST /api/mission` and `/api/mission/stream`

1. `_mission_cube()`: validates vehicle / season / priority; a season-slider `ls` becomes a season via
   `config.season_for_ls()`.
2. The goal is read into target features: `search.keyword_parse()`, else the AI model (`search.ai_parse`, or
   `ai_parse_stream` for the stream, which forwards the model's thinking as `ai` events).
3. `mission.plan()`: tool list (`tool_list`), a science score per pixel (`search.score_map`), a safety mask
   (Special Regions, slope beyond the vehicle, thermal inertia < 150), top 3 destinations B, the nearest safe landing
   spot A for each (`nearest_landing`, `config.LANDING_RULES`, NASA sites first), a route on a cost map of time,
   energy or O2, terrain risk and seasonal dust with green / yellow track factors (`_route_layers`), then the
   round-trip resources with tool mass, reserve and turnaround time (`_resources`, `physics.path_resources`).
   Candidates that run out of range or supplies are dropped; the rest are scored 1-5 on `config.MATRIX_CRITERIA`.
4. `app._finish_mission()` gives the plan an id and turns the science and off-limits maps into PNGs.
5. The explanation is a template (`mission._template`); the AI version comes from `mission.explain_ai` /
   `explain_stream` (`/api/mission/{id}/explain` or the stream's `explanation` event).

When an area has no landing spot, `mission.NoLandingSpot` is raised and `app._no_landing()` points to the nearest
firm ground (`mission.nearest_firm_ground`).

### 3. Gear kit: `POST /api/gear/kit`

1. `gear/api.py` calls the `recommend_gear` tool (`gear/tools.py`).
2. `gear/context.py` resolves the `MissionContext` against its archetype's defaults and records `assumptions`.
3. With a `route_request`, `gear/signals.py` runs the real planner (`app.plan`) and samples slope, firmness,
   thermal inertia, roughness, temperature and sun along the route.
4. `gear/rules.py` fires rules from those values; `gear/engine.py` merges items, assigns carriers, checks the
   22.7 kg hand-carry limit and builds the manifest; `gear/budget.py` sizes consumables and dose.
5. The page (`kit.html`) renders it. An agent can publish a kit (`publish=true`); it is saved to
   `gear/state/published_kit.json`. More in [gear/README.md](../gear/README.md).

## Module map

Owners are the people whose commits built each part (git authors: `darrens1325` Darren, `Jason-Chen10` Jason,
`Gk` Gia, `siddhilakkarsu-max` Siddhi; `Ashwin-P23` made the initial scaffold).

| File | Responsibility | Main functions | Built by |
|---|---|---|---|
| `app.py` | FastAPI app: cubes, layers, plan, find, mission and site endpoints, tile relays, static files | `Cube`, `get_cube`, `layer`, `plan`, `consumables_block`, `_walkback_round_trip`, `find`, `plan_mission(_stream)`, `build_site`, `ctx_tile` | Darren, Jason, Gia |
| `config.py` | Every tunable number and data source (see below) | `region_box`, `site_id`, `themis_ti`, `_mission_vehicle`, `season_for_ls` | Darren, Gia |
| `physics.py` | Per-pixel models: sun, slip and speed, cost, routing, terrain-aware consumables | `sun_position`, `cost_seconds_per_meter`, `best_route`, `minetti_cw`, `route_profile`, `round_trip_walk`, `path_resources`, `load_factor`, `climb_energy_kwh`, `dust_opacity`, `daily_sunlight_fraction`, `shelter_seeds` | scaffold, Gia |
| `mission.py` | Mission planner: goal to 3 candidates, landing spots, tracks, resources, decision matrix, explanations | `plan`, `tracks`, `offlimits`, `landing_mask`, `nearest_landing`, `nearest_firm_ground`, `_route_layers`, `_resources`, `explain_ai`, `explain_stream` | Darren (resource model: Gia) |
| `search.py` | Text to per-pixel criteria; AI model calls (OpenRouter or any OpenAI-compatible server) | `keyword_parse`, `ai_parse`, `ai_parse_stream`, `ai_stream`, `score_map`, `find`, `FEATURES` | Darren |
| `murray.py` | Murray Lab CTX viewer layers, HiRISE index, 3D terrain relay | `murray_layers`, `murray_features`, `murray_hirise`, `elevation_tile_bytes` | Darren |
| `build_cube.py` | Builds `cubes/<region>.npz` | `build`, `load_band`, `terrain_into_grid`, `build_minerals`, `firmness_from_ti`, `build_hires_imagery` | scaffold, Darren |
| `fetch_tracks.py` | Downloads a rover traverse | `fetch` | Darren |
| `mars_weather.py` | Reads the bundled OpenMARS / LMD grids | `weather_layer`, `wind_components`, `visible_dust_grid`, `WEATHER_LAYERS` | Jason |
| `surface_temperature.py` | 0.5 deg ground temperature simulation | `solve_temperature`, `temperature_overlay` | Jason |
| `thermal_detail.py` | 0.125 deg TES viewport simulation; rebuilds its grid | `detail_overlay`, `detail_sample`, `build` | Jason |
| `build_weather.py` | Rebuilds `thermal_data/weather.npz` (needs `blosc2`, `zstandard`, curl) | `build` | Jason |
| `mars_radiation.py` | Modeled GCR effective dose from pressure | `dose_from_pressure`, `radiation_fields`, `sample_radiation` | Jason |
| `gear/` | Gear catalog, rules, budget, agent tools, routes ([README](../gear/README.md)) | `tools.call_tool`, `engine.build_manifest`, `budget.size_consumables` | Gia |
| `gear_server.py` | Old entry point, now `from app import app as server` | - | Gia |
| `make_demo_cube.py` | Fake terrain cube for offline demos (overwrites `cubes/jezero.npz`) | `main` | scaffold |
| `tools/make_rover_glb.py`, `tools/make_mars_disk.py` | Generate the hover models and the landing-page disk | - | Darren |
| `marsmap/` | Jason's standalone MarsMap snapshot; its features were ported into the main app in #17 ([README](../marsmap/README.md)) | - | Jason |

## How `config.py` is organised

1. **Regions:** `REGIONS` (`jezero`, `jezero_hirise`, `global`), `SITES` (named places), `SITE_SIZE_DEG`,
   `region_box()`, `site_id()`, `mc_quadrangle()`.
2. **Data sources:** `SOURCES` (global, per band), `REGION_SOURCES` (tried first for Jezero), `themis_ti()`,
   `MINERALS` (CRISM parameters, thresholds and search words).
3. **Targets:** `SCIENCE_TARGETS`, `SEARCH_ZONES`.
4. **Consumables and vehicles (route planner):** `CONSUMABLE_SOURCES` (citation per number), `_SUIT_O2_SUPPLY`,
   `WALKER`, `CONSUMABLE_RESERVE`, `VEHICLE_POWER`, `VEHICLES` (nine travellers).
5. **Mission planner:** `ROVER_TRACKS`, `TRACK_RULES`, `MISSION_VEHICLES`. The crewed mission vehicles `on_foot`,
   `four_wheel` and `buggy` are built by `_mission_vehicle()` from `VEHICLES` entries `astronaut`,
   `unpressurized_rover` and `pressurized_rover` (`MISSION_VEHICLE_OF`), so change their numbers in `VEHICLES`
   only; `two_wheel` is a team estimate. `SUIT` reads the astronaut's O2. Then `SITE_HOURS`, `SEASONS` /
   `BASE_SEASONS` / `season_for_ls()`, `PRIORITIES` (cost weights, matrix boost, reserve), `MATRIX_CRITERIA`,
   `TOOLS`, `ESSENTIALS`, `LANDING_RULES`, `NASA_SITES`, `SPECIAL_REGIONS`.

`tests/test_vehicle_lists.py` checks that the shared vehicles carry the same numbers in both lists and that each
mission range fits its battery.

## Front end

| Page | Scripts and assets | What it does |
|---|---|---|
| `frontend/index.html` (globe) | inline app script; `vendor/Cesium/` (CesiumJS 1.147.0); `weather_display.js`, `weather_timeline.js`, `wind_motion.js`, `temperature_view.js`, `mars_lighting.js`; models `rover.glb`, `astronaut.glb`, `bike.glb`, `lrv.glb`, `buggy.glb`; `mars-disk.webp` (landing page), `viking-mdim.jpg` (base map) | Mission panel, map layers, sharp imagery box, Murray Lab maps, weather timeline, manual planning, consumables panel, clicked-point panel. Press A for technical details. |
| `frontend/kit.html` (gear) | `kit.js`, `kit.css`; add-ons `kit-presets.js` / `.css`, `kit-compare.js` / `.css`, `kit-pack.js` / `.css` | Gear manifest, rules, consumables budget, planner's published kit, scenarios, compare, packing list |

The globe links to the gear page from Manual planning ("Gear for this route") and from each mission card
("Gear for this mission").

## Tests

`tests/` uses the standard library `unittest`; run from the repo root:

```bash
python -m unittest discover -s tests          # 137 tests at the time of writing
```

| File | Covers |
|---|---|
| `test_gear.py`, `test_gear_ti.py`, `test_gear_persist.py`, `test_app_gear.py` | Gear catalog, rules, budget, tools, thermal-inertia rules, published-kit file, routes in `app:app` |
| `test_kit_presets.py`, `test_kit_compare.py`, `test_kit_pack.py`, `test_mer_demo.py` | Gear page add-ons (JavaScript parts run under node when it is installed, else skipped) |
| `test_cons_panel.py`, `test_walkback_o2.py` | `/api/plan` consumables keys and the O2 / battery walk-back zone |
| `test_mission_resources.py`, `test_mission_gear_link.py`, `test_vehicle_lists.py`, `test_plain_text.py` | Mission resource model, the mission-to-gear link, shared vehicle numbers, plain-text messages and the season slider |
| `test_sites.py` | Named sites, `site_<lat>_<lon>` regions and the build endpoints (no real builds) |
| `test_radiation.py` | Radiation data integrity, units, missing values and API |

`tests/_gear_state.py` points `MARSWALK_GEAR_STATE_DIR` at a temporary folder so tests never touch the real
published kit. Tests that run the planner need `cubes/jezero.npz` (the committed one).
