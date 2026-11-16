# Results, planner handoff and database audit — 2026-11-15

The results board now compares measured driving simulations with the player's gameplay clock. The old
13-minute planner travel estimate was being displayed alongside roughly one minute of compressed gameplay.
The AI now drives both polylines through `simStep`, including acceleration, steering, grip and hazards, using
the player's vehicle, difficulty, seed and time calibration. It stops at the sampling interaction radius at B.
No sampling duration is added to AI driving. Failed runs never receive an invented faster value.

The board has four time rows, oxygen, electrical energy, distance and cost directly below distance. Both
mission-clock rows were removed. Labels and numbers are 20–26 px; model inputs remain separately expandable.
Physical consumption/cost estimates still use simulated surface hours internally and retain the NASA links
and explicit user-entered USD rates.

The green Play Route action carries the saved plan ID and selected candidate in the URL, alongside the exact
mission handoff. Blocked storage restores that plan from the backend; failed restoration cannot silently
generate a replacement. Play requests pointer lock during the click gesture and focuses the game canvas.

The ground-firmness editor requests the visible rectangle from the existing planner cube. Cropping before
downsampling preserves local native pixels. Finer saved data takes precedence over coarser regional data.
Unknown observations remain unknown, and the existing satellite imagery is more visible under the overlay.
These are thermal/material estimates, not measurements of soil strength or individual rocks. The existing
3D scenery remains the game's procedural rendering calibrated from the selected planner mission.

## Headless checks

- Actual AI driver: all 14 baked routes reached B; repeated seed/route produced the same time; reported time
  equals the executed 30 Hz ticks, not the planner estimate.
- Normal keyboard drive against an isolated API: player total **58.133 s**, driving **42.400 s**; AI on that
  route **40.033 s**. AI reference was also **40.033 s** because this run used the unedited reference route.
  One full sample at B completed the mission; explicit Submit stored route rank 1. No browser/API errors.
- Real planner assistant → midday → pressurized rover → green Play Route retained the exact goal, vehicle,
  time, mission ID and route. Play captured the mouse; W moved immediately without Escape/Resume.
- Planner editor: original reference preserved through edit/apply; drag/undo/cancel; satellite/topography;
  desktop, tablet and phone layouts. No browser/API errors.
- Results regression: time rows, readability, unit conversions, NASA cabin oxygen estimate, invalid/missing
  rates, excluded resources, local storage failure and phone layout.
- Map regression: stale responses, dateline coordinates, geographic aspect, validation retry, material
  classes, unknown areas, finer saved observations and regional fallback.
- 18 async start/resume/failure × pause/map/leaderboard/blur regressions passed.
- Route tracking: delayed ACK coalescing, final pause packet, lost-ACK recovery and ranked resume passed.
- Launcher integration and exact candidate handoff passed.
- Python: game (16), route API (26), leaderboard (8), Pages build/delivery (11): **61 tests passed**.

## Database persistence

The project already has server-side SQLite storage: `leaderboard.sqlite3` holds players/survival scores;
`game_routes.sqlite3` holds immutable plans, source terrain, attempts and route rankings. Both use the
configured `MARSWALK_GAME_STATE_DIR`. Tests verified reopening and a fresh independent application process
reading the committed score. No audit callsigns or scores were written to the public website.

## Local artifacts

- `game_state/single-site-audit/keyboard-complete-ranked.png`: inspected enlarged board from the keyboard run.
- `game_state/planner-flow-audit/report.json`: full planner-flow checks and browser/API error lists.
- `game_state/ai-driver-audit.json`: timings and arrival positions for all 14 AI drives.

These checks use headless Chrome (software WebGL for 3D), not every browser or physical device. They validate
the local branch; publishing requires both the Cloudflare frontend and the matching FastAPI backend.
