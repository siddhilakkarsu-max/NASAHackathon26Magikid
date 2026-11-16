# Original planner/game rebuild verification

Verified 2026-11-15 on `feat/jason-chen10-marsmap`, after reverting the separate Route Lab implementation
and incorporating `origin/main` at `fdf897f` (including PR #66, which landed during verification).

## Result

The existing Planner assistant and green Mission Ready button now lead into the original game with the
exact selected mission, vehicle and saved start time. The briefing contains a goal, satellite route preview
and Play game button. Details, tools and alternatives remain available in collapsed panels.
Start driving begins movement directly. Edit map opens a contained popup with draggable points, undo,
satellite imagery, topography, slope and a relief control. Leaderboards sit beside the original minimap.
The original storm, shelter, rock, vehicle and sampling systems remain in use.

Route comparison stores the planner's original reference and source cube on the server. Route edits cannot
replace that reference. The server evaluates travel with the planner's existing model, tracks active driving
separately, and requires B, a sample and return to A before an explicit route-score submission.

## Automated checks

- Full Python suite after the final main merge: **273 passed, 11 subtests passed**. The 22 warnings are existing `lerc`/NumPy shape
  deprecations in elevation checks.
- `node docs/game/launcher_test.js`: saved route/time/season/region handoff, unavailable storage and kit mapping.
- `node docs/game/integration_test.mjs`: compact launch, selected route, cancelled planning, regional imagery bounds.
- `node docs/game/map_editor_test.mjs`: stale requests, dateline routes, correct map proportions on mobile,
  validation retry, and locking pointer/keyboard/close actions during a pending route change.
- `node docs/game/route_tracking_test.mjs`: delayed acknowledgement coalescing, final pause packets,
  lost acknowledgement recovery and resuming from the authoritative position.
- `node docs/game/planner_flow_test.mjs`: actual assistant goal → Midday → Pressurized rover → green Play;
  exact server-saved mission; Play game → Start driving → movement; minimap, shelters and tools; leaderboard;
  satellite/topography popup; drag, undo, cancel and apply; immutable reference; 1280, 760 and 390 pixel widths.
  All six check groups passed with no JavaScript errors or game API failures. Movement is checked by observed
  displacement, rather than a fixed rendering delay.
- All **14 original baked routes** completed with autopilot, three samples each, no NaNs or page errors,
  including active/completed storms. Autopilot created no ranked route attempts.
- Separate browser checks covered lost progress acknowledgements, retry after an unavailable plan,
  stale candidate responses, failed final progress, restoring the final approach and a lost submission receipt.
- Backend checks include blocked/missing swept terrain, fixed endpoints, immutable source settings, callsign
  authorization, stale/idempotent packets, paused movement, accumulated sub-millimetre drift, science-location
  eligibility, replay and rank receipts beyond the first 100 entries.

## Visual and live checks

Headless Chrome used the existing local APIs and Mars imagery services. Screenshots are stored outside Git
under `game_state/planner-flow-audit/`: briefing, driving, satellite, topography and responsive popup views.
`game_state/brief-settled-ratio.png` confirms the loaded route preview fits its frame without sidebars.
The map audit also loaded the original user's mission coordinates near 5.65°E, 6.90°S, independently of Jezero.

A separate normal-speed keyboard run drove the original game to B, collected a sample through the actual
mini-game, returned to A during a storm and explicitly submitted a route score. The final clean run recorded
745.575 seconds simulated travel and 84.609 seconds active driving, with rank 1. Its 8.647-second sampling
mini-game added only the 0.953-second closing movement heartbeat to active driving. Screenshots are
`game_state/route-keyboard-complete-before-submit.png` and `game_state/route-keyboard-complete-ranked.png`.
All live tests used a separate `MARSWALK_GAME_STATE_DIR`; test scores were not added to the normal board.
An earlier run under concurrent test load recovered automatically from two rejected progress packets and
still completed. Their response details were not captured, so their exact cause is unconfirmed. The final
instrumented repeat had no rejected packets or page errors. A controlled 1.6-second delayed acknowledgement
then exposed queued movement updates arriving in a burst. The client now coalesces driving heartbeats while
one is pending, preserving ordered pause/final packets. The new regression and a subsequent full keyboard
mission passed without rejected packets; server speed and clock checks were not relaxed.

## Limits

- The 3D scenery remains the original game's procedural scenery. Overhead imagery, elevation displays and
  server route evaluation use the available measured sources; this does not make the 3D world a surveyed model.
- CTX imagery and terrain tiles are reused through existing services. Display detail can exceed the saved
  planner scoring grid. Relief exaggeration changes visualization only, never source elevations or route physics.
- Old uncaptured plans and offline missions remain playable and editable without route ranking. Their edited
  travel/resource estimates are explicitly distance-scaled approximations.
- The server checks where samples are claimed, but mini-game success is still reported by the browser.
  The existing survival leaderboard retains its original browser-reported score behavior.
- Browser verification used headless Chrome. No physical phone, Firefox, Safari or screen-reader check was performed.

Source references: [Caltech Murray Lab CTX mosaic](https://murray-lab.caltech.edu/CTX/) and
[USGS CTX terrain data](https://stac.astrogeology.usgs.gov/docs/data/mars/ctxdtms/).

## Follow-up headless bug audit

Updated the feature branch with `main` at `e22d98a` before checking the game again. The full Python suite
passed (273 tests and 11 subtests), along with the launcher, browser integration, map editor, route tracking
and live planner flow checks.

Reproduced and fixed a delayed-start race: if the user opened the map, opened the leaderboard or paused
while Start driving was awaiting a server response, that response could resume the game behind the popup.
The game now records newer pause actions and preserves them on both successful and failed requests.
`start_pause_test.mjs` covers 18 combinations of initial start, resume, server failure, open/closed map,
open/closed leaderboard, Pause and window blur. It verifies frozen mission time, a paused server attempt,
and successful explicit resume afterward. The test fails against the previous game and passes with the fix.
