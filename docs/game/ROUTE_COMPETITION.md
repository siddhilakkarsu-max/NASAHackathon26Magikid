# Marswalk route competition

Route Lab compares route design using a fixed, versioned rover model. It reuses
the existing first-person game and controls. The original survival game remains
available separately; its scores are not competition scores.

## Start locally

From the repository root, using Python 3.11 or newer:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/game.html?mode=competition`, or use
**Plan → Route competition · Jezero** in the planner. No API key, hosted language
model, or new terrain download is needed. The two tracked files under
`data/competition/` must be present; a missing or corrupt package disables the
competition rather than inventing replacement terrain.

The default HTTP game page opens Route Lab. Existing planner and gear **Play**
actions still carry their selected mission into the original survival mode.
`game.html?mode=survival` selects that mode explicitly.

## Play

1. Claim a callsign. Select a destination and ordered survey stops, then generate
   the AI reference. This is A* graph search on measured terrain; descriptive
   goal text is not interpreted by a chatbot. The exact objectives are visible.
2. Press **Play** to enter the rover view, then **Map · edit route**. Compare the
   immutable reference and your editable route. Add, move or remove intermediate
   points; changing a layer preserves the route. Start and destination are fixed.
3. Confirm the route. The server checks every crossed terrain cell, boundary and
   required stop. Press **Start driving**. Use the existing movement controls or
   route assistance. Assistance does not change the route score.
4. Opening the map pauses the drive. Changing the route invalidates the attempt;
   confirming and starting the edited route begins from the start. Reloading
   recovers a paused attempt rather than crediting offline time.
5. Complete the ordered objectives and reach the destination. The completion
   screen separates the AI reference time, your simulated route time, and your
   actual active driving time. **Submit route score** saves the successful attempt
   to that mission's leaderboard.

## Data and scoring

The mission is limited to a 6.4 × 6.4 km Jezero area. Topography and first-person
terrain share the native 20 m USGS CTX elevation grid. Slope uses that DEM and is
shown in degrees, with red indicating steeper terrain. The material layer is a
coarse TES thermal-inertia estimate, about 7 km per derivative cell here. It is
not measured traction or ground firmness. No fine material detail is generated.
See [data provenance and reconstruction](COMPETITION_DATA.md) for source links,
projection, resolution, checksums and missing-data rules.

Scores are calculated by the server from the confirmed route. At integration
stations along the route, horizontal distance `d`, elevation change `dz` and
grade `g = dz / d` give:

```
segment_time_s = hypot(d, dz) / 0.04 * (1 + (g / 0.10)^2)
energy_Wh = 110 * time_s / 3600 + positive_climb_m * 899 * 3.71 / 0.70 / 3600
```

The numerical integration includes canonical route turns as well as stations at
5 m intervals. Terrain above 25° and missing elevation/slope are forbidden. This
is an explicitly illustrative comparison rover: 0.04 m/s base speed, 899 kg mass,
110 W electrical load, 70% climbing efficiency and Mars gravity of 3.71 m/s².
These constants do not claim to predict flight-rover operations. The drive is
presented at 400× time compression; simulated mission time is not compressed.
Thermal inertia, player hesitation and actual driving speed do not change the
route score. This is an uncrewed scenario; oxygen is not estimated.

Mission identity binds the exact start, destination, ordered stops, terrain and
coordinate metadata, rover settings, conditions, and reference algorithm. Only
matching identities compete. The board keeps each callsign's best valid route;
equal millisecond-rounded simulated times share a rank. Driving time never breaks
a tie. Energy and all travel times are estimates, not verified mission timings.

## Persistence and hosting

The existing callsign credential is kept in the browser. SQLite files live in
`game_state/` by default; `MARSWALK_GAME_STATE_DIR` selects a persistent directory.
Back up both the existing player database and `route_competition.sqlite3`. Each
attempt stores the mission ID, callsign, immutable route, deterministic metrics,
progress and completion state. Tokens are checked server-side and are not put in
URLs. Callsign recovery remains the existing browser-based mechanism.

Use one application worker with persistent local storage for this version. For
shared online use, serve behind HTTPS and apply normal request-rate and body-size
limits. Server validation rejects client-supplied scores and impossible swept
movement, but browser input cannot prove that a human drove. Assisted driving is
allowed because this is a route-planning competition.

## Verification

The acceptance criteria and three audit categories are in
[COMPETITION_SPEC.md](COMPETITION_SPEC.md). The executed commands, outcomes and
remaining limitations are recorded in [COMPETITION_TEST_REPORT.md](COMPETITION_TEST_REPORT.md).
