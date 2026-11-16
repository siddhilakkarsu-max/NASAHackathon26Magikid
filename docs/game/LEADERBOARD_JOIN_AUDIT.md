# Post-objective callsigns and AI-time leaderboard

Complete the sample at B, press **Join leaderboard**, choose a callsign and submit.
No account login or pre-mission callsign is required. Attempts begin with a private
browser capability and are attached to the callsign only after completing B.

Ranks use the measured AI driving ticks for the player's designed route, divided
by 30. Player driving time, including detours, is never a ranking key or tie-breaker.
Equal AI tick counts tie. Mission, vehicle, difficulty and 2D/3D mode are separated.
Previous planner-estimate records remain stored outside the new AI-time boards.

## Verification — 2026-11-15

- 54 Python tests passed: route APIs, ownership, completion, rankings, persistence,
  game integration and the existing callsign leaderboard.
- Guest completion, post-objective claim, wrong guest proof, early claim, stolen
  attempts, invalid AI ticks/version/route hash and idempotent retries are covered.
- A ranking test gives the slower human driver the faster AI route time and verifies
  that the AI time wins despite identical planner estimates.
- Six headless scripts passed: results, 18 start/pause races, tracking, integration,
  the real planner/3D/editor flow and a normal keyboard drive through a full sample.
- The final keyboard run took 42.700 gameplay driving seconds. Its AI ran 1,201 ticks
  (40.033333 seconds); that exact AI time was persisted and shown in the leaderboard.
- A taken callsign was rejected, then a different name successfully claimed the same
  completed result. The form fit a 390 px phone viewport and a desktop viewport.
- The planner flow and completion run reported no browser errors or game API failures.
  The isolated API log contained no errors. Test callsigns were confined to the audit DB.

AI ticks and sampling success are browser-reported. Python verifies route identity,
completion location, ownership and result structure; it does not independently run
the JavaScript driving simulator. These rankings are not cheat-proof.

Local logs: `game_state/leaderboard-join-audit/`. Form screenshots and the completed
result screenshot: `game_state/single-site-audit/`.
