# Planner map controls

Mars global maps has one Map view selector. Planner imagery, CTX, MOLA, Viking,
weather and radiation replace one another as full-surface maps. Detailed photos
includes real 3D terrain underneath the imagery. Names, crater outlines,
rover tracks, the photo tile grid and HiRISE footprints are independent overlays.
Choosing a regional data layer restores the planner background.

## Detailed photos and terrain

The detailed black-and-white map combines Murray Lab CTX imagery with the
MOLA/HRSC global elevation model served by Esri and the USGS 20 m Jezero survey
where it is installed. Image and elevation tiles refine
as the camera approaches the surface. Only visible tiles and the renderer's
bounded cache are needed; the entire full-resolution planet is not downloaded.
Right-drag tilts and rotates the terrain view; the mouse wheel zooms. The labeled
height control defaults to 2.7x display exaggeration and spans 1x–8x. **True scale**
restores 1x. These settings change the display only: elevation samples and mission
calculations retain their physical values. Rover and astronaut proportions are
not stretched. **Angled terrain view** frames the visible surface or pinned box;
**Explore Jezero in 3D** frames the crater. `?view=jezero3d` opens that view directly.

**Box a sharp area** pins the selected area's CTX imagery and terrain. The box
stays visible when zooming out; camera distance does not fade it away. **Clear**
removes that pinned area. Selecting another global map changes the background
outside the pinned rectangle; inside it, the pinned CTX imagery remains on top.
Actual elevation is kept continuous across the globe to avoid artificial cliffs
along a box's boundary. The automatic region preview is not a pinned box and
continues to fade at distant camera positions. A small box can occupy less than a screen pixel from
far away, and fine features become visible as it fills more of the screen.

The source imagery is approximately **5 m/pixel**, while the global elevation
grid is **200 m/pixel**, with **20 m/pixel elevation inside the Jezero survey**.
Zooming closer magnifies the best available samples;
it does not reveal measured small-object heights absent from the elevation
source. No relief is inferred from the light and dark parts of the photograph.
CTX photo tiles pass through a local validator. Some upstream PNGs return HTTP
200 but are truncated and cannot be decoded. A damaged tile uses the correctly
cropped portion of a valid coarser parent photo until finer valid tiles load;
no missing pixels are synthesized. This fallback can temporarily reduce image
detail but does not alter elevation. Sources and response headers retain the
fallback resolution information.

Install the verified regional survey once per checkout (about 86 MiB):

```sh
python jezero_terrain.py --download
```

The source and validity mask live in ignored `data/`; they are not committed to
Git. When the source is missing or unavailable, the app retains global terrain
and labels the missing regional detail. Requests do not initiate large downloads.
`/api/terrain/jezero` reports actual availability, coverage, native resolution,
elevation range, source link and processing details.

Regional terrain uses geographic 257-by-257 vertex grids at levels 8–11, reaching
approximately 20 m sample spacing. The USGS CTX heights are MOLA controlled.
Within 1 km of survey edges or no-data holes, display tiles blend the two real
elevation products; the measured CTX heights remain unmodified in the interior.
Shared tile-edge samples are identical. Global heights outside the survey retain
the original source; no procedural mountains or craters are added.

Source references:

- [Murray Lab CTX product documentation](https://murray-lab.caltech.edu/CTX/V01/TilePages/)
  describes the 5 m imagery and its coverage. The application uses the CTX1
  service used by [Caltech's viewer](https://murray-lab.caltech.edu/CTX/V01/SceneView/MurrayLabCTXmosaic.html).
  CTX1's service description still mentions beta01, so the application does not
  promise a particular imagery release beyond this served source.
- [USGS global elevation inventory](https://fdp.astrogeology.usgs.gov/fdp/mars/)
  documents the 200 m MOLA/HRSC blend.
- [USGS Mars 2020 CTX elevation mosaic](https://astrogeology.usgs.gov/search/map/mars_2020_science_investigation_ctx_dem_mosaic)
  documents the Jezero 20 m stereo-derived elevation product. Its original
  [GeoTIFF](https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/ScienceInvestigationMaps_JPL/M20_JezeroCrater_CTXDEM_20m.tif)
  supplies the regional terrain.
- [Esri's official Mars example](https://developers.arcgis.com/javascript/latest/sample-code/mars/)
  uses the same MDEM200M elevation service, credited to NASA, ESA, HRSC,
  Goddard Space Flight Center, USGS Astrogeology and Esri.

Native service limits are CTX imagery level 12 (approximately 5.09 m per pixel
in the north-south direction), MOLA/Viking imagery level 7, and MDEM200M terrain
level 7. The generic service metadata advertises finer imagery levels that are
not actually served. Direct CTX1 requests at Jezero, Gale, Olympus Mons and
Valles Marineris returned images at level 12 and HTTP 400 at level 13 on
2026-11-15; Jezero levels 14 through 17 also returned HTTP 400. Cesium magnifies
the last available image and upsamples the last available terrain instead of
requesting those nonexistent finer tiles. Source gaps and artifacts are not
filled with invented measurements.

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
node docs/planner/terrain_navigation_test.mjs
node docs/planner/terrain_failure_test.mjs
node docs/planner/terrain_relief_test.mjs
node docs/planner/time_slider_test.mjs
```

Set `MARSWALK_TEST_URL` for another app URL, `CHROME` for an existing Chrome
executable, or `PLAYWRIGHT_MODULE` for an importable Playwright module URL.
Reports and screenshots go to a temporary directory printed by each script;
`MARSWALK_AUDIT_DIR` selects a specific output directory.
`MARSWALK_RENDER_SCALE=0.5` reduces raster resolution in the map-selection,
navigation, relief and failure audits on software-rendered machines; it does not
change the app default or terrain coordinates. Omit it for full raster resolution.

The map test checks every enabled view, retained annotations, regional transitions,
and late weather/terrain responses. The slider test uses real Control+A selection,
mouse drags and keyboard input across four viewport sizes. Its optional
`MARSWALK_SLIDER_MODE=fixture` mode isolates the controls from the globe.

The terrain test uses mouse gestures to tilt, zoom and draw boxes; checks pinning
at several camera distances, clearing, terrain picking and dateline crossing;
and records the actual requested source levels and rendering errors.
The failure test intercepts elevation metadata to check visible errors, retry,
and clearing a box while terrain loads. Set `MARSWALK_TERRAIN_WEATHER=1` to also
check pinned-photo ordering over real pressure data and clearing back to weather.
The relief audit compares rendered height amplification with unchanged physical
DEM samples, checks scale synchronization and camera clearance, and captures
Jezero, Olympus Mons and Gale. `node docs/planner/regional_terrain_test.cjs` checks
the hybrid provider's child masks, throttling, cache buffers and missing-data
fallback. `tests/test_jezero_terrain.py` checks the regional backend and tile edges.

Backend map-source and dateline checks are in `tests/test_murray.py`. Game handoff,
region, season and route checks are documented in `docs/game/README.md`.

These checks cover specific regressions; they do not establish that all external
map services are always available or that every browser/device has been tested.
