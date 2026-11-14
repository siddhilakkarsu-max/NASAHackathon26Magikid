# Changelog

Notable changes to Marswalk Planner. Entries are grouped by session; this is a hackathon
project, so dates matter more than semantic version numbers.

## [Unreleased] - 2026-11-14

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
