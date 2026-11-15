# PR #60: Mars moons, animated overview and cached-update recovery

PR: https://github.com/siddhilakkarsu-max/NASAHackathon26Magikid/pull/60

The planner opens on its normal imagery with synchronized Sun/moon playback and
an orbiting presentation camera. Phobos and Deimos use NASA models, physical
sizes/distances and JPL MAR099/DE440 ephemerides. Place labels and moons are hidden
when Mars blocks them.

Dragging pauses the overview. It resumes after seven seconds without an action;
hover movement and default-map zoom do not reset the timer. Editing local solar
time or season resolves a dated scenario and eases the displayed moons to the
calculated endpoints. That visual transition is labeled; it is not a simulated
physical trajectory between the two dates. Source failures do not fabricate data.

Frontend script/style URLs now include content hashes, preventing the cached
lighting-module mismatch that stopped Cesium rendering. A compatibility guard
keeps the map usable and offers refresh if modules cannot work together.

## How to try it

Choose Start exploring, zoom, drag and release while continuing to move the
mouse, then edit the Time panel's season and local time. Check Phobos & Deimos
for the resolved UTC, reference date and source status. Details and limitations
are in `docs/planner/MOONS.md`.

## Main updates and conflicts

- `2f84fb7`: merged main through `61486ca`; no conflicts.
- `8bf822f`: merged main through `0c62fa5`. The conflict in
  `frontend/index.html`, in `murrayLabel`, combined main's `mapFont(12)`
  Electrolize styling with this branch's `marsSurfaceLabelVisibility` callback
  and `disableDepthTestDistance: 0`. The teammate's font and the far-side label
  fix are both retained. Other incoming changes were retained.
- The older map audit intercepted the retired terrain metadata path. It now
  reads the current catalog endpoint (currently `/murray/elevation/v2/`) and
  still checks that a late terrain response cannot replace a newer map choice.

## Validation before publication

- Python: 237 tests and 11 subtests passed. There were 22 LERC/NumPy deprecation
  warnings in the existing elevation tests.
- Headless browsers: 74 checks passed: moons 11, hover/idle/transitions 12,
  overview 12, cached upgrades 8, global map selection 21, regions 10 (covering
  all 24 region choices). No uncaught browser or renderer errors in the audits.
- Visibility geometry checks and Git whitespace/conflict-marker checks passed.
- A new browser assertion verifies the merged Electrolize map font together
  with the far-side label visibility behavior.

The changelog generator records merged PRs; this PR's generated history will be
added after it merges. These checks cover the recorded cases, not every possible
browser or external data-service failure.
