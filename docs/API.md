# API reference

Every HTTP route the server answers. One process serves them all: `uvicorn app:app` (or `run.bat` / `./run.sh`).
Routes live in `app.py`, `gear/api.py` (prefix `/api/gear`) and `murray.py`. FastAPI also serves its own
interactive list at http://localhost:8000/docs.

Change a route, a request field or a response field? Update this page and `CHANGELOG.md` in the same PR (see
"Keeping the docs current" in the [README](../README.md)).

## Common request body (`Conditions`)

Most `POST` routes take these fields, all optional:

| Field | Default | Meaning |
|---|---|---|
| `region` | `"jezero"` | A loaded cube: `jezero`, `jezero_hirise`, a name in `config.SITES` or `site_<lat>_<lon>` |
| `vehicle` | `"astronaut"` | Any key of `config.VEHICLES` (route planner travellers) |
| `local_hour` | `11` | Mars local solar time, 0-24 |
| `ls` | `90` | Season, solar longitude 0-360 |
| `budget_hours`, `reserve` | `4`, `0.25` | EVA time budget and the share of it held back |
| `min_sun_elev` | `10` | Warn when the sun is lower than this (deg) |
| `weights` | `{}` | Route cost weights `slope`, `sand`, `rough` (default 1 each) |
| `radiation_solar_mv`, `radiation_spatial_contrast` | `700`, `true` | Radiation layer only: 400 / 700 / 1000 MV scenario; fixed per-scenario colour bounds or the shared 12-30 µSv/h scale |

PNG overlays come back as `data:image/png;base64,...` strings with a `rect` (`west`, `south`, `east`, `north`).

## Regions, points and map layers (`app.py`)

| Method and path | Purpose | Request | Response (main fields) |
|---|---|---|---|
| `GET /api/regions` | Loaded cubes and vehicle limits | - | `regions[]` (`region`, `label`, `rect`, `size`, `bands`, `pixel_m`, `provenance`, `targets`, `minerals`), `vehicles`, `vehicle_specs` (rated hours, O2/energy capacity and rates, `source`) |
| `GET /api/pixel` | Every band value in a cube pixel | `lat` (-90..90), `lon` (-360..360), `region` | `values`, `ground`, `minerals`, `notes`, `confidence`, `source`; falls back to other cubes, then to `/api/point` |
| `GET /api/point` | Live lookup anywhere, no cube needed | `lat` (-90..90), `lon` (-360..360); NaN or out of range: 422 | `values` (elevation, slope, roughness, albedo, THEMIS day/night, air column), `ground`, `notes`, `confidence` |
| `GET /api/imagery/{region}` | Hi-res photo overlay made by `build_cube.py <region> --imagery` | - | `available`, `url`, bounds |
| `POST /api/layer/{name}` | Coloured overlay for one layer | `Conditions` | `image`, `rect`, `legend` (`name`, `unit`, `min`, `max`, `colors`), `sun`; weather layers add `grid_step_deg`, `data_range`, `wind_vectors`, `wind_field`; `radiation_dose` adds `radiation` (model label, notes, limitations, sources) |
| `POST /api/layer/{name}/sample` | Native model value under the mouse | `Conditions` + `lat`, `lon`, `detail` | `value`, `unit`, `label`, `grid_step_deg`; wind adds `toward_deg`; radiation adds `pressure_pa`, `dust_opacity`, `reason` |
| `POST /api/weather/temperature-detail` | 0.125° simulated ground temperature for the visible box | `Conditions` + `west`, `south`, `east`, `north` | `image`, `rect`, `grid_step_deg`, `source_cells`, `temperature_range` |
| `GET /api/weather/calendar` | Sol to Ls table for the season slider and timeline | - | `sols`, `ls` |
| `GET /api/weather/sources` | The reviewed weather source inventory | - | `weather_sources.csv` as a download |
| `GET /api/radiation/method` | Radiation method and provenance | - | `radiation_data/README.md` as text |

Layer names for `/api/layer/{name}`:

- any band in the cube (`elevation`, `slope`, `aspect`, `roughness`, `firmness`, `thermal_inertia`, `albedo`,
  `imagery`, `minerals`, `science`, `air_column_vs_gale`, `themis_night`, `themis_day`, and the CRISM mineral bands
  in `config.MINERALS`);
- computed: `suitability`, `illumination`, `cost`, `shelter`, `temperature` (region), `global_temperature`;
- global weather (`mars_weather.WEATHER_LAYERS`): `openmars_surface_temperature`, `air_temperature`,
  `surface_pressure`, `wind_speed`, `wind_direction`, `dust_opacity`;
- `radiation_dose` (`mars_radiation.py`).

`/sample` answers for `temperature`, `global_temperature`, the weather layers and `radiation_dose` only.

## Planning (`app.py`)

| Method and path | Purpose | Request | Response (main fields) |
|---|---|---|---|
| `POST /api/plan` | Manual route from base to target | `Conditions` + `base`, `target` (`{lat, lon}`) | `route[]` (per point `lat`, `lon`, `d`, `t`, `elev`, `slope`, `ti`, `firm`, `o2_kg`, `energy_kwh`), `stats` (distance, times, slopes, `within_budget` and the consumables fields below), `warnings`, `explanation`, `walkback_image`, `walkback_basis`, `walkback_area_km2`, `walkback_reserve_pct`, `walkback_o2_usable_kg`, `walkback_energy_usable_kwh` |
| `POST /api/find` | Targets matching a text description | `Conditions` + `query`, `base?`, `focus?`, `count` (1-10) | `matches[]` (`lat`, `lon`, `score`, `why`, `within_budget`), `criteria`, `parser` (`keywords` or `ai`), `not_understood`, `notes`, `heatmap` |
| `POST /api/assistant` | The chat assistant (Helmut). The AI decides the reply, suggestions and map actions; the built-in keyword rules answer only when no AI is configured or reachable | `messages[]` (up to 40 `{role, text}`), `state`, `memo` | `reply`, `chips`, `actions[]` (validated), `memo`, `source` (`ai` or `rules`), `wait_for_mission` |
| `GET /api/mission/options` | Menus for the mission panel | - | `vehicles` (`label`, `max_slope`, `range_km`), `seasons`, `priorities`, `criteria` (label and weight) |
| `POST /api/mission` | Goal to 3 candidate missions and a recommendation | `goal`, `vehicle` (`config.MISSION_VEHICLES`), `season` or `ls`, `priority`, `green_only`, `region` | `settings`, `tools`, `candidates[]` (`route`, `resources`, `card`, `scores`, `total`, `rank`), `dropped`, `notes`, `tracks`, `explanation`, `science_image`, `offlimits_image`, `id` |
| `POST /api/mission/stream` | The same plan as server-sent events | as `/api/mission` | events `status`, `ai` (`phase` goal / explain, `kind` reasoning / content, `text`), `result` (the plan), `explanation`, `note`, `error`, `done` |
| `POST /api/mission/{id}/explain` | AI-written explanation of a plan | - | `explanation`, `source` (`ai` or `template`) |
| `GET /api/tracks` | Perseverance drives classed green / yellow, red off-limits terrain | `region`, `vehicle` (mission key) | `rover`, `source`, `km`, `segments[]`, `offlimits_image`, `offlimits_pct` |

Consumables fields in `/api/plan` `stats` (`consumables_block()` in `app.py`): `o2_used_kg`, `o2_max_kg`, `o2_pct`,
`o2_usable_kg`, `o2_flat_kg`, `terrain_o2_factor`, `slope_o2_factor`, `o2_flat_pace_h`, `energy_used_kwh`,
`energy_max_kwh`, `energy_pct`, `energy_usable_kwh`, `climb_kwh`, `elevation_gain_m`, `elevation_loss_m`,
`reserve_pct`, `power_source`, `dust_opacity`, `sunlight_pct`, `solar_kwh_per_sol`, `recharge_sols`, `recharge_h`,
`endurance_h`, `max_range_km`, `limiting_factor`. The front end's Consumables panel reads these keys
(`tests/test_cons_panel.py` checks them).

Server messages may be `"plain text | technical detail"`: the page shows the part after ` | ` only in its
advanced view (press A).

## Planning anywhere on Mars (`app.py`)

| Method and path | Purpose | Request | Response |
|---|---|---|---|
| `GET /api/sites` | Named places in `config.SITES` | - | `size_deg`, `sites[]` (`site`, `label`, `lat`, `lon`, `ready`, `building`) |
| `POST /api/sites/build` | Load the area around a point (reuses a loaded cube that covers it) | `{"lat", "lon"}` or `{"site": "gale"}` | `region`, `label`, `status` (`terrain`, `minerals`, `done`, `failed`, `not built`), `ready`, `reused`; at most 2 builds at once (else 429) |
| `GET /api/sites/build/{region}` | Build progress | - | `status`, `ready`, `seconds`, `crism_done`, `crism_total`, `log` |

## Imagery and tiles (`app.py`)

| Method and path | Purpose |
|---|---|
| `GET /tiles/{layer}/{z}/{y}/{x}.jpg` | Relay of NASA Mars Trek WMTS tiles (Trek sends no CORS header); the globe uses the Viking MDIM 2.1 mosaic |
| `GET /ctxtiles/{z}/{y}/{x}.jpg` | Murray Lab 5 m CTX tile coloured with Viking colours, cached in `cubes/tilecache/` |
| `POST /api/prefetch` / `GET /api/prefetch` | Download every `/ctxtiles` tile in a box (`west`, `south`, `east`, `north`, `max_level`, levels 8-12) / progress (`done`, `total`, `running`) |
| `GET /cubes/...` | Static files in `cubes/` (photo overlays) |
| `GET /` | The front end (`frontend/`, e.g. `/index.html`, `/kit.html`) |

## Murray Lab maps (`murray.py`)

| Method and path | Purpose |
|---|---|
| `GET /api/murray/layers` | The Murray Lab CTX viewer's layers (tiles, terrain, GeoJSON, HiRISE) with URLs and credits |
| `GET /murray/features/{name}.geojson` | Slimmed, cached feature layers: `m2020`, `msl`, `names`, `craters`, `quads` |
| `GET /murray/hirise?west=&south=&east=&north=&limit=` | HiRISE footprints in a box (`total`, `truncated`, `features`) |
| `GET /murray/hirise/at?lat=&lon=` | HiRISE observations covering a point |
| `GET /murray/quad/at?lat=&lon=` | The CTX mosaic tile at a point, with its download link |
| `GET /murray/elevation/` and `/murray/elevation/tile/{z}/{y}/{x}` | 3D terrain relay (Esri MDEM200M, MOLA/HRSC 200 m) for Cesium; tiles cached in `cubes/murraycache/` |

## Gear (`gear/api.py`)

Details, the `MissionContext` fields and the agent tools are in [gear/README.md](../gear/README.md).

| Method and path | Purpose | Request | Response |
|---|---|---|---|
| `GET /api/gear/tools?format=anthropic\|openai` | Tool definitions for a planning agent | - | `format`, `tools` |
| `POST /api/gear/tools/{name}` | Call one tool | the tool's arguments as the JSON body | the tool's result (errors as 400 / 404) |
| `POST /api/gear/kit` | The gear page's call: full manifest | `context` (`MissionContext`), `adjustments?` | `summary`, `items`, `groups`, `rules`, `carry`, `mass`, `budget`, `warnings`, `assumptions`, `thin_evidence`, `adjustments` |
| `GET /api/gear/published` | The kit the agent last published | - | `manifest`, `published_at`, `note`, `source` (`memory`, `disk` or `null`) |
| `DELETE /api/gear/published` | Forget the published kit (memory and file) | - | same shape, emptied |
| `GET /api/gear/catalog` | Every catalog item | - | `categories`, `items`, `confidence`, `count` |
| `GET /api/gear/archetypes` | Mission archetypes and defaults | - | `archetypes` |
| `GET /api/gear/rules` | Every rule and threshold | - | the `list_gear_rules` tool result |
