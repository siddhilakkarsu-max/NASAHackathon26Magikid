# Changelog

> **Frozen.** New changes go in `docs/changelog/`, one file per merged pull request (see `AGENTS.md`).
> This file keeps the history up to PR #32.

Notable changes to Marswalk Planner. Entries are grouped by session; this is a hackathon
project, so dates matter more than semantic version numbers.

## [Unreleased] - 2026-11-15, game: complete vehicle models

Branch `feat/Gk`.

### Fixed

- **Half the rover was missing while riding** (`frontend/game.html`). The riding view used a separate front-only
  "cockpit" model, so there were no seats or rear, and it did not match the parked vehicle. Each vehicle is now one
  complete model (`g3VehModel`) drawn around the driver's eye when riding and placed on the ground when parked.

### Changed

- Open rover: four wheels with hubs and fenders, two seats, console with display and hand controller, foot rest,
  headlights, TV camera, tool pallet; the dish moved behind the driver, out of the forward view.
- Bike: frame, fork, handlebar with grips and levers, display, headlight, fenders, seat, battery, panniers.
- Pressurised rover: six wheels, nose, cabin with window frame, dash, yoke and two seats, rear module, roof gear.
- Ground rings are thinner and their fill fainter; the parked vehicle has a ring and label but no light pillar.
- Test hook `window.__MW.look(yawDeg, pitchDeg)`. 1 test.

### Verification

- Headless Chrome screenshots: riding view forward, down, left and right for all three vehicles; the parked rover
  and bike from three sides. Autopilot completes all 14 baked routes.

### Limits

- Models are flat-shaded boxes, beams and cylinders built in code. Wheels do not turn and the steering does not
  move. The pressurised rover cannot be left, so it is never seen from outside.

## [Unreleased] - 2026-11-15, game: leaderboard, callsigns and a "mission ready" button

Branch `feat/Gk`.

### Added

- **Leaderboard and callsigns** (`leaderboard.py`, routes `/api/game/players`, `/api/game/scores`,
  `/api/game/leaderboard`; one include line in `app.py`). A player claims a callsign on the game's title screen;
  successful missions flown by hand at normal speed are posted; the end screen shows the rank and top ten for that
  mission and route, the title screen the overall board. Stored in `game_state/leaderboard.sqlite3` (not in git,
  folder set by `MARSWALK_GAME_STATE_DIR`). Browser storage: `marswalk.game.player`.
- **"Mission ready · Play" button** (`frontend/game-launch.js`). A green pulsing button appears at the top right
  of the planner map when a plan is ready and opens the selected route in the game. Hidden while planning.
- 8 tests (174 total): `tests/test_leaderboard.py` (7) and one in `tests/test_game.py`.

### Verification

- Headless Chrome against the local server: claim a callsign, finish a mission by hand, see the rank and board;
  duplicate and invalid callsigns refused with a message; autopilot runs not posted. On the planner: the button is
  hidden before and during planning, appears when the plan is ready, overlaps no other control, and launches the
  game with the selected route.

### Limits

- Scores come from the browser and can be faked; the server checks ranges, the callsign token and a 4 s gap.
- A callsign has no password and cannot be recovered on another device. No name filter beyond the character rule,
  no admin page. Each server keeps its own board.

## [Unreleased] - 2026-11-15, game: vehicle handling, dismounting and a sample at B

Branch `feat/Gk`.

### Changed

- **Vehicles drive like vehicles** (`frontend/game.html`). W accelerates, S brakes and reverses, A / D steer; the
  vehicle carries momentum, steering needs speed, loose ground gives less grip, and the cockpit stays fixed to the
  vehicle while the mouse looks around.
- **Dismount and mount** with V on the bike and the open rover. The parked vehicle is a model in the world; on
  foot the crew moves and breathes at walking rates and the vehicle draws only its hotel load. Site work steps the
  crew off automatically.

### Fixed

- **Nothing to sample at B.** On several plans every sampling spot lay 110 to 640 m from B, so pressing E at the
  B marker did nothing. The nearest spot is now placed on B.

### Verification

- Headless Chrome: drive, steer, reverse, dismount, "too far to mount", remount and sampling at B on the open
  rover; bike and pressurised rover load without errors; autopilot completes all 14 baked routes.
- 1 test (166 total).

### Limits

- Handling is a feel model, not vehicle dynamics. Not driven by hand with a real mouse and keyboard.

## [Unreleased] - 2026-11-15, the game goes first-person 3D

Branch `feat/Gk`.

### Changed

- **First-person 3D view** (`frontend/game.html`, section 12b, raw WebGL, no libraries). The player sees Mars
  through the visor or over the vehicle's hood: W / S move along the view, A / D strafe, mouse or arrow keys look.
  The planned route is a chevron line on the ground coloured by the plan's risk; light pillars mark A, B, sampling
  spots, shelters and the turn-back point; off-limits ground is hatched red; data layers paint the terrain. Storms
  close the view in, night uses a headlamp. The simulation, tools, hazards and planner hand-off are unchanged.
- **Lighter dialogue.** Blocking Houston cutscenes are cut to one or two lines around the mission and become radio
  calls during it; the intro plays from its button only. `?story=1` restores the full scripts.

- **Helmet AR HUD.** The helmet rim frames the view and the HUD panels sit inside it, stacked so they do not
  overlap. The visor reacts to damage, low oxygen, storms, cold and lost signal.
- **Easier to pick up.** Missions start facing down the route, the path arrows point the way you travel, a guide
  light floats ahead on the route, one plain-language hint shows at a time, and Space hops in Mars gravity.
- **Models.** Lander with legs, ladder, hatch and solar wings; science station at B; rover with wheels, fenders,
  console, dish and camera; bike handlebars and front wheel; cabin window frame and dash; suit forearms and gloves.

### Added

- URL params `view=2d` (top-down renderer, also the fallback without WebGL), `story=1`, `gq=low`.
- A heading pill with an arrow to the next point on the route.
- 2 tests (149 total).

### Verification

- Headless Chrome: autopilot completes all 14 baked routes in 3D from `file://`; all six death causes fire; manual
  walking and strafing work; 59-60 frames per second on Intel UHD.

### Limits

- Terrain shape is scenery generated over the game's hazard fields, not the real Jezero elevation.
- Clicking the ground for point values needs `view=2d`. Not checked on a phone; mouse capture not exercised by hand.
- Live-planning and hand-off checks were not re-run on the 3D build (their code did not change).
## [Unreleased] - 2026-11-14, planner controls and game integration

- Use one global Map view selector for imagery, terrain, weather and radiation;
  keep annotation overlays independent and remove the OpenMARS reference option.
- Prevent selected page text from canceling time-slider drags after one step.
- Show the full published CTX photo grid and correct dateline tiles and lookup.
- Integrate the teammate game into a collapsed section and Mission results action.
  Preserve the saved route, region and exact season when launching it.
- Place game imagery using its actual regional bounds and prevent canceled planning
  responses from replacing a newly chosen mission.
- Add map-selection, native slider and game-handoff browser regression checks.

## [Unreleased] - 2026-11-14, survival game that plays the plan

Branch `feat/Gk`.

### Added

- **Marswalk: Survive the Route** (`frontend/game.html`, one self-contained file, served at `/game.html`). The
  player follows the planned route A to B and back with the plan's tools, oxygen, battery and reserve; six ways to
  die (`oxygen`, `battery`, `integrity`, `tools`, `offlimits`, `storm`); Houston cutscenes with the signal delay.
  The briefing shows the planner's settings, tools, decision matrix, candidate cards, dropped routes and notes;
  layers, weather, rover tracks and clicked-point values are in a drawer. Plans live through
  `/api/mission/stream`, or runs offline on five baked real plans.
- **Play buttons** (`frontend/game-launch.js`). `kit.html` loads it and gets a Play button that opens the game with
  the kit form's vehicle, season, region and goals. On the planner it adds "Play this mission", which saves the
  plan and selected route to `localStorage["marswalk.game.mission"]` and opens `game.html?src=planner`.
- URL params: `baked`, `cand`, `difficulty`, `src=planner`, `goal`, `vehicle`, `season`, `priority`, `green_only`,
  `region`, `autopilot`, `speed`, `skip`, `mute`, `seed`, `touch`. Storage: `marswalk.game.mission`,
  `marswalk.game.best`, `marswalk.game.last`, `marswalk.game.prefs`.
- `docs/game/README.md` (player guide and hand-over) and `docs/game/smoke_test.js` (headless autopilot run).
- 10 tests (136 total), `tests/test_game.py`. One fails if the game's vehicle table drifts from
  `config.MISSION_VEHICLES`.

### Verification

- Headless Chrome: autopilot completes all 14 baked routes served and from `file://`; all six death causes fire;
  42 UI checks and 16 planning and hand-off checks pass; no console errors; 59-60 frames per second on Intel UHD.

### Limits

- `frontend/index.html` is not edited, so the planner has no Play button until
  `<script src="/game-launch.js" defer></script>` is added to its `<head>`.
- Terrain away from the planned corridor is generated. Storms, breaches, tool charges and scoring are game rules,
  not planner output. Time is compressed: a round trip takes about 2.5 to 6.5 minutes.
- Baked missions and the embedded weather table are Jezero only. Not checked on a phone, Firefox or Safari.

## [Unreleased] - 2026-11-14, gear page, app hookup and run scripts

PRs #9 to #16 (merged just after midnight UTC, 2026-11-15).

### Changed

- **One server for everything (#10).** `app.py` includes the gear router, so `uvicorn app:app` serves the planner,
  `/api/gear/*` and `/kit.html`. `gear_server.py` is now `from app import app as server`, kept so old commands work.
- **Loose ground from measured thermal inertia (#11).** Rules T1 and T4 judge loose ground by thermal inertia below
  300 when the route has at least 3 measured pixels, otherwise by night-IR firmness as before. 82 % of the Jezero
  cube's measured pixels are TI 150-300 (sand), so T4 now fires on most Jezero routes.

### Added

- "Gear for this route" link under Manual planning in `frontend/index.html`. It opens `kit.html` with the
  traverse archetype and the planner's region, vehicle, base and target (#10).
- **Published kit survives a restart (#9).** Saved to `gear/state/published_kit.json` (folder set by
  `MARSWALK_GEAR_STATE_DIR`) and restored at start. `GET /api/gear/published` gains `source` (`memory`, `disk` or
  `null`); `DELETE /api/gear/published` clears it. `gear/state/.gitignore` keeps the file out of git.
- Route terrain signals `ti_mean`, `ti_min`, `ti_samples`, `dust_fraction` (TI < 150), `sand_fraction` (150-300) and
  `ti_loose_fraction` (< 300); thresholds `ti_dust` and `ti_sand`; source `putzig_ti`. New rule **T13** "Fine dust
  along the route" fires when a fifth of the route is fine dust: suit dust removal, HEPA filtration and an air
  monitor, plus array cleaning for solar vehicles (#11).
- **`run.bat` (Windows) and `run.sh` (macOS/Linux) (#12).** Find Python 3.10+, create `.venv`, reinstall only when
  `requirements.txt` changes (`.venv/.requirements.sha256`), retry without `rasterio` if the full install fails,
  start the server and open the browser. Port as an argument or `PORT`; a busy port gets a message and a free
  port suggestion. Flags `--reload`, `--no-browser`, `--help`; env `MARSWALK_PYTHON`, `MARSWALK_NO_PAUSE` (Windows).
- **Compare kits (#14).** "Pin for comparison" keeps the current kit (in `sessionStorage`); change the mission and
  "Compared with pinned kit" lists the differences. Debug params `?compare=<archetype>`,
  `?compare_vehicle=<vehicle>`. `frontend/kit-compare.js`, `kit-compare.css`.
- **Packing list, CSV and link (#15).** Packing-list mode with tick boxes saved in `localStorage` per kit,
  "Clear ticks", and empty boxes in print. "Download CSV" (UTF-8 with BOM, CRLF) and "Copy link". Debug params
  `?pack=1`, `?packdemo=1`. `frontend/kit-pack.js`, `kit-pack.css`.
- **Scenarios and season (#16).** Seven one-click presets (`delta-walk`, `delta-dust`, `crew-rover`, `opportunity`,
  `spirit`, `cave`, `long-base`), shareable as `?preset=<id>`. A Season (Ls) input sent as `route_request.ls`,
  also `?ls=`. `frontend/kit-presets.js`, `kit-presets.css`.
- 28 tests (78 total).
- **Mars sunlight on the globe (#13, Jason):** atmosphere and solar lighting that follow the selected region's
  local time ("Sunlight and atmosphere" toggle), with a cursor spotlight that reveals the night side
  (`frontend/mars_lighting.js`).

## [Unreleased] - 2026-11-14, terrain, load and battery realism

PR #8 (Gia). From the team's resource research (Gia's section of the planning doc).

### Changed

- **Suit oxygen now uses NASA's Mars design basis:** 0.114 kg/h and 0.912 kg carried (1.9 g/min over 8 h,
  SBIR topic EVA.2.S26B), replacing 0.085 kg/h and 0.68 kg. Rate and capacity rose together, so the suit still
  lasts 8 h and the mission planner's percentages, turnaround times and rankings are unchanged.
- `physics.endurance()` is removed; `consumables_block()` in `app.py` costs the planned route directly.
- `max_range_km` now uses what is usable after the reserve, at the route's terrain.

### Added

- **Oxygen follows the terrain.** The return leg walks the route in reverse, and effort per metre follows
  Minetti et al. 2002, so a climb out costs more than the descent back saves. New stats: `slope_o2_factor`,
  `terrain_o2_factor`, `o2_flat_kg`, `o2_flat_pace_h`, `elevation_gain_m`, `elevation_loss_m`.
- **Weight counts.** `physics.load_factor()` charges carried mass in proportion to body + suit + load. The gear
  budget applies the kit's hand-carried load to the route's oxygen and warns if it eats into the reserve.
- **Vehicles pay for climbing:** `climb_kwh`, the energy to lift the vehicle (m g h), a lower bound.
- **Reserve:** 15 % of every supply held back, 20 % in the dust-storm season (Ls 180-330), with warnings when a
  route cuts into it. `o2_usable_kg`, `energy_usable_kwh`, `reserve_pct`.
- **Dust and sunlight:** dust opacity from the team's weather data at the route, turned into the share of a
  sol's direct sunlight on a panel, as in the temperature model. `sunlight_pct`, `dust_opacity`,
  `solar_kwh_per_sol`, `recharge_sols` for solar rovers, `recharge_h` for the crew rover (2:1 charge-to-drive),
  and a warning when dust blocks most of the light. Nuclear rovers are unaffected. `power_source` says which.
- `VEHICLE_POWER`, `WALKER` and `CONSUMABLE_RESERVE` in `config.py`.
- 9 tests (50 total).

### Measured, landing site to the western delta (4.8 km, climbs 141 m)

| | Ls 90 | Ls 250 (dust season) |
|---|---|---|
| Astronaut O2 | 0.76 of 0.91 kg, fits after the 15 % reserve | same 0.76 kg, but only 0.73 usable after 20 % |
| Crew rover | 5.35 kWh incl. 0.62 kWh climbing; 7 h to recharge | same energy; 38 h to recharge at 13 % sunlight |
| Perseverance | unaffected by dust (nuclear) | unaffected |

### Limits

- Minetti measured unsuited people in Earth gravity; only the ratio to flat ground is used.
- Body mass (80 kg) is an assumption; the reserve and 2:1 recharge ratio are team research figures, not NASA ones.
- Sunlight counts direct light only, so dust effects are the pessimistic end.

## [Unreleased] - 2026-11-14, AI reasoning stream and MarsMap snapshot

PRs #6 and #7.

### Added

- **Watch the AI think (#6, Darren).** `POST /api/mission/stream` sends the plan as server-sent events with the
  model's reasoning and answer live, for reading the goal and for explaining the choice; the mission panel fills
  "AI reasoning" boxes while the template summary shows. `AI_REASONING` and `AI_THINK_SECONDS` (default 40) control
  the thinking. The non-streaming routes are unchanged.
- **`marsmap/` (#7, Jason):** a snapshot of Jason's standalone MarsMap project (its own app, cube builder and page),
  kept for reference; its features were ported into the main app in #17.

### Changed

- The mission summary shows the decision-matrix total unrounded (#6, Darren).

## [Unreleased] - 2026-11-14, more vehicles

PR #5 (Gia).

### Added

- Five vehicles in the route planner's `VEHICLES` (`config.py`), bringing it to nine. Each number comes from the
  mission's published figures, with a `CONSUMABLE_SOURCES` entry saying where.

| Key | Vehicle | Top speed | Max slope | Energy model |
|---|---|---|---|---|
| `unpressurized_rover` | Open crew rover (Apollo LRV-class) | 10 km/h | 20 deg | 8.7 kWh battery, 0.095 kWh/km, plus suit oxygen |
| `sojourner` | Sojourner (Mars Pathfinder, 1997) | 1 cm/s | 30 deg | none published |
| `mer` | Spirit / Opportunity (2004) | 5 cm/s | 30 deg | 0.9 kWh per sol, 100 W to drive |
| `zhurong` | Zhurong (Tianwen-1, 2021) | 200 m/h | 20 deg | none published |
| `rosalind_franklin` | Rosalind Franklin (ExoMars, launch 2028) | 100 m/h | 20 deg | none published |

- Where no driving load has been published, the vehicle has no energy model and is limited by its rated window
  only, rather than carrying invented numbers.
- Matching gear catalog items. The gear rules treat the open rover as crewed (tools ride on it) and suited
  (rule S1 checks its crew's oxygen at NASA's design rate). `list_mission_archetypes` now reads the vehicle
  list from `config.py`.
- 6 tests (41 total).

### Not added

- Ingenuity and other helicopters: the planner routes over ground slope, so a flying vehicle cannot be costed
  properly. Ingenuity stays in the gear catalog as an aerial scout.

## [Unreleased] - 2026-11-14, mission planner, AI search, surface temperature and weather

PRs #2 and #4.

### Added

- **Find a target by description (#2, Darren).** `search.py` and `POST /api/find`: "valley with clay" becomes
  per-pixel criteria; words the keyword parser doesn't know go to a free OpenRouter model or any
  OpenAI-compatible server such as Ollama.
- **Mission planner (#2, Darren).** `mission.py` and `POST /api/mission`, `GET /api/mission/options`,
  `POST /api/mission/{id}/explain`, `GET /api/tracks`: goal, vehicle, season and priority to 3 destinations with
  safe landing spots, routes on a cost map with Perseverance's real drives as green / yellow tracks, a round-trip
  oxygen / battery check, a decision matrix and an explanation. `fetch_tracks.py` downloads the traverse.
- **Minerals and ground firmness (#2, Darren):** CRISM mineral bands (clay, carbonate, olivine, pyroxene, sulfate,
  hydrated silica, water-bearing) from targeted observations and the map tile via PDS ODE, and THEMIS thermal
  inertia (Zenodo 23527756) for firmness. The Jezero cube was rebuilt at 512 px/deg on the CTX 20 m DEM.
- **Simulated surface temperature (#4, Jason)** from TES albedo and thermal inertia (`surface_temperature.py`),
  shown on a full Mars globe, with 0.125° detail for the visible area (`thermal_detail.py`,
  `POST /api/weather/temperature-detail`).
- **Global weather (#4, Jason):** OpenMARS air temperature, pressure, winds and ground-temperature reference, LMD
  dust opacity (`mars_weather.py`, `build_weather.py`), animated wind arrows, a weather timeline by sol
  (`GET /api/weather/calendar`), hover values (`POST /api/layer/{name}/sample`), a Jezero check against MEDA and the
  reviewed source list (`weather_sources.csv`, `GET /api/weather/sources`). CesiumJS 1.147.0 is now bundled.

## [Unreleased] - 2026-11-14, gear system

PR #3 (Gia). Branch `feat/Gk`. Builds on `MISSION_EQUIPMENT_RESEARCH.md`.

### Added

- **`gear/` package: the tool system for the planning agent.** A catalog of 99 items, 37 rules, a consumables
  and dose budget, and eight typed tools (`recommend_gear`, `get_route_context`, `size_consumables`,
  `search_gear_catalog`, `get_gear_item`, `list_gear_rules`, `check_carry_load`, `list_mission_archetypes`).
  Tool definitions come out in Anthropic or OpenAI shape from `GET /api/gear/tools`, and `call_tool()` never
  raises. See `gear/README.md`.
- Every item and rule carries a source and an evidence tag (verified, published, excerpt, inferred, none).
  Items with no published mass leave it blank, and totals say they are lower bounds.
- Rules read what the planner already computes (round-trip hours, oxygen, slope, loose-ground share, roughness,
  temperature, sun) and add gear for it. A rule fires from a route's real terrain, not from guesses.
- An agent can add or drop items with a stated reason, and publish the result to the page.
- `frontend/kit.html`, `kit.css`, `kit.js`: the gear manifest page. Rules table with the value that tripped each,
  filterable manifest grouped by category, expandable rows with reasons and source links, consumables with
  formulas, an evidence summary, a "Planner's kit" tab that follows what the agent publishes, and a print view.
  Deep links: `kit.html?rule=S2`, `kit.html?tab=published`.
- `gear_server.py`: runs the planner with the gear routes without editing `app.py`.
- **Perseverance** added to `VEHICLES` in `config.py` (top speed about 152 m/h, 30 degree tilt limit, same MMRTG
  energy numbers as the Curiosity-class rover). It appears in the planner's vehicle list automatically.
- `tests/test_gear.py`: 35 tests (`python -m unittest discover -s tests`).

### Found while building

- At NASA's Mars suit design rate (0.114 kg/h) the planner's 0.68 kg astronaut oxygen lasts 6.0 h, not 8 h. Rule
  S1 flags round trips that fit at the planner's rate but not at NASA's. The planner's own numbers are unchanged.

## [Unreleased] - 2026-11-14, consumables

Branch `feat/Gk`, feature commit `7146cda`, PR #1 (+314 / -13 across 5 files; this changelog
added afterwards on the same branch).

### Added

**Consumables tracking on every plan**

- `physics.endurance()` costs a leg in O2 (suited astronaut) or energy (rovers), derived from the
  route's own crossing time. A slow rocky detour therefore costs more breathing time and more idle
  power without needing a second terrain term.
- Round-trip consumption reported against capacity: `0.28 / 0.68 kg O2 (41 %)`.
- `limiting_factor` reports which of the vehicle's own limits runs out first: `oxygen`, `energy`,
  or `rated`. It deliberately ignores the user's time budget, which is reported separately as
  `within_budget` - a trip using 41 % of its O2 is not labelled "time budget".
- `max_range_km`: the furthest one-way distance still walkable out *and* back on a full load at
  that route's pace.
- `endurance_h` and `rated_hours` per vehicle, plus `vehicle_specs` on `/api/regions` so the front
  end never hardcodes a constant.
- Capacity warnings, with the small rover pointing at the crew rover instead of only failing.

**Consumables panel (front end)**

- Spec line per traveller: `O2 0.085 kg/h - 0.68 kg carried - 8.0 h rated`.
- Labelled progress bars with an over-capacity red state and a binding-limit chip.
- `999+ %` clamp, so a legitimate 1061 % overshoot reads as "wrong vehicle" rather than as a
  broken number.
- The EVA budget slider now clamps to the selected vehicle's rated endurance; its range was
  widened from 8 h to 12 h to fit the crew rover.

### Changed

- `plan()` returns nine additional `stats` fields and an explanation sentence naming consumption
  and the binding limit.
- `config.py`: every `VEHICLES` entry gained `rated_hours`, `consumable_source` and `consumables`.
  A new `CONSUMABLE_SOURCES` map ties each constant to its citation.
- `README.md`: consumables model, API fields, honest-limits entries and an ownership row.

### Corrected before commit

Six defects were caught in review and fixed before `7146cda`; none of them ever shipped.

- `limiting_factor` compared capacity against the user's budget, mislabelling a 41 %-O2 trip as
  "time budget".
- `.capitalize()` mangled `O2` into `o2` in explanation text.
- A 1061 % energy overshoot was attributed to `rated endurance`.
- The readout went stale when the base or target moved after planning.
- The front end's label map still carried a dead `time` key.
- A redundant `trip_h` field and a brittle label-string check were removed in favour of the
  vehicle key.

### Constants and provenance

| Traveller | Modelled limit | Provenance |
| --- | --- | --- |
| Astronaut on foot | 0.085 kg/h O2, 0.68 kg carried, 8 h rated | NASA ALS Baseline Values & Assumptions (JSC-47804) O2 rate; xEMU 8 h endurance |
| Robotic rover (Curiosity-class) | 2.5 kWh, 150-500 W load, 8 h rated | NASA/JPL MSL MMRTG figures |
| Pressurized crew rover | 20 kWh, 1.5 kW idle, 12 h rated | Engineering estimate - labelled as such in the UI and README |

Deliberately omitted rather than invented: suit battery capacity and the pressurized cabin's O2
supply, neither of which had a figure that could be sourced.

### Measured on the demo cube

Base = landing site, target 2.06 km out, 4 h budget, Ls 90.

| Traveller | Consumption | Binding limit | Round trip |
| --- | --- | --- | --- |
| Astronaut | 0.28 / 0.68 kg O2 (41 %) | oxygen | 3.25 h - over the usable 3.0 h |
| Pressurized rover | 2.12 / 20 kWh (11 %) | energy | 1.08 h - within budget |
| Curiosity-class rover | 26.53 / 2.50 kWh (1061 %) | energy | 85.5 h |

At 23 km out with an 8 h budget: astronaut 374 % of O2, crew rover 101 % of energy.

### Verification

- `POST /api/plan` through FastAPI's `TestClient` for 3 vehicles x 2 distances, asserting that
  every documented `stats` key is present, that an O2 vehicle never emits energy figures (and
  vice versa), and that `limiting_factor` always names a real model.
- `node --check` on the extracted inline script - parses clean.
- All 20 `$("id")` references in the script resolve against the markup.
- `json.dumps` on every response, confirming no numpy types reach the wire.

### Known limitations

- The pressurized rover's loads are engineering estimates, not published NASA figures.
- Routing is still time-based: an over-capacity trip is drawn and flagged, not refused.
- The panel was verified structurally, not reviewed visually in a browser.

### Tooling

- Forked to `anh-gl-nguyen1762`, cloned locally, branched `feat/Gk`, `upstream` remote added for
  syncing with the team.
- Local `.venv`, gitignored: numpy 2.5.4, scipy 1.18.1, scikit-image 0.26.0, fastapi 0.163.0,
  uvicorn 0.54.0, pillow 13.0.0, matplotlib 3.11.2, httpx 0.28.1.

## 2026-11-14, starting point

Direct commits to `main`, before the PR workflow.

### Added

- The project scaffold: `app.py` (FastAPI back end), `build_cube.py`, `config.py`, `physics.py`,
  `make_demo_cube.py`, `frontend/index.html` (Cesium globe), the first `cubes/jezero.npz` and the README
  (Ashwin-P23).
- `AGENTS.md`, the team's git workflow for AI agents (Siddhi).
