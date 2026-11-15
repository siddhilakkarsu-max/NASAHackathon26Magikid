// Real app + real terrain/imagery. Planning-job responses are deliberate fixtures:
// exercising every region must not start dozens of background scientific builds.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const out = process.env.MARSWALK_AUDIT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'marswalk-regions-'));
await fs.mkdir(out, { recursive: true });
const checks = [], errors = [];
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
page.setDefaultTimeout(45000);
page.on('pageerror', e => errors.push(String(e)));
const pass = name => { checks.push(name); console.log('PASS ' + name); };
let failure;
const choose = async value => {
  if (!await page.locator('#globalLayer').isVisible()) {
    await page.locator('#gmRail button[data-section="globalMaps"]').click();
  }
  await page.locator('#globalLayer').selectOption(value);
  await page.waitForFunction(value => plannerLayout.globalChoice() === value, value);
};
const selectRegion = async value => {
  await page.locator('#regionsButton').click();
  await page.locator('#region').selectOption(value);
};
const state = () => page.evaluate(() => ({ choice: plannerLayout.globalChoice(), region: current?.region,
  pending: current?.planningReady === false, selected: document.querySelector('#region').value,
  tilt: cameraControls.enableTilt, look: cameraControls.enableLook, flat: viewer.terrainProvider === flatTerrain, pitch: viewer.camera.pitch,
  center: viewCenter(), terrain: murrayOn('terrain'), photos: murrayOn('ctx'),
  controls: !document.querySelector('#terrainDisplayControls').hidden,
  view3d: !document.querySelector('#map3dView').hidden,
  planDisabled: document.querySelector('#runMission').disabled, status: document.querySelector('#areaStatus').textContent }));
try {
  await page.addInitScript(() => localStorage.setItem('mapManualSeen', '1'));
  // Keep two planning downloads pending in this browser even if the developer
  // has already built every cube locally. Preserve all other metadata and files.
  const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
  const catalogResponse = await page.request.get(base + '/api/sites');
  assert(catalogResponse.ok(), 'The live region catalog must be available');
  const pendingKeys = (await catalogResponse.json()).sites.slice(0, 2).map(site => site.site);
  assert.equal(pendingKeys.length, 2, 'Two named regions are needed for cancellation checks');
  await page.route('**/api/regions', async route => {
    const response = await route.fetch();
    assert(response.ok(), 'The live planning metadata must be available');
    const metadata = await response.json();
    await route.fulfill({ response, json: { ...metadata,
      regions: metadata.regions.filter(region => !pendingKeys.includes(region.region)) } });
  });
  await page.route('**/api/sites/build', route => route.fulfill({ json: {
    region: route.request().postDataJSON().site, ready: false, status: 'building' } }));
  await page.route('**/api/sites/build/*', route => route.fulfill({ json: {
    region: route.request().url().split('/').pop(), ready: false, status: 'building' } }));
  await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
  await page.locator('#startExploring').click();
  await page.waitForFunction(() => current && namedSites.length && murray.defs.length);
  await page.evaluate(scale => {
    viewer.resolutionScale = scale; viewer.camera.cancelFlight();
    window.regionRenderErrors = [];
    viewer.scene.renderError.addEventListener((_, e) => regionRenderErrors.push(String(e)));
    document.querySelector('#globeLighting').checked = false; globeLighting.setEnabled(false);
  }, Number(process.env.MARSWALK_RENDER_SCALE || 0.5));
  await page.locator('#regionsButton').click();
  await page.waitForFunction(() => document.body.classList.contains('drawer'));
  assert(await page.locator('#region').isVisible());
  assert.equal(await page.locator('#missionSetup').isVisible(), false);
  assert.equal(await page.locator('#globalMaps').isVisible(), false);
  pass('Regions button opens the updated teammate drawer and accessible region selector');
  const choices = await page.locator('#region option').evaluateAll(options => options.map(o => o.value).filter(v => v !== 'here'));
  const catalog = await page.evaluate(() => namedSites.map(s => s.site));
  for (const key of catalog) assert(choices.includes(key) || choices.includes('site:' + key), key);
  assert.equal(new Set(choices).size, choices.length);
  for (const value of choices) {
    await selectRegion(value);
    const key = value.replace(/^site:/, '');
    await page.waitForFunction(key => current?.region === key && topographicSelected() && !viewer.camera._currentFlight, key);
    const s = await state();
    assert.equal(s.tilt, true); assert.equal(s.look, true); assert.equal(s.photos, true); assert.equal(s.controls, true);
    assert(await page.locator('#region3dView').isVisible());
    const rect = await page.evaluate(() => current.rect);
    assert(s.center && s.center.lat >= rect.south - 0.03 && s.center.lat <= rect.north + 0.03, key + ' latitude');
    assert(s.center.lon >= rect.west - 0.03 && s.center.lon <= rect.east + 0.03, key + ' longitude');
    if (value.startsWith('site:')) assert(s.pending && s.planDisabled, 'Never plan in the previous region');
  }
  pass(`All ${choices.length} region choices fly to their real catalog bounds and select topographic imagery`);
  await selectRegion('jezero');
  await page.waitForFunction(() => current?.region === 'jezero' && topographicSelected() && !murray.state.terrain.loading && viewer.terrainProvider === murray.state.terrain.provider,
    null, { timeout: 120000 });
  await page.locator('#region3dView').click();
  await page.waitForFunction(() => viewer.camera.pitch > -1.2 && !viewer.camera._currentFlight, null, { timeout: 120000 });
  await page.locator('#drawerClose').click();
  await page.locator('#map3dView').click();
  await page.waitForFunction(() => viewer.camera.pitch > -1.2 && !viewer.camera._currentFlight, null, { timeout: 120000 });
  assert.equal((await state()).planDisabled, false);
  await page.screenshot({ path: path.join(out, 'region-topographic-3d.png') });
  pass('Jezero opens real streamed terrain; the visible 3D view button tilts the camera');
  await page.locator('#regionsButton').click();
  await page.evaluate(() => {
    document.querySelector('#globalMaps').open = true;
    setSharpBox({ west: 77.2, south: 18.2, east: 77.6, north: 18.6 }, { persistent: true });
  });
  for (const value of ['map:ctx', 'map:mola', 'map:viking', '', 'surface_pressure']) {
    await choose(value);
    const s = await state();
    assert.equal(s.flat, true); assert.equal(s.terrain, false); assert.equal(s.tilt, false); assert.equal(s.look, false);
    assert.equal(s.controls, false); assert(Math.abs(s.pitch + Math.PI / 2) < 1e-5);
    assert.equal(await page.locator('#region3dView').isVisible(), false);
    await page.waitForFunction(() => document.querySelector('#map3dView').hidden);
    assert.equal(await page.locator('#map3dView').isVisible(), false);
    assert(await page.evaluate(() => sharpBoxPinned && ctxLayer.show && ctxLayer.alpha === 1));
  }
  pass('Every other surface disables 3D and resets tilt, even with a pinned photo overlay');
  await page.evaluate(() => routePlayback.setRoute('audit', [{ lat: 18.45, lon: 77.45 },
    { lat: 18.451, lon: 77.451 }], 'astronaut', 'Interaction test fixture'));
  const drawerBox = await page.locator('#panel').boundingBox();
  const routeBox = await page.locator('#routePlayback').boundingBox();
  assert(routeBox.x >= drawerBox.x + drawerBox.width, 'The wider drawer must not cover route controls');
  await page.locator('#walkerView').click();
  await page.waitForFunction(() => routePlayback.walking() && topographicSelected() &&
    document.querySelector('#walkerStatus').textContent.includes('eye height'), null, { timeout: 120000 });
  await choose('map:ctx');
  assert.equal(await page.evaluate(() => routePlayback.walking()), false);
  assert.equal((await state()).tilt, false);
  await page.evaluate(() => routePlayback.clear());
  pass('Walker view selects topography; switching maps exits it and cancels its tilted camera');
  // An API ignoring cancellation deliberately completes after a newer region wins.
  const [first, second] = pendingKeys;
  await page.evaluate(key => {
    window.originalRegionApi = api;
    window.buildHeld = false;
    api = async function(url, body, signal) {
      if (url === '/api/sites/build' && body.site === key) {
        window.buildHeld = true;
        return new Promise(resolve => window.releaseRegionBuild = () => resolve({ ready: true, region: key, status: 'done' }));
      }
      return window.originalRegionApi(url, body, signal);
    };
  }, first);
  await selectRegion('site:' + first);
  await page.waitForFunction(() => window.buildHeld);
  await selectRegion('site:' + second);
  await page.waitForFunction(key => current?.region === key && topographicSelected() && !viewer.camera._currentFlight, second);
  await choose('map:viking');
  await page.evaluate(() => { window.releaseRegionBuild(); api = window.originalRegionApi; });
  await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 100)));
  let s = await state();
  assert.equal(s.region, second); assert.equal(s.choice, 'map:viking');
  await page.evaluate(() => fillRegions());
  assert.equal((await state()).selected, 'site:' + second);
  pass('Late planning completion cannot change a newer region or map; metadata refresh preserves pending selection');
  await selectRegion('here');
  assert.equal((await state()).pending, false); assert.equal((await state()).planDisabled, false);
  pass('Anywhere cancels pending region selection and restores a usable planner');
  // A synthetic planning metadata response tests successful completion without
  // pretending to download a real cube. The live geographic catalog is retained.
  await page.evaluate(key => {
    window.originalRegionApi = api;
    window.readyFixture = null;
    api = async function(url, body, signal) {
      if (url === '/api/sites/build' && body.site === key) {
        return new Promise(resolve => window.completePlanning = () => {
          window.readyFixture = { ...regions[0], region: key, rect: { ...current.rect }, label: current.label };
          resolve({ ready: true, region: key, status: 'done' });
        });
      }
      if (url === '/api/regions' && window.readyFixture) return { regions: [...regions, window.readyFixture] };
      return window.originalRegionApi(url, body, signal);
    };
  }, first);
  await selectRegion('site:' + first);
  await page.waitForFunction(() => typeof window.completePlanning === 'function' && topographicSelected() && !viewer.camera._currentFlight);
  await choose('map:mola');
  const beforeReady = await page.evaluate(() => ({ camera: Cesium.Cartesian3.clone(viewer.camera.positionWC) }));
  await page.evaluate(() => window.completePlanning());
  await page.waitForFunction(key => current?.region === key && current.planningReady !== false && document.querySelector('#region').value === key, first);
  assert.equal((await state()).choice, 'map:mola');
  assert.equal((await state()).planDisabled, false);
  assert.deepEqual(await page.evaluate(() => ({ camera: Cesium.Cartesian3.clone(viewer.camera.positionWC) })), beforeReady);
  await page.evaluate(async () => {
    api = window.originalRegionApi;
    regions = (await api('/api/regions')).regions;
    fillRegions('jezero'); document.querySelector('#region').onchange();
  });
  pass('Successful planning completion enables controls without changing the selected map or camera');
  // Failure of planning data does not remove usable topography or claim readiness.
  await page.unroute('**/api/sites/build');
  await page.route('**/api/sites/build', route => route.fulfill({ status: 503, json: { detail: 'Deliberate planning fixture failure' } }));
  await selectRegion('site:' + first);
  await page.waitForFunction(() => document.querySelector('#areaStatus').textContent.includes("couldn't load"));
  s = await state();
  assert(s.pending && s.planDisabled); assert.equal(s.choice, 'map:terrain'); assert.equal(s.tilt, true);
  pass('Planning download failure leaves topography usable and explains retry without invented data');
  await selectRegion('jezero');
  await page.waitForFunction(() => current?.region === 'jezero' && topographicSelected());
  await page.locator('#drawerClose').click();
  assert.deepEqual(errors, []);
  assert.deepEqual(await page.evaluate(() => regionRenderErrors), []);
  pass('No uncaught JavaScript or Cesium rendering errors during region and map transitions');
} catch (error) {
  failure = String(error.stack || error);
  await page.screenshot({ path: path.join(out, 'region-topography-failure.png') }).catch(() => {});
} finally {
  await fs.writeFile(path.join(out, 'region-topography-results.json'), JSON.stringify({ checks, errors, failure }, null, 2));
  await browser.close();
}
if (failure) throw new Error(failure);
