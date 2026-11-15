# PR #48: measured terrain and regional topographic views

Terrain now refines from measured global elevation to published USGS CTX/HRSC
data where available. The bundled metadata catalog identifies source footprints
and native grid spacing; gaps retain measured coarser elevation. Detailed CTX
photos, bounded streaming/caches, dateline handling, provenance and explicit
fallback/retry behavior support browsing beyond Jezero without invented relief.

All 24 configured regions open the topographic map and fly to their catalog
bounds. Only that map enables 3D tilt and walking views; other global maps return
to overhead views. Pinned photo boxes remain independent overlays. Planning-data
downloads cannot move a newer selection or revive a cancelled map, and failed
downloads leave terrain browsing available. Stars and optional seasonal dust
haze are included; haze is a climatological visual effect, not a live forecast.

The current shared UI and vehicle-handling game updates are included. The Regions
button opens its own region group in the team's single-section drawer, and route
controls stay clear of the wider panel.

## How to try

1. Start the app using the repository's normal launcher and open **Regions**.
2. Choose a region. Its catalog bounds and topographic imagery appear immediately;
   planning controls become available when that region's planning data is ready.
3. Select **View this region in 3D**, or use **3D view** above the map. Right-drag
   to tilt and zoom to load available measured detail.
4. Choose another surface under **Layers**. Terrain tilt is disabled and the
   view returns overhead. An explicitly pinned photo box can remain visible.

## Validation

- Backend suite: 206 tests and 6 subtests passed after the vehicle-handling merge.
- Four Node scripts passed: regional terrain, global terrain, sky/dust lifecycle,
  and game launcher. The headless game integration also passed.
- Headless region audit: 10 checks passed against the latest panel integration,
  including all 24 choices, drawer visibility, route-control clearance, 3D-only
  behavior, walking mode, failed/completed/cancelled planning, and stale replies.
- Headless map-selection audit: 21 checks passed against the latest panel
  integration, with retained annotations and no uncaught page/rendering errors.
- Responsive slider audit against the latest panel: 24 mouse drags and 16 keyboard
  checks passed at four viewport sizes, with no pointer cancellations or page errors.
- Earlier terrain navigation, failure/retry, and relief audits passed. A further
  navigation run is recorded in the PR validation notes.
- Git whitespace and JavaScript syntax checks passed; the changelog generator
  and its completeness check passed.

The region audit uses controlled planning-job responses, including two browser-only
pending regions, to avoid launching bulk downloads or modifying local cubes.
Live map providers supply the terrain. Fine coverage and source availability vary;
grid spacing does not establish physical accuracy. The optional local Jezero DEM
and generated planning cubes are not committed. Some remote tiles did not finish
within the earlier relief audit's 20-second screenshot wait. The legacy Puppeteer
smoke script was unavailable; the Playwright integration was used instead.

## Merge and integration resolutions

- Earlier merge `aeb303c`: add/add conflicts in
  `docs/changelog/PR-040-feat-siddhi.md`, `PR-041-feat-siddhi.md`,
  `PR-042-feat-siddhi.md`, and `PR-043-feat-siddhi.md`. Both versions were compared;
  incoming human summaries were retained together with their generated history.
  There were no application-code conflicts.
- Merge `9137694` brought in `main` at `cb6a68a` (vehicle handling) cleanly.
- Merge `5f9dc04` brought in `main` at `d6292aa` (team panel design) cleanly.
  The subsequent browser audit exposed a hidden region picker because the new
  panel filtering operated on top-level groups. The Regions action now selects
  `panelPlace`; route controls also use the new drawer width. The team's styling
  and section isolation are preserved. The region and map audits verify this
  combined behavior.
