# Marswalk: Survive the Route

A survival game that plays the plan the Marswalk planner generates. You are the astronaut (or driver): follow the
planned path from landing spot A to destination B, do the science with the planner's tool list, and get back to A
alive. Run out of oxygen, battery or suit integrity, or use up every tool, and you die. Houston talks you through
it in cutscenes, with the Earth-Mars signal delay.

Everything is in one file, `frontend/game.html` (no libraries, no build step). This document is both the player
guide and the hand-over for the next developer or agent.

## Launch

| How | What you get |
|---|---|
| `run.bat` / `./run.sh`, then `http://localhost:8000/game.html` | Online mode: plan any mission on the title screen, real weather, pixel values and rover tracks |
| **Play** button on the gear page (`kit.html`) | Opens the game and plans a mission from the kit form's vehicle, season, region and goals |
| **Play this mission** on the planner (`index.html`) | Opens the exact plan and selected route. Needs one line in `index.html`, see "Pending" below |
| Double-click `frontend/game.html` | Offline mode: five baked real missions, embedded Jezero weather tables, generated terrain |

## How to play

Pick a mission (or plan one), read the briefing, choose route #1, #2 or #3 and a difficulty, press **Begin EVA**.

| Key | Action |
|---|---|
| WASD / arrows | Move. Stay inside the shaded corridor around the dashed path |
| Shift | Careful pace: slower, no scree strikes, spots soft sand nearby |
| E / Space / Enter | Interact (start site work at a sampling spot, rock free of sand, mini-game action) |
| 1-9, 0 | Use the tool in that belt slot |
| G, C, O, B, R, F | Radar ping, camera, emergency oxygen bottle, battery pack, radio relay, repair kit |
| H | Head home (start the return leg) |
| L / Tab | Cycle data layer / open the planner-data drawer |
| + / - / wheel | Zoom |
| M, P or Esc | Mute, pause |

Touch screens get a joystick and CAREFUL / ACT buttons; tool slots are tappable.

**Win:** return to A with at least one sealed sample. Three samples, photos, resources left, time against the plan
and integrity raise the score (grades S to D, weighted by the plan's decision-matrix weights).

**Die** (six causes): `oxygen`, `battery` (pressurised rover life support), `integrity` (strikes, storm, unpatched
breach), `tools` (every charge spent more than 30 m from A: 20 s countdown), `offlimits` (4.5 s on red ground),
`storm` (12 s more than 150 m off the corridor in a storm).

## URL parameters

| Param | Meaning |
|---|---|
| `baked=<0-4>` | Start that baked mission at once |
| `cand=<0-2>` | Route index |
| `difficulty=cadet\|astronaut\|commander` | Burn x0.90 / 1.00 / 1.15, corridor 16 / 12 / 9 m, hazards x0.6 / 1 / 1.5 |
| `src=planner` | Load the hand-off from `localStorage["marswalk.game.mission"]` |
| `goal=`, `vehicle=`, `season=`, `priority=`, `green_only=1`, `region=` | Plan live through `/api/mission/stream` (falls back to a baked mission with a note) |
| `autopilot=1` | A bot follows the path, samples and returns (demos, tests) |
| `speed=<1-200>` | Simulation speed multiplier |
| `skip=1`, `mute=1` | Skip cutscenes, start muted |
| `seed=<int>` | Fix the random seed (default comes from the mission id) |
| `touch=1\|0` | Force or hide touch controls |

60-second demo: `game.html?baked=1&autopilot=1&speed=4` (open rover, ridge, dust-storm season: storm, comms
blackout, scree and a return under pressure).

## Hand-over: how it is built

### Files

| File | Role |
|---|---|
| `frontend/game.html` | The whole game. Edit it directly; there is no generator to re-run |
| `frontend/game-launch.js` | Adds Play buttons to `index.html` (when included) and `kit.html`; writes the hand-off |
| `tests/test_game.py` | Structure and contract tests (10), part of `python -m unittest discover -s tests` |
| `docs/game/smoke_test.js` | Headless-Chrome autopilot run over every baked mission and route |

### Sections of `game.html` (search for `// N.` headings)

| Line | Section |
|---|---|
| 390 | 1. `CFG`: every constant. `[P]` = planner number, `[G]` = invented game rule |
| 489 | 2. Data: `VEH` (planner vehicles), `BAKED` (one mission JSON per line), tool definitions, Jezero weather tables |
| 568-646 | 3-5. Utilities, seeded PRNG (mulberry32) and noise, API wrappers (timeouts, silent fallback, never from `file://`) |
| 702 | 6. Mission normalise: the only reader of the raw planner object; tolerates missing fields |
| 820 | 7. World: route smoothing and 5 m resampling, distance-to-route grid, slope/firmness fields, cached terrain tiles |
| 1376 | 8. Simulation: 30 Hz fixed step, movement and burn |
| 1611 | 9. Events: storm, soft sand, breach, comms blackout, turnaround, reserve, deaths |
| 1794 | 10. Tools and site-work mini-games |
| 2101 | 11. Cutscenes (`scene(name)`) and WebAudio |
| 2509 | 12. Canvas rendering |
| 2838 | 13. DOM HUD, title, briefing, drawer, end screen |
| 3545-3657 | 14-16. Input, main loop, `window.__MW` |

### Data flow

Planner (`/api/mission` object) -> hand-off / live plan / baked -> `normalise` -> world built from the selected
candidate's `route.points` -> simulation -> render + HUD.

Hand-off written by `game-launch.js`, read by `readHandoff()` and treated as untrusted (all text is escaped):

```json
{"v":1,"savedAt":0,"region":"jezero","selected":0,
 "request":{"goal":"","vehicle":"","season":"","priority":"","green_only":false},
 "hour":11,"ls":90,"ai":{"goal":{"reasoning":"","content":""},"explain":{"reasoning":"","content":""}},
 "mission":{}}
```

Other storage keys: `marswalk.game.best` (best score per mission and route), `marswalk.game.last` (previous run,
for "compared with the previous run"), `marswalk.game.prefs` (intro seen).

### What is real and what is invented

Real, from the planner (`config.py`, `physics.py`, `mission.py`): vehicle limits and energy figures (`VEH`; a test
fails if they drift from `config.MISSION_VEHICLES`), suit oxygen 0.912 kg at 0.114 kg/h, walk-back rate
0.181 kg/h, oxygen x(1 + 0.04 x slope) on foot, battery Wh/km x(1 + 0.05 x slope) x(1 + 0.5 x sand x (1-firm)^2),
the slip table, walker speed, reserve %, turnaround time, 1 h of site work, tool names with kg and W, sun and
surface-temperature formulas, risk colours, signal delay 4-24 min.

The game calibrates each run to the plan: a clean on-route run uses the oxygen and battery the planner predicted
(`kSpeed`, `kO2`, `kWh` in the snapshot), so the planner's own resource model changes carry over.

Invented for play (all marked `[G]` in `CFG`): time compression (a round trip lasts about 2.5 to 6.5 real
minutes), off-route penalties, terrain away from the corridor (generated, not the real surface), storms, soft
sand, breaches, blackouts, integrity, mini-games, scoring, and tool charges:

| Tool | Charges | Tool | Charges |
|---|---|---|---|
| Spectrometer | 6 | Camera | 8 |
| Core drill | 4 | Emergency oxygen bottle (+0.057 kg) | 1 |
| Sample tubes | 10 | Battery pack | 1 |
| Radar | 5 | Radio relay | 2 |
| Neutron spectrometer | 4 | Repair kit | 3 |
| Rock hammer | 6 | | |

A wrong use wastes a charge.

### Test hook

`window.__MW`: `getSnapshot()`, `startBaked(i, cand, diff)`, `setSpeed(n)`, `kill(cause)`, `teleport(metres)`,
`autopilot(bool)`, `probe(x, y)`, `hazards()`, `perf()`, plus `state` and `CFG`.

### Verify before committing

```bash
python -m unittest discover -s tests                      # 136 tests
node docs/game/smoke_test.js http://127.0.0.1:8000        # 14/14 routes, needs puppeteer-core and a running server
```

### Verified on 2026-11-14 (headless Chrome, Intel UHD graphics)

- Autopilot on Astronaut difficulty completes all 14 baked routes, served and from `file://`, with no console
  errors and no NaN meters.
- All six death causes fire, through `__MW.kill` and through play.
- 42 UI checks (intro, briefing, drawer and layers, pause, site work, touch, end screen, seven bad-input cases)
  and 16 flow checks (live planning, hand-off, corrupt and hostile hand-off, URL planning, offline fallback).
- 59-60 frames per second, about 1.5 ms of script per frame.

### Pending and limits

- **Pending:** `frontend/index.html` belongs to other teammates and is not edited. To get the Play button there,
  add `<script src="/game-launch.js" defer></script>` in `<head>` after the `mars_lighting.js` tag. The script
  injects the button itself. It was tested by injecting it into the page, but that test predates the planner's
  new landing screen and has not been repeated since.
- The baked missions and `VEH` match the planner at main `e3f16de`. If vehicle numbers change again,
  `test_vehicle_table_matches_planner` fails: update `VEH` and re-fetch the `BAKED` lines from `/api/mission`.
- Baked missions and the embedded weather table are Jezero only. Live planning sends whatever `region` it is
  given, but other regions are untested in the game.
- Terrain off the corridor is generated, so it does not match the real ground. On the corridor it follows the
  plan's risk values.
- Storms, breaches and tool wear are game rules; the planner has no such events.
- Not checked on a real phone, in Firefox or Safari, or with a screen reader.
- `game.html` is 525 KB, most of it the five baked missions.
