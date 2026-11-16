# PR #73: ideal AI route driving and standalone leaderboards

AI now integrates every designed segment at terrain-limited speed without steering error or corner cutting.
The displayed game route retains the same designed vertices.
Player and AI share physical envelopes and original-mission clock calibration. Original-route timing stays
fixed across player edits/retries. NASA speed references and game assumptions are visible in results.

Successful standalone missions show a highlighted Leaderboard action; enter a callsign after sampling B.
AI time on the designed route is saved to SQLite and ranks the result. Completed-game claims are browser
reported and use separate boards from tracked terrain-validated attempts. No pre-mission login is needed.
The branch includes the earlier post-mission callsign and original-baseline fixes.

Validation: 59 focused Python tests (including the latest planning regressions); 14 AI routes with exact distance/speed checks; unchanged baseline in
2D/3D after edits and retries; headless standalone ridge sampling, player speed cap, callsign submission
and visible database rank. Latest main merged cleanly; no conflicts or discarded teammate changes.

Try: open /game.html, choose a built-in mission, finish its sample, click Leaderboard and enter a callsign.
