# Planner map controls

Mars global maps has one Map view selector. Planner imagery, CTX, MOLA, Viking,
weather and radiation replace one another as full-surface maps. **Topographic map
(3D + detailed photos)** is the only map that enables elevation and camera tilt.
Detailed photos and Elevation colours are overhead views. Names, crater outlines,
rover tracks, the photo tile grid and HiRISE footprints are independent overlays.
Choosing a regional data layer restores the planner background.

Phobos and Deimos are available under **Time → Phobos & Deimos**. See
[Mars moons](MOONS.md) for controls, NASA/JPL sources, physical scale and model
limitations. Place labels hide behind Mars while the camera moves.

## Regions and 3D navigation

**Regions** in the left tool rail opens the existing region selector. Selecting
a region flies to its cataloged bounds and selects the topographic map. The
**View this region in 3D** button sits directly below the selector; **3D view**
is also available beside the map chips. Right-drag tilts the view. Choosing any
other global or regional map disables tilt and returns to an overhead camera.
Walker’s view selects topography; changing maps exits Walker’s view.

All loaded areas and named sites from `/api/sites` are available (24 choices in
the current default installation). Terrain and photos stream independently of
planning cubes. Named sites without planning data can be explored immediately;
planning and regional analysis controls become available when their data arrives.
Failures keep terrain usable and explain how to retry. Late planning responses
cannot move the camera, restore an old map, or replace a newer region selection.

## Detailed photos and terrain

The topographic map combines Murray Lab CTX imagery with the
MOLA/HRSC global elevation model served by Esri, USGS 20 m CTX stereo surveys
distributed around Mars, and verified ESA/DLR 50 m HRSC quadrangle mosaics.
The installed USGS Jezero mosaic remains preferred within its survey.
Image and elevation tiles refine
as the camera approaches the surface. Only visible tiles and the renderer's
bounded cache are needed; the entire full-resolution planet is not downloaded.
Right-drag tilts and rotates the terrain view; the mouse wheel zooms. The labeled
height control defaults to 2.7x display exaggeration and spans 1x–8x. **True scale**
restores 1x. These settings change the display only: elevation samples and mission
calculations retain their physical values. Rover and astronaut proportions are
not stretched. **Angled terrain view** frames the visible surface or pinned box;
**Explore Jezero in 3D** frames the crater. `?view=jezero3d` opens that view directly;
`?view=terrain` opens the whole planet with detailed photos and terrain selected.

**Box a sharp area** pins the selected area's CTX imagery. The box
stays visible when zooming out; camera distance does not fade it away. **Clear**
removes that pinned area. Selecting another global map changes the background
outside the pinned rectangle; inside it, the pinned CTX imagery remains on top.
Pinning photos never enables 3D on other maps. Within the topographic map,
elevation stays continuous across the globe instead of being clipped at the box.
The automatic region preview is not a pinned box and
continues to fade at distant camera positions. A small box can occupy less than a screen pixel from
far away, and fine features become visible as it fills more of the screen.

The source imagery is approximately **5 m/pixel**, while the global elevation
grid is **200 m/pixel**. The finer elevation sources have nominal **20 m CTX**
(20–36 m spacing in the catalog) and
**50 m HRSC grid spacing** where surveyed, not uniform planet-wide coverage.
The 20 verified HRSC tiles cover five published quadrangles; the USGS catalog
adds targeted stereo footprints across other longitudes and latitudes.
These are grid spacings, not guaranteed feature resolution or vertical accuracy.
The USGS notes stereo artifacts, gaps, and limits on reliably resolving small
features. The on-screen coverage note describes cataloged survey extents;
an individual point inside an extent can still have no-data or service failures.
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
Git. When the local source is missing, the other cataloged surveys remain
available and the global terrain supplies any gaps. Requests do not initiate
whole-raster downloads.
`/api/terrain/jezero` reports actual availability, coverage, native resolution,
elevation range, source link and processing details.

Regional terrain uses geographic 257-by-257 vertex grids at levels 8–11, reaching
approximately 20 m sample spacing. The USGS CTX heights are MOLA controlled.
Within 1 km of survey edges or no-data holes, display tiles blend the two real
elevation products; the measured CTX heights remain unmodified in the interior.
Shared tile-edge samples are identical. Global heights outside the survey retain
the original source; no procedural mountains or craters are added.

The detail provider indexes survey rectangles by their global parent tile and
respects each source's native detail limit (HRSC level 10; CTX level 11). The
backend streams required raster windows from official servers and caches tiles.
HRSC **DA5** areoid heights are used; **DT5** sphere heights are deliberately
excluded because they cannot be substituted without a datum conversion.
HTTP range support, native coordinate systems, and example measured heights
are documented in `hrsc50m_sources.json`. Upstream availability can temporarily
reduce detail; missing observations are not replaced with synthetic terrain.

The bundled CTX inventory contains 44,628 elevation products as retrieved on
2026-11-15, plus the 20 verified HRSC tiles. Sixteen dateline-spanning STAC
bounding boxes were resolved using their actual footprint geometries, rather
than advertising entire latitude bands as detailed coverage. Refresh this
metadata inventory with `python tools/build_terrain_catalog.py`; it does not
download the elevation archive. `/api/terrain/detail` reports the available
inventory, source counts, resolutions, credits and limitations.
Restart the server after replacing the catalog or installing the local Jezero
survey, then reload terrain so the in-memory source inventory is refreshed.

Streaming tiles carry `X-Terrain-Detail-Status`, source IDs/counts and failure
counts. Partial or global fallback responses expire quickly instead of being
cached as permanently fine data. **Reload terrain detail** replaces the active
provider and requests visible geometry again after an upstream outage; the
loading indicator shows unfinished terrain/imagery streaming. Successfully
streamed fine tiles and raw source grids remain distinct from display-only
height exaggeration. The source count is an inventory, not an assertion that
every raster pixel has been independently checked.

Source references:

- [USGS Mars CTX stereo elevation documentation](https://stac.astrogeology.usgs.gov/docs/data/mars/ctxdtms/)
  describes 20 m geoid-adjusted, MOLA-controlled DEMs, COG streaming, and quality limitations.
- [DLR HRSC regional DTM catalog](https://hrscteam.dlr.de/public/data/regionaldtms.php)
  provides the 50 m quadrangle mosaics.

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

## Stars and seasonal dust haze

The star background uses the six NASA Tycho atlas faces already bundled with
Cesium. The native skybox stays behind the globe and atmosphere; it does not
paint stars over the terrain. Its orientation is decorative, not a date-specific
Mars star chart. The checkbox under Time, season & lighting switches it off.

Seasonal dust haze is optional and off initially. It samples the existing LMD
5-degree dust climatology at the view center for the selected season. The input
is infrared dust optical depth, so its bounded mapping to visible atmospheric
scattering is explicitly illustrative—not a calibrated visible-opacity product,
live weather, or a map of individual storm clouds. The regional effect fades
away at orbital altitude. Missing data, disabling haze, or disabling atmosphere
restores the original scattering. Neither stars nor haze changes elevations,
map values, mission calculations, or terrain detail settings.

- [NASA/Goddard Tycho/Hipparcos star atlas](https://svs.gsfc.nasa.gov/3572/)
- [LMD dust climatology and scenarios](https://www-mars.lmd.jussieu.fr/mars/dust_scenarios/index.html)

## Browser regression checks

Start the app on localhost port 8001, install Playwright and its Chromium browser,
then run these scripts sequentially:

```sh
node docs/planner/map_selection_test.mjs
node docs/planner/terrain_navigation_test.mjs
node docs/planner/terrain_failure_test.mjs
node docs/planner/terrain_relief_test.mjs
node docs/planner/global_terrain_browser_test.mjs
node docs/planner/mars_sky_browser_test.mjs
node docs/planner/time_slider_test.mjs
node docs/planner/region_topography_test.mjs
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

The region audit checks every menu choice against its catalog bounds, accessible
3D controls, map exclusivity, pending/failed planning data and stale responses.
It uses real map providers but deliberately fixtures planning-job responses so
the test does not start dozens of long-running regional builds. Two named regions
are treated as not yet downloaded inside that browser, even if their local cubes
already exist; the test does not change those files. It also checks the Regions
rail section and route-control clearance with the team's wider drawer.

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
`tests/test_global_terrain.py` checks source coordinates, overlap blending, data
gaps, dateline footprints and cache recovery. `global_terrain_test.cjs` compares
the multi-source index to an independent spatial oracle and checks cancellation.
`mars_sky_test.js` checks dust lifecycle, stale samples, missing data and baseline
restoration. The sky browser test uses real seasonal opacity samples; the global
terrain browser test compares Cesium heights with the raw streamed tile values.

Backend map-source and dateline checks are in `tests/test_murray.py`. Game handoff,
region, season and route checks are documented in `docs/game/README.md`.

These checks cover specific regressions; they do not establish that all external
map services are always available or that every browser/device has been tested.
