import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const out = process.env.MARSWALK_AUDIT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'marswalk-relief-'));
await fs.mkdir(out, { recursive: true });
console.log('Audit artifacts: ' + out);
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const checks = [], pageErrors = [], regionalRequests = [], sourceFailures = [];
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
let page, failure;
const record = check => { checks.push(check); console.log('PASS ' + check.name); };

async function frames(n = 5) {
  await page.evaluate(n => new Promise(resolve => {
    const frame = () => --n <= 0 ? resolve() : requestAnimationFrame(frame);
    requestAnimationFrame(frame);
  }), n);
}
async function state() {
  return page.evaluate(() => ({ scale: viewer.scene.verticalExaggeration,
    input: +document.querySelector('#terrainScale').value,
    regionalInput: +document.querySelector('#sharpTerrainScale').value,
    label: document.querySelector('#terrainScaleValue').textContent,
    regionalLabel: document.querySelector('#sharpTerrainScaleValue').textContent,
    terrain: murrayOn('terrain'),
    flat: viewer.terrainProvider instanceof Cesium.EllipsoidTerrainProvider,
    pitch: viewer.camera.pitch, heading: viewer.camera.heading,
    cameraHeight: viewer.camera.positionCartographic.height,
    underground: viewer.scene.cameraUnderground,
    renderErrors: window.reliefRenderErrors }));
}
async function choose(value) {
  await page.evaluate(() => { document.querySelector('#globalMaps').open = true; });
  await page.locator('#globalLayer').selectOption(value);
  if (value === 'map:terrain') {
    await page.waitForFunction(() => murrayOn('terrain') && !murray.state.terrain.loading &&
      viewer.terrainProvider === murray.state.terrain.provider, null, { timeout: 120000 });
  }
  await frames();
}
async function nadir(lon = 77.45, lat = 18.45, height = 5000) {
  await page.evaluate(({lon, lat, height}) => {
    viewer.camera.cancelFlight();
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(lon, lat, height, MARS),
      orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 } });
    viewer.scene.requestRender();
  }, {lon, lat, height});
  await frames();
  await page.waitForFunction(({lon, lat}) => Number.isFinite(viewer.scene.globe.getHeight(
    Cesium.Cartographic.fromDegrees(lon, lat))), {lon, lat}, { timeout: 120000 });
}
async function rawSamples(level, locations) {
  return page.evaluate(async ({level, locations}) => {
    const positions = locations.map(p => Cesium.Cartographic.fromDegrees(p[0], p[1]));
    const sampled = await Cesium.sampleTerrain(viewer.terrainProvider, level, positions);
    return sampled.map(p => p.height);
  }, {level, locations});
}
async function renderedHeight(lon = 77.45, lat = 18.45) {
  return page.evaluate(({lon, lat}) => viewer.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(lon, lat)), {lon, lat});
}
async function waitRenderedHeight(expected, tolerance = 25, lon = 77.45, lat = 18.45) {
  // Metadata/provider readiness is not mesh readiness. Wait until the measured
  // local elevation has replaced early coarse global tiles at this location.
  await page.waitForFunction(({expected, tolerance, lon, lat}) => {
    const height = viewer.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(lon, lat));
    return Number.isFinite(height) && Math.abs(height - expected) <= tolerance;
  }, {expected, tolerance, lon, lat}, { timeout: 120000 });
}
async function settleVisibleTiles() {
  // The camera may reveal new real image/terrain tiles after its flight ends.
  // Record slow external services without pretending an idle camera means all
  // imagery is ready; geometric assertions have their own required waits.
  let ready = true;
  try {
    await page.waitForFunction(() => viewer.scene.globe.tilesLoaded, null, { timeout: 20000 });
  } catch (error) {
    if (error.name !== 'TimeoutError') throw error;
    ready = false;
  }
  await frames(2);
  return ready;
}
async function setRange(id, value) {
  // Dispatch the native range's input event; right-drag and wheel gestures are
  // covered by terrain_navigation_test. This isolates scaling from camera motion.
  await page.locator('#' + id).evaluate((input, value) => {
    input.value = String(value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, value);
  await frames();
}
async function waitFlight() {
  await page.waitForFunction(() => !viewer.camera._currentFlight, null, { timeout: 60000 });
  await frames();
}

try {
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(60000);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  page.on('pageerror', error => pageErrors.push(String(error)));
  page.on('request', request => {
    const match = new URL(request.url()).pathname.match(/^\/terrain\/(?:jezero|detail)\/(\d+)\/(\d+)\/(\d+)\.bin$/);
    if (match) regionalRequests.push({ level: +match[1], y: +match[2], x: +match[3] });
  });
  page.on('response', response => {
    if (response.status() >= 400 && /\/terrain\/(?:jezero|detail)\//.test(response.url())) {
      sourceFailures.push({ url: response.url(), status: response.status() });
    }
  });
  await page.addInitScript(() => localStorage.setItem('mapManualSeen', '1'));
  await page.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('#startExploring').click();
  await page.locator('#regionsButton').click();
  await page.waitForFunction(() => murray.defs.length && current && !viewer.camera._currentFlight &&
    document.querySelector('#globalLayer option[value="map:ctx"]'));
  await page.evaluate(scale => {
    viewer.resolutionScale = scale;
    window.reliefRenderErrors = [];
    viewer.scene.renderError.addEventListener((scene, error) => window.reliefRenderErrors.push(String(error)));
    // Geometry comparisons at distant longitudes should not be obscured by the
    // unrelated night-side lighting control.
    document.querySelector('#globeLighting').checked = false;
    document.querySelector('#globeLighting').dispatchEvent(new Event('change'));
  }, Number(process.env.MARSWALK_RENDER_SCALE || 1));
  const metadataResponse = await page.request.get(base + '/api/terrain/jezero');
  assert(metadataResponse.ok());
  const metadata = await metadataResponse.json();
  assert.equal(metadata.available, true, 'The actual local Jezero raster must be available for this integration audit');
  assert.equal(metadata.resolution_m, 20);
  const localLevel = metadata.maximum_level;
  assert(Number.isInteger(localLevel) && localLevel > 7);
  await choose('map:terrain');
  let s = await state();
  assert.equal(s.scale, 2.7); assert.equal(s.input, 2.7); assert.equal(s.regionalInput, 2.7);
  assert.equal(s.flat, false);
  assert(await page.locator('#terrainDisplayControls').isVisible());
  record({ name: 'Topographic map starts with visibly labelled 2.7x terrain relief and real regional elevation',
    resolution: metadata.resolution_m, nativeLevel: localLevel });

  await page.locator('#terrainTrueScale').click();
  await nadir();
  const samples = [[77.45, 18.45], [77.4, 18.5], [77.5, 18.5]];
  const before = await rawSamples(localLevel, samples);
  assert(before.every(Number.isFinite), 'The regional terrain provider returns real finite samples');
  await waitRenderedHeight(before[0]);
  const one = await renderedHeight();
  assert(Number.isFinite(one) && Math.abs(one) > 100, 'A nonzero rendered elevation is required for the scale check');
  assert.equal((await state()).scale, 1);
  record({ name: 'True-scale reset uses 1x and high-resolution Jezero sampling succeeds', rawHeights: before, renderedHeight: one });

  await setRange('terrainScale', 2.7);
  await waitRenderedHeight(before[0] * 2.7, 25 * 2.7);
  const boosted = await renderedHeight();
  const after = await rawSamples(localLevel, samples);
  assert.deepEqual(after, before, 'Display exaggeration must not modify source elevation values');
  // A scale change can trigger finer visible tiles. Allow a small terrain-LOD
  // discrepancy, while requiring the measured relief to change by the requested factor.
  assert(Math.abs(boosted - one * 2.7) < Math.max(80, Math.abs(one) * 0.03),
    `Rendered elevation must follow 2.7x: true=${one}, boosted=${boosted}`);
  s = await state();
  assert.equal(s.input, 2.7); assert.equal(s.regionalInput, 2.7);
  assert.match(s.label, /2\.7/); assert.match(s.regionalLabel, /2\.7/);
  record({ name: 'Rendered relief changes while the physical DEM samples remain unchanged', trueHeight: one, exaggeratedHeight: boosted });

  await setRange('terrainScale', 8);
  await waitRenderedHeight(before[0] * 8, 25 * 8);
  const deepFloor = await renderedHeight();
  assert(Number.isFinite(deepFloor) && deepFloor < 0, 'This regression needs a crater floor below the reference surface');
  await nadir(77.45, 18.45, deepFloor + 150);
  assert((await state()).cameraHeight < 0, 'Begin close to the displayed floor, below zero datum');
  await page.evaluate(() => {
    const input = document.querySelector('#terrainScale');
    // All events occur before the next rendered frame, as with a fast gesture.
    for (const value of [7, 4, 2.7, 1]) {
      input.value = String(value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  await frames(10);
  const clearance = await page.evaluate(() => {
    const location = viewer.camera.positionCartographic;
    return { height: location.height, ground: viewer.scene.globe.getHeight(location),
      pendingGuard: terrainClearanceRemove !== null };
  });
  s = await state();
  assert.equal(s.scale, 1); assert.equal(s.input, 1); assert.equal(s.regionalInput, 1);
  assert.equal(s.underground, false);
  assert(Number.isFinite(clearance.ground) && clearance.height - clearance.ground >= 40,
    'Reducing exaggeration must keep the camera above the rising crater floor');
  assert.equal(clearance.pendingGuard, false, 'The one-shot camera guard must remove its listener');
  assert.deepEqual(await rawSamples(localLevel, samples), before);
  record({ name: 'Rapid scale changes below zero datum keep the camera above terrain and leave data unchanged', clearance });
  await setRange('terrainScale', 2.7);
  await nadir();

  await page.locator('#terrainJezero').click();
  await waitFlight();
  const jezeroTilesReady = await settleVisibleTiles();
  s = await state();
  assert(s.pitch > -1.4 && s.pitch < -0.1, 'The Jezero shortcut gives an oblique, not overhead, view');
  assert.equal(s.underground, false);
  await page.screenshot({ path: path.join(out, 'jezero-relief-2p7x.png') });
  record({ name: 'Jezero shortcut frames an angled crater view', pitch: s.pitch, cameraHeight: s.cameraHeight, tilesReady: jezeroTilesReady });

  await page.evaluate(() => setSharpBox({west:77.3, south:18.35, east:77.65, north:18.65}, {persistent:true}));
  await page.evaluate(() => { document.querySelector('#regionalMaps').open = true; });
  assert(await page.locator('#sharpTerrainDisplayControls').isVisible());
  await setRange('sharpTerrainScale', 4);
  s = await state();
  assert.equal(s.scale, 4); assert.equal(s.input, 4); assert.equal(s.regionalInput, 4);
  await page.locator('#sharpTerrainAngledView').click();
  await waitFlight();
  s = await state();
  assert(s.pitch > -1.4 && s.pitch < -0.1); assert.equal(s.underground, false);
  assert(await page.evaluate(() => sharpBoxPinned && ctxLayer.show && ctxLayer.alpha === 1));
  await page.locator('#sharpTerrainTrueScale').click();
  s = await state();
  assert.equal(s.scale, 1); assert.equal(s.input, 1); assert.equal(s.regionalInput, 1);
  assert.deepEqual(await rawSamples(localLevel, samples), before);
  record({ name: 'Pinned-area controls stay synchronized, tilt their area and restore true scale without changing data' });
  await page.locator('#clearBox').click();

  await choose('map:terrain');
  await setRange('terrainScale', 2.7);
  for (const site of [
    {name:'olympus', rect:{west:-136, south:16, east:-131, north:21}, points:[[-133.8,18.65],[-135,17]]},
    {name:'gale', rect:{west:137.2, south:-5.9, east:138.5, north:-4.6}, points:[[137.8,-5.4],[137.4,-5.1]]},
  ]) {
    const heights = await rawSamples(7, site.points);
    assert(heights.every(Number.isFinite), site.name + ' retains the measured global terrain outside Jezero');
    assert(Math.abs(heights[0] - heights[1]) > 10, site.name + ' must contain nonflat measured relief');
    await page.evaluate(rect => angledTerrainView(rect), site.rect);
    await waitFlight();
    const tilesReady = await settleVisibleTiles();
    assert.equal((await state()).underground, false);
    await page.screenshot({ path: path.join(out, site.name + '-relief-2p7x.png') });
    record({ name: site.name + ' uses nonflat real global terrain in an angled view', heights, tilesReady });
  }

  assert(await page.evaluate(() => roverEntity.model.enableVerticalExaggeration.getValue(Cesium.JulianDate.now()) === false),
    'Terrain exaggeration must not stretch the hover rover model');
  assert(regionalRequests.some(tile => tile.level === localLevel), 'Actual fine regional terrain tiles were requested');
  assert(regionalRequests.every(tile => tile.level <= localLevel), 'No unsupported regional resolution is requested');
  assert.deepEqual(sourceFailures, []);
  assert.deepEqual((await state()).renderErrors, []);
  assert.deepEqual(pageErrors, []);
  record({ name: 'Regional tiles respect source resolution; rendering and model proportions remain valid',
    requestedLevels: [...new Set(regionalRequests.map(tile => tile.level))].sort((a,b) => a-b) });
} catch (error) {
  failure = String(error.stack || error);
  console.error('Relief failure state:', JSON.stringify(await page?.evaluate(() => ({ scale: viewer.scene.verticalExaggeration,
    height: viewer.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(77.45, 18.45)),
    tilesLoaded: viewer.scene.globe.tilesLoaded,
    rendered: viewer.scene.globe._surface._tilesToRender.map(t => ({level:t.level,
      scale:t.data?.mesh?.encoding?.exaggeration})),
  })).catch(() => null)));
  await page?.screenshot({ path: path.join(out, 'terrain-relief-failure.png') }).catch(() => {});
} finally {
  await fs.writeFile(path.join(out, 'terrain-relief-results.json'), JSON.stringify({checks, pageErrors, regionalRequests, sourceFailures, failure}, null, 2));
  await browser.close();
}
if (failure) throw new Error(failure);
