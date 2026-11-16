# Single-objective mission update

Verified headlessly on 2026-11-15, on `feat/jason-chen10-marsmap`.

## Scope

Each selected candidate is one mission from A to B. Completing its sampling mini-game ends that mission;
extracting then cancelling does not. Other candidates remain selectable as the next objective.
The existing game, terrain presentation, hazards, vehicle controls and route-editing style remain in use.

The end panel shows active play time, active driving time, the AI model on the player's route, and the
same model on the immutable original route. AI comparisons and rankings now use one-way travel; a model
version prevents mixing old round-trip attempts. Old saved plans can still start new attempts.
Resources accumulate consumption rather than subtracting the final tank level, so refills cannot erase use.
The mission clock is distinct from real play time and is the basis of the surface cost estimate.

Ground firmness adds material estimates over the existing satellite map, using saved thermal observations
and derived planner firmness. Regional data supports standalone baked missions too. Unknown data stays
unknown. The categories do not claim measured soil strength or mapped individual rocks.

## Sources and cost assumptions

- [NASA life-support baseline, Table 3-31](https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf#page=72):
  0.895 kg oxygen per crewmember per Earth day. The pressurized-rover report averages this over the simulated
  mission duration for one crew member. This is a reporting estimate and does not add a new gameplay drain.
- [NASA life-support baseline, Table 4-70](https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf#page=149):
  typical EVA oxygen of 0.086 kg per crewmember-hour. The existing game uses a 0.114 kg/h base with
  terrain/gameplay modifiers; the source panel distinguishes those values rather than attributing the game
  baseline to this NASA table.
- [NASA Mars surface-power study](https://ntrs.nasa.gov/citations/20210022250): pressurized concept rover,
  5,193 kg, 60 kWh, 1.85 kW hotel load, rolling resistance 0.15. These underpin the existing drive model;
  terrain, instruments, carried load, cold and damage remain model adjustments.
- [NASA Apollo LRV](https://nssdc.gsfc.nasa.gov/planetary/lunar/apollo_lrv.html): two 36 V, 121 Ah batteries.
- [NASA/JPL thermal-inertia research](https://ntrs.nasa.gov/citations/20170003773): material mixing limits
  interpretation. The map's source panel also identifies its actual regional datasets and resolutions.

USD/hour, USD/kg oxygen and USD/kWh are editable player assumptions, initially blank. NASA does not supply
the app's prices. Cost covers surface time from A through sampling at B, oxygen and electricity only;
launch, transit, vehicle purchase and return travel are excluded. Inputs have unit, finite-value and range
checks; unavailable consumption is not silently priced as zero. A zero rate explicitly excludes that item.

## Checks

- Full backend: **279 tests and 11 subtests passed**; 22 existing lerc/NumPy deprecation warnings.
- Launcher, browser integration, route tracking and **18** delayed-start/pause cases passed.
- Single-site regression: pauses, sampling clock, oxygen/battery refills, cancelled extraction, full sample
  at B, frozen results, retry reset, edited route then next candidate, and cabin oxygen unit conversion.
- Results regression: all four times, energy/cost units, invalid rates, unknown consumption, storage failure,
  rate persistence, NASA links and a 390-pixel viewport.
- Normal-speed keyboard mission, without autopilot/teleportation: drove to B, finished the mini-game and
  explicitly submitted rank 1 without a return leg. One-way AI time 372.787 s; server active driving 42.547 s;
  58.255 s active play; modeled electrical consumption 1,659.986 Wh. No page errors or rejected API packets.
- **14/14** original 3D routes completed at B with one sample, no NaNs, page errors or ranked autopilot attempts.
- Real standalone Ground firmness map: regional observations loaded, one destination, desktop and 390-pixel
  layouts inspected, no horizontal overflow. Map regressions also cover stale responses, missing data,
  dateline coordinates and existing drag/apply behavior.

Live tests used isolated state at `game_state/single-site-audit`, not the normal leaderboard. Screenshots
are ignored local artifacts there and at `game_state/single-site-map.png` / `single-site-map-mobile.png`.
Browser checks used headless Chrome; no physical phone or other browser engine was tested.
