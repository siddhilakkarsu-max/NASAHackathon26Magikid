# Marswalk: Survive the Route

A first-person 3D survival game that plays the plan the Marswalk planner generates. You are the astronaut (or
driver), seeing Mars through the visor or over the rover's hood: follow the planned path from landing spot A to destination B, do the science with the planner's tool list, and get back to A
alive. Run out of oxygen, battery or suit integrity, or use up every tool, and you die. Houston stays on the radio
in short calls with the Earth-Mars signal delay; the long cutscenes are off unless you add `?story=1`.

Everything is in one file, `frontend/game.html` (no libraries, no build step). This document is both the player
guide and the hand-over for the next developer or agent.

## Launch

| How | What you get |
|---|---|
| `run.bat` / `./run.sh`, then `http://localhost:8000/game.html` | Online mode: plan any mission on the title screen, real weather, pixel values and rover tracks |
| **Play** button on the gear page (`kit.html`) | Opens the game and plans a mission from the kit form's vehicle, season, region and goals |
| **Play route #N** in the planner's Mission results | Opens the exact plan and selected route in a new tab |
| **Game · Survive the route** on the planner | A collapsed section for playing the selected route or browsing ready-made missions |
| Double-click `frontend/game.html` | Offline mode: five baked real missions, embedded Jezero weather tables, generated terrain |

## How to play

Pick a mission (or plan one), read the briefing, choose route #1, #2 or #3 and a difficulty, press **Begin EVA**.

| Key | Action |
|---|---|
| W / S | On foot: walk forward / back along your view. In a vehicle: accelerate / brake and reverse. Follow the chevron line |
| A / D | Strafe on foot. In a vehicle: steer (arrow keys steer too) |
| V | Step off the bike or open rover, or mount it again from within 7 m (E beside it also mounts) |
| Mouse (click the view first) or left / right arrows | Look around. Touch: drag the view |
| Shift | Careful pace: slower, no scree strikes, spots soft sand nearby |
| E / Enter | Interact (start site work at a sampling spot, rock free of sand, mini-game action) |
| Space | Hop in Mars gravity (interacts instead when you stand on a sampling spot) |
| 1-9, 0 | Use the tool in that belt slot |
| G, C, O, B, R, F | Radar ping, camera, emergency oxygen bottle, battery pack, radio relay, repair kit |
| H | Head home (start the return leg) |
| L / Tab | Cycle data layer (painted on the ground) / open the planner-data drawer |
| + / - / wheel | Zoom |
| M, P or Esc | Mute, pause |

Touch screens get a joystick (forward and strafe) and CAREFUL / ACT buttons; tool slots are tappable.

What you see: the planned route is a chevron line on the ground, coloured by the plan's risk (green, yellow, red),
with faint dashed lines at the corridor edges. Light pillars mark A (blue), B (orange), sampling spots (cyan),
shelters (white) and the turn-back point (red). Off-limits ground is hatched red. The pill under the clock shows
your heading and an arrow to the next point on the route.

Vehicles handle like vehicles. They build up speed and coast, steering only bites while rolling and flips in
reverse, loose ground gives less grip, and the cockpit stays fixed to the vehicle while you look around with the
mouse. On the bike and the open rover, V steps you off: the vehicle stays parked where you left it as a model in
the world (blue ring and label), you walk at on-foot speed and oxygen rate, and the vehicle draws only its hotel
load. Sampling is done on foot, so starting site work steps you off automatically. The pressurised rover is
sampled from inside. The autopilot never dismounts.

Each vehicle is one complete model (`g3VehModel`): the bike, the open rover with two seats, console, dish, camera
and tool pallet, and the pressurised rover with its cabin, six wheels and rear module. The same model is drawn
around the driver's eye while riding (`G3C.SEAT`) and placed on the ground when parked, so looking around from
the seat shows the whole vehicle and what you walk away from is what you were sitting in.

The planner's sampling spots can all lie 100 to 600 m from B. The game places the nearest one on B itself, so
there is always a sample to take where the route ends.

The HUD is drawn as augmented reality inside the helmet: the rim of the helmet frames the view, and the panels
(vitals left, clock and heading top, map right, radio lower left, tool belt bottom) are stacked so they do not
overlap. A small green light floats on the route 38 m ahead as the thing to walk towards, and one plain-language
hint at a time appears above the tool belt (what to press when stuck, breached, off the line, out of signal).
The visor reacts: a red flash and cracks with damage, a red pulse under 20 % oxygen, dust on the glass in a
storm, frost in the cold, and flickering panels when the signal is lost. Each mission starts facing down the route.

**Win:** return to A with at least one sealed sample. Three samples, photos, resources left, time against the plan
and integrity raise the score (grades S to D, weighted by the plan's decision-matrix weights).

**Die** (six causes): `oxygen`, `battery` (pressurised rover life support), `integrity` (strikes, storm, unpatched
breach), `tools` (every charge spent more than 30 m from A: 20 s countdown), `offlimits` (4.5 s on red ground),
`storm` (12 s more than 150 m off the corridor in a storm).

## Leaderboard and callsigns

On the title screen, pick a callsign (3 to 16 letters, digits, spaces, hyphens or underscores) and press
**Claim callsign**. From then on, every successful mission you fly yourself at normal speed is posted. The end
screen shows your rank on that mission and route with its top ten; the title screen shows the overall board
(the total of each crew's best score per mission). Runs that used the autopilot or a speed multiplier, and
missions that ended in death or abort, are not posted. The leaderboard needs the server, so it is hidden when
the game is opened from a file.

Server side (`leaderboard.py`, routes under `/api/game`, included by `app.py`):

| Call | Body / params | Returns |
|---|---|---|
| `POST /api/game/players` | `{"name"}` | `{"name", "token"}`; 409 if taken, 400 if invalid or reserved |
| `POST /api/game/scores` | `{"name", "token", "mission", "goal", "vehicle", "route", "difficulty", "score", "grade", "met_h", "samples"}` | `{"rank", "best", "improved", "players", "board"}`; 403 wrong token, 404 unknown callsign, 429 too soon |
| `GET /api/game/leaderboard` | `?mission=<key>&limit=20`; no `mission` gives the overall board | `{"mission", "board", "players"}` |

Scores live in one SQLite file, `game_state/leaderboard.sqlite3` (not in git; set `MARSWALK_GAME_STATE_DIR` to
move it). All URLs are relative, so it works on whatever host serves the site, including an sslip.io address.
The browser keeps `{name, token}` in `localStorage["marswalk.game.player"]`.

Limits to say out loud: scores are reported by the player's browser, so a determined person can post a made-up
one; the server checks ranges, the callsign's token and a 4-second gap between posts. A callsign has no
password and cannot be recovered on another device or after clearing the browser. There is no name filter
beyond the character rule and a short reserved list, and no admin page: to remove an entry, edit the SQLite
file. Each server has its own board.

## URL parameters

| Param | Meaning |
|---|---|
| `baked=<0-4>` | Start that baked mission at once |
| `cand=<0-2>` | Route index |
| `difficulty=cadet\|astronaut\|commander` | Burn x0.90 / 1.00 / 1.15, corridor 16 / 12 / 9 m, hazards x0.6 / 1 / 1.5 |
| `src=planner` | Load the hand-off from `localStorage["marswalk.game.mission"]` |
| `goal=`, `vehicle=`, `season=`, `ls=`, `priority=`, `green_only=1`, `region=` | Plan live through `/api/mission/stream`; exact `ls` overrides the season preset (falls back to a baked mission with a note) |
| `autopilot=1` | A bot follows the path, samples and returns (demos, tests) |
| `speed=<1-200>` | Simulation speed multiplier |
| `skip=1`, `mute=1` | Skip cutscenes, start muted |
| `seed=<int>` | Fix the random seed (default comes from the mission id) |
| `touch=1\|0` | Force or hide touch controls |
| `view=2d` | Top-down 2D renderer (also the automatic fallback without WebGL) |
| `story=1` | Full Houston cutscenes and the intro on first visit |
| `gq=low` | No antialiasing, device pixel ratio 1, for weak graphics |

60-second demo: `game.html?baked=1&autopilot=1&speed=4` (open rover, ridge, dust-storm season: storm, comms
blackout, scree and a return under pressure).

## Hand-over: how it is built

### Files

| File | Role |
|---|---|
| `frontend/game.html` | The whole game. Edit it directly; there is no generator to re-run |
| `frontend/game-launch.js` | Adds Play buttons to `index.html` (when included) and `kit.html`; writes the hand-off |
| `tests/test_game.py` | Structure, contract and launcher tests, part of `python -m unittest discover -s tests` |
| `docs/game/smoke_test.js` | Headless-Chrome autopilot run over every baked mission and route |
| `docs/game/launcher_test.js` | Dependency-free Node checks for saved-plan settings, region, exact season, storage fallback and kit mapping |
| `docs/game/integration_test.mjs` | Playwright browser checks for compact launch UI, route handoff, kit rerender, live-plan fallback, geographic raster alignment and cancelled-plan isolation |

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
| 2509 | 12. 2D canvas rendering (fallback, `view=2d`) |
| 2865 | 12b. First-person WebGL renderer: `h3` height field, clipmap terrain, rocks, path ribbons, beacons, dust, cockpits |
| 3339 | 13. DOM HUD, title, briefing, drawer, end screen |
| 4047-4161 | 14-16. Input, main loop, `window.__MW` |

### Data flow

Planner (`/api/mission` object) -> hand-off / live plan / baked -> `normalise` -> world built from the selected
candidate's `route.points` -> simulation -> render + HUD.

Hand-off written by `game-launch.js`, read by `readHandoff()` and treated as untrusted (all text is escaped):

```json
{"v":1,"savedAt":0,"region":"jezero","selected":0,
 "request":{"goal":"","vehicle":"","season":"","ls":90,"priority":"","green_only":false},
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

The 3D view is drawn from the same world the simulation uses. Height comes from `h3(W, x, y)`: gentle along the
surveyed corridor, craggy where the game's slope field is steep, with dunes on loose ground and craters off the
corridor. It is scenery over the game's hazard fields, not the real Jezero elevation.

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
`autopilot(bool)`, `look(yawDeg, pitchDeg)`, `probe(x, y)`, `hazards()`, `perf()`, plus `state` and `CFG`.

### Verify before committing

```bash
python -m unittest discover -s tests
node docs/game/launcher_test.js                          # no dependencies
node docs/game/smoke_test.js http://127.0.0.1:8000        # 14/14 routes, needs puppeteer-core and a running server
node docs/game/integration_test.mjs                     # needs playwright; mocks app APIs, no server required
```

For the browser integration checks, install `playwright` or set `PLAYWRIGHT_MODULE` to its importable module
URL. Set `CHROME` if Chrome is not at the default Windows location. These checks use deterministic planner
responses; the smoke test above exercises the served game separately.

The planner handoff reads the saved mission settings even when the form contains a draft for the next plan.
It preserves the selected candidate and the resolved region, and passes the exact solar longitude through
the URL if browser storage is unavailable. The Game section stays collapsed until opened; its shortcut in
Mission results is hidden while planning and when a region change clears the mission. Kit Play keeps its
existing form-to-live-mission flow and preserves the form's exact solar longitude.
Selecting another mission cancels an outstanding live plan; a late response cannot replace the chosen game.
Both briefing and gameplay place imagery using the bounds returned with that image, independently of the
mission's science raster bounds. Images without valid geographic bounds use the procedural fallback.

### Verified on 2026-11-15, first-person 3D build (headless Chrome, Intel UHD graphics)

- Autopilot completes all 14 baked routes from `file://` in the 3D view, no console errors, no NaN meters.
- All six death causes fire (15 checks).
- Manual controls: turning to the route heading and holding W moves along the line; D strafes off it.
- 59-60 frames per second, 1-2 ms of script per frame.
- Not re-run on the 3D build: the 42 UI checks and the 16 live-planning and hand-off checks listed below (the
  local server was down). The planning and hand-off code was not changed.

### Verified on 2026-11-14, 2D build (headless Chrome, Intel UHD graphics)

- Autopilot on Astronaut difficulty completes all 14 baked routes, served and from `file://`, with no console
  errors and no NaN meters.
- All six death causes fire, through `__MW.kill` and through play.
- 42 UI checks (intro, briefing, drawer and layers, pause, site work, touch, end screen, seven bad-input cases)
  and 16 flow checks (live planning, hand-off, corrupt and hostile hand-off, URL planning, offline fallback).
- 59-60 frames per second, about 1.5 ms of script per frame.

### Limits

- The launcher is included by both planner and kit pages. Browser integration checks cover the collapsed Game
  section and selected-route action; regional imagery and track caches are reset when their region changes.
- The baked missions and `VEH` match the planner at main `e3f16de`. If vehicle numbers change again,
  `test_vehicle_table_matches_planner` fails: update `VEH` and re-fetch the `BAKED` lines from `/api/mission`.
- Baked missions and the embedded weather table are Jezero only. When live weather is unavailable, the HUD
  explicitly labels the inherited Jezero climate fallback, including for missions elsewhere. Non-Jezero
  raster positioning is covered by mocked browser regressions; this does not validate that region's live data.
- Terrain off the corridor is generated, so it does not match the real ground. On the corridor it follows the
  plan's risk values.
- Storms, breaches and tool wear are game rules; the planner has no such events.
- Not checked on a real phone, in Firefox or Safari, or with a screen reader.
- `game.html` is 580 KB, most of it the five baked missions.
- In the 3D view, clicking the ground for point values is not available (the mouse looks around); use `view=2d`
  for that. Rover tracks and backup routes are drawn as ground lines only.
- The 3D view was checked in headless Chrome only: not on a phone, and mouse capture was not exercised by hand.
- The hop is visual only: it does not clear obstacles or change the simulation.
- Vehicle handling is a feel model (momentum, speed-dependent steering, grip from firmness), not vehicle dynamics.
  Top speed, energy and oxygen still come from the planner's numbers. Returning to A on foot without the
  vehicle still counts as a success.
- Models (lander, science station, rover, bike, cabin, gloves) are built from flat-shaded boxes, beams and
  cylinders in code; they are recognisable, not detailed.
