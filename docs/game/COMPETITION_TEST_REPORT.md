# Route competition test report

Executed 2026-11-15 (America/Los_Angeles). Branch
`feat/jason-chen10-marsmap` was first fast-forwarded to GitHub main `82e88fd`.
The brief prerequisite scan passed 23 existing game/leaderboard tests, the Node
launcher checks, JavaScript syntax and whitespace checks before implementation.

## Pass 1 — scoring and validation

```powershell
.venv\Scripts\python.exe -m pytest tests/test_route_competition.py tests/test_competition_terrain.py -q
```

**40 passed**: 19 backend tests and 21 terrain cases. These cover independently
calculated flat/slope travel and energy values; identical and collinearly
subdivided routes; ascent at short route turns; thermal inertia not influencing
traction; mission/data/model identity; complete segment and corner crossings;
missing, steep and out-of-bounds terrain; ordered objectives; authorization;
client-score rejection; teleport/grade-speed rejection; refresh/pause gaps;
duplicate progress; exact route-corridor coverage; atomic restart and finish;
persistent results; and ranks **1, 1, 3** despite different actual driving times.

The installed 20 m crop was compared exactly with the original source pixels.
Corrupt/missing packages and inconsistent projection metadata fail closed.
Small artificial grids are used only as explicitly controlled unit-test fixtures,
never as runtime terrain.

A live API evaluation also verified a valid player alternative can beat the AI
reference. The direct route through the same required stations scored
**23,126.361 s over 723.607 m**, compared with the graph-search reference's
**23,860.083 s over 826.690 m**. The reference is not treated as an unbeatable cap.

## Pass 2 — complete gameplay

The audit server used an isolated SQLite state directory, not the user's scores:

```powershell
$env:MARSWALK_GAME_STATE_DIR='game_state/competition-audit-20261115'
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8012 --no-access-log
```

In another shell, with Playwright installed (or `PLAYWRIGHT_MODULE` set to its
importable `index.mjs`) and `CHROME` pointing to a Chrome executable:

```powershell
node docs/game/competition_browser_test.mjs
```

**Passed all 9 grouped checks**, using headless Chrome with software WebGL and
the live backend, real bundled DEM, and normal API endpoints. The test claims a
callsign, generates a mission, opens the first-person rover, switches all layers,
adds/moves/removes points, preserves the reference, rejects an invalid route,
confirms a valid route, drives, pauses, edits/restarts, reloads, restores, finishes,
explicitly submits and reads the leaderboard. It uses the normal route-assist
control and real wall-clock time; it does not teleport, override scores, mock
terrain, or bypass server completion checks.

Recorded successful run:

| Result | Value |
| --- | ---: |
| AI reference simulated time | 23,860.083 s |
| Confirmed route simulated time / leaderboard score | 23,860.083 s |
| Actual active driving time | 110.753 s |
| Required stops reached | 2 of 2 |
| Route horizontal distance | 826.690 m |
| Model energy | 739.312 Wh |
| Repeated submission | No duplicate player entry |
| Uncaught browser errors | 0 |

The final run intentionally loses one accepted progress acknowledgement and
rejects the last pause request. Recovery and score submission still succeed.
Those failures are labeled test fixtures; all successful scoring and driving
responses come from the real server. A separate mocked unavailable-data response
disables competition instead of fabricating terrain.

Local screenshots of the map, rover and results were rendered and inspected.
The machine-readable run report and screenshots are under
`game_state/competition-browser-audit/` (ignored runtime output).

## Pass 3 — failures and regressions

```powershell
node docs/game/competition_failure_test.mjs
node docs/game/integration_test.mjs
node docs/game/launcher_test.js
.venv\Scripts\python.exe -m pytest -q
```

- **Failure browser audit passed:** missing-callsign recovery preserves edits;
  UI editing outside the boundary is rejected; failed attempt retirement can be
  retried; late evaluations cannot confirm changed geometry; invalidated saved
  attempts cannot resume; no uncaught browser errors. It uses the existing 2D
  fallback to focus on state transitions.
- **Existing browser integration passed:** selected planner route hand-off,
  planning/clear states, kit rerender, exact season fallback, regional raster
  alignment and cancelled-plan isolation. Its existing API fixtures remain
  fixtures; it is separate from the live-data competition run.
- **Launcher checks passed:** existing selected-plan/storage/kit behavior and
  the independent competition entry point.
- **Full Python suite: 277 passed, 11 subtests passed**, with 22 existing `lerc`
  NumPy-shape deprecation warnings, in 26.26 s.

After the final browser fixes and request-description correction, the relevant
Python tests were rerun:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_game.py tests/test_route_competition.py tests/test_competition_terrain.py -q
```

**56 passed in 9.01 s.** JavaScript syntax and `git diff --check` also passed.
The Windows sandbox blocked Python's local asyncio socket pair on initial test
attempts; the same tests were rerun outside that sandbox and completed. Hung test
processes were stopped; those interrupted runs are not counted as passes.

## Issues found and fixed

- Short turns between integration stations could hide climb: integrate canonical
  turning vertices as well as regular stations.
- Region/geometry ambiguity and browser-supplied scores in the old game design:
  the competition has separate server-owned mission identities and scoring.
- Route assistance could loop at overlapping reference segments: maintain its
  forward route station rather than repeatedly selecting the nearest old segment.
- Momentum and route joining could exceed the grade speed allowance: cap each
  swept motion using the defined terrain model.
- Lost acknowledgements restored stale local positions: restore the server's
  current sequence and position before resuming.
- Rejected final-pause and retirement promises could permanently block retry:
  recover authoritative state and retry the appropriate transition.
- Dense route handles were difficult to edit: add route focus, whole-area view and
  explicit add-point controls.
- Raster source pixels and route coordinates had a half-pixel offset: align node
  centres; thermal boundaries follow the same source-cell rule as the server.
- Missing identity and invalidated saves lacked a usable recovery path: return to
  the callsign form or clear the invalid saved pointer without losing the plan.
- Displayed leaderboard improvements assumed a nonexistent field: derive them
  from reference and simulated times. The primary score is explicitly time.

## Remaining limits

Passing these checks does not establish zero possible bugs. The model is a fixed
comparison rule, not validated flight-rover engineering. The 20 m DEM cannot
resolve small rocks, ledges or rover-scale slopes; coarse TES inertia is not soil
strength. Source-data accuracy and real mission travel time were not independently
remeasured. Browser input cannot prove human driving, and assistance is permitted.

Large-scale concurrent hosting, load testing, mobile hardware and every browser
GPU were not verified. This version is documented for a single application worker
with persistent storage. Game-specific rows remain separate from the original
survival leaderboard, which retains its legacy scoring behavior.
