# Changelog

Notable changes to Marswalk Planner. Entries are grouped by session; this is a hackathon
project, so dates matter more than semantic version numbers.

## [Unreleased] - 2026-11-14, more vehicles

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

## [Unreleased] - 2026-11-14, gear system

Branch `feat/Gk`. Builds on `MISSION_EQUIPMENT_RESEARCH.md`.

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
