# PR #71: planner missions, measured AI driving and persistent route rankings

The results board now compares the player's gameplay time with actual AI driving
on the edited route and original AI route. A mission finishes after one sample at
B. Larger results show the four times, oxygen, electrical energy, distance and
cost; cost-model inputs remain separately expandable.

The planner's green Play Route action carries its exact mission and selected
candidate into the game, including vehicle and start time. Initial Play captures
the mouse and activates controls. The route editor displays the planner's
available firmness/thermal observations with honest source resolution. SQLite
persists saved plans, attempts and route rankings alongside the callsign database.

## Validation

- 61 focused Python tests passed on the final code: game, route API, leaderboard
  persistence, Pages build and frontend delivery.
- Nine headless scripts passed: launcher, results, map editor, start/pause races,
  route tracking, integration, single-site completion, actual AI drivers and the
  planner-to-game flow. All 14 AI reference drives reached their destination;
  all 18 start/pause race cases passed.
- The planner flow reported no browser errors or game API failures and checked
  desktop, tablet and phone layouts, immediate mouse capture and route editing.
- The rerun caught an obsolete assertion that searched source text for a URL
  literal. Executable launcher tests already verify the complete generated URL,
  mission ID, candidate and storage fallbacks; the stale assertion was removed.
- Removed an extra blank line flagged by `git diff --check`.
- Server-log review found a Windows asyncio socket-close `ConnectionResetError`
  during browser testing. The server remained responsive: game, mission options
  and database leaderboard returned HTTP 200 afterward. No application traceback
  appeared in that warning. This is retained as a test-environment observation.

## Try it

Create a mission in the planner, use the green Play Route button and begin driving.
Edit the route if desired, reach B and complete its sample. Check the enlarged
results and submit the completed attempt to its route leaderboard.

## Merge and deployment

The branch already contained the latest `main` (`e22d98a`) at the pre-merge audit;
there were no new conflicts to resolve. The PR also supplies the missing generated
changelog for already-merged PR #68 so the repository's changelog check can pass.

Publish both the Cloudflare frontend and the matching FastAPI backend after merge.
Merging the PR alone does not verify a public deployment. Full feature evidence
and source-data limitations are in `docs/game/RESULTS_DRIVING_AUDIT.md`.
