# Planner map controls

Mars global maps has one Map view selector. Planner imagery, CTX, MOLA, Viking,
3D terrain, weather and radiation replace one another. Names, crater outlines,
rover tracks, the photo tile grid and HiRISE footprints are independent overlays.
Choosing a regional data layer restores the planner background.

The photo tile grid displays every published tile in view. Its 3,960 tiles cover
all longitudes from 88 degrees south to 88 degrees north; the polar gaps reflect
the source. Dateline normalization and cached tile lookup preserve four-degree
tiles at the longitude boundary.

Native text dragging is canceled on the time, season and budget ranges. This
prevents an existing page text selection from canceling a slider gesture after
one step, while preserving native pointer and keyboard interaction.

## Browser regression checks

Start the app on localhost port 8001, install Playwright and its Chromium browser,
then run these scripts sequentially:

```sh
node docs/planner/map_selection_test.mjs
node docs/planner/time_slider_test.mjs
```

Set `MARSWALK_TEST_URL` for another app URL, `CHROME` for an existing Chrome
executable, or `PLAYWRIGHT_MODULE` for an importable Playwright module URL.
Reports and screenshots go to a temporary directory printed by each script;
`MARSWALK_AUDIT_DIR` selects a specific output directory.

The map test checks every enabled view, retained annotations, regional transitions,
and late weather/terrain responses. The slider test uses real Control+A selection,
mouse drags and keyboard input across four viewport sizes. Its optional
`MARSWALK_SLIDER_MODE=fixture` mode isolates the controls from the globe.

Backend map-source and dateline checks are in `tests/test_murray.py`. Game handoff,
region, season and route checks are documented in `docs/game/README.md`.

These checks cover specific regressions; they do not establish that all external
map services are always available or that every browser/device has been tested.
