# Route-planning competition: acceptance contract

The competition rewards the submitted route, not driving skill. Existing
first-person rendering and input controls remain available, with the old
survival game kept separate from ranked route planning.

## Stages and expected behavior

1. **Measured map.** One bounded Jezero area uses a real elevation grid. The
   topography, slope (degrees; steeper is red), material estimate, route editor
   and first-person terrain use the same local metric coordinates. Missing
   elevation or slope is forbidden terrain. Thermal inertia is shown at its
   actual source resolution and never called traction or firmness. Every layer
   has a legend, source, resolution and missing-data indication.
2. **Plan and edit.** Explicit destination and ordered survey objectives define
   the mission. A graph-search reference route is generated and saved unchanged.
   Play opens the existing first-person view. A visible Map button exposes both
   routes and all objectives. Editing can add, move and delete intermediate
   points; layer changes preserve those points. Confirmation checks complete
   segments, including crossed cells, against terrain and boundary constraints.
3. **Standard score.** One versioned uncrewed rover model supplies speed, slope
   effects and energy assumptions. Equal routes under the same mission produce
   equal simulated travel times. Driver hesitation, actual driving time,
   assisted driving and display time compression never improve that score.
4. **Persistent competition.** The server owns mission identity, reference
   route, confirmed route validation and score calculation. Identity includes
   objectives, region/data version and rover settings. A persistent SQLite
   leaderboard compares only that mission; equal simulated times share rank.
   Driving starts an immutable attempt. Changes to its route invalidate/restart
   the attempt. Completion requires ordered objectives and destination; failed
   and unfinished attempts cannot submit. Repeated submissions are idempotent.
5. **Results.** Successful completion shows the AI reference's simulated time,
   the player's route simulated time (the score), actual active driving time,
   distance, difference from reference, and energy. Loading, map/editor,
   hidden/paused screens and disconnected time do not count as active driving.
   This v1 is uncrewed: no oxygen is displayed. View leaderboard, Edit route and
   Try again are available. All travel/resource values are labeled estimates.

The fixed model is an explicitly defined game model, not a verified prediction
of a flown rover. Coarse thermal inertia is not converted into precise terrain
traction. Survey stops are game objectives on surveyed terrain, not invented
mineral discoveries. Structured objectives are shown to the player; free text
is not silently interpreted as unsupported scientific facts.

## Three audit passes

1. **Scoring and validation:** identical routes and ties, segmentation,
   slope/grade effects, no-data holes, whole-segment boundaries, impossible
   routes, required stops/order, model/data identity, score tampering, energy,
   and actual-versus-simulated time separation.
2. **Complete gameplay:** generate a reference, Play, open Map, switch all
   layers, add/move/delete points, validate, drive, finish, display all three
   times, explicitly submit, and read a persistent leaderboard entry.
3. **Failures and regressions:** source/API failures, missing terrain,
   repeated/reordered requests, reload/paused recovery, restart, edit during
   driving, incomplete attempts, stale responses, and preserved legacy controls.

Tests run headlessly. Reports must list the actual executed commands and
results, distinguish live scientific data from test fixtures, and state any
remaining limits. Passing tests is not a claim of zero possible bugs.
