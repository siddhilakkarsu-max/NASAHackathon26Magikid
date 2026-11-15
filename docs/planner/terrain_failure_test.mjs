import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const out = process.env.MARSWALK_AUDIT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'marswalk-terrain-failure-'));
await fs.mkdir(out, { recursive: true });
console.log('Audit artifacts: ' + out);
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const checks = [], pageErrors = [], renderErrors = [], releases = [];
const metadata = url => /^\/murray\/elevation\/?$/.test(url.pathname);
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
let page, failure;

async function open() {
  const p = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  p.setDefaultTimeout(45000);
  p.on('pageerror', error => pageErrors.push(String(error)));
  await p.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.locator('#startExploring').click();
  await p.waitForFunction(() => murray.defs.length && current && !viewer.camera._currentFlight &&
    document.querySelector('#globalLayer option[value="map:ctx"]'));
  await p.evaluate(scale => {
    viewer.resolutionScale = scale;
    document.querySelector('#regionalMaps').open = true;
    window.terrainFailureRenderErrors = [];
    viewer.scene.renderError.addEventListener((scene, error) => window.terrainFailureRenderErrors.push(String(error)));
  }, Number(process.env.MARSWALK_RENDER_SCALE || 1));
  await p.locator('#clearBox').click();
  return p;
}

async function state() {
  return page.evaluate(() => ({
    choice: plannerLayout.globalChoice(), pinned: sharpBoxPinned,
    terrainOn: murrayOn('terrain'), loading: !!murray.state.terrain?.loading,
    hasProvider: !!murray.state.terrain?.provider,
    providerActive: !!murray.state.terrain?.provider && viewer.terrainProvider === murray.state.terrain.provider,
    flat: viewer.terrainProvider instanceof Cesium.EllipsoidTerrainProvider,
    localStatus: document.querySelector('#sharpTerrainStatus').textContent,
    localStatusHidden: document.querySelector('#sharpTerrainStatus').hidden,
    localRetryHidden: document.querySelector('#sharpTerrainRetry').hidden,
    globalStatus: document.querySelector('#murray_terrain_status').textContent,
    globalStatusHidden: document.querySelector('#murray_terrain_status').hidden,
    globalRetryHidden: document.querySelector('#murrayTerrainRetry').hidden,
    ctx: ctxLayer ? { show: ctxLayer.show, alpha: ctxLayer.alpha, index: viewer.imageryLayers.indexOf(ctxLayer) } : null,
    overlayIndexes: overlay.map(layer => viewer.imageryLayers.indexOf(layer)),
    displayedLayer, renderErrors: window.terrainFailureRenderErrors,
  }));
}

async function record(name) {
  const result = await state();
  assert.deepEqual(result.renderErrors, [], 'No Cesium render failures');
  checks.push({ name, ...result });
  console.log('PASS ' + name);
  return result;
}

async function closePage() {
  if (!page) return;
  renderErrors.push(...await page.evaluate(() => window.terrainFailureRenderErrors || []));
  await page.close();
  page = null;
}

async function pinBox() {
  // The separate interaction audit draws the two corners with real pointer input.
  // This fixture isolates service failure/recovery using the same production path.
  await page.evaluate(() => setSharpBox({ west: 77.2, south: 18.2, east: 77.6, north: 18.6 }, { persistent: true }));
}

async function failMetadata(p) {
  let requests = 0;
  await p.route(metadata, async route => {
    requests++;
    await route.fulfill({ status: 503, contentType: 'application/json',
      body: JSON.stringify({ error: { code: 503, message: 'Intentional terrain metadata failure for regression test.' } }) });
  });
  return () => requests;
}

try {
  page = await open();
  const failedRequests = await failMetadata(page);
  await pinBox();
  await page.waitForFunction(() => !murray.state.terrain?.loading && !murrayOn('terrain') &&
    !document.querySelector('#sharpTerrainStatus').hidden && !document.querySelector('#sharpTerrainRetry').hidden);
  let result = await state();
  assert(failedRequests() > 0, 'The intended metadata request was intercepted');
  assert.equal(result.pinned, true);
  assert.equal(result.flat, true, 'A failed service must not claim to have installed terrain');
  assert.match(result.localStatus, /could not load/);
  assert.equal(result.ctx?.show, true, 'Photos remain independently available after elevation failure');
  assert.equal(result.ctx?.alpha, 1);
  await record('pinned area exposes terrain service failure and regional retry');

  await page.unroute(metadata);
  await page.locator('#sharpTerrainRetry').click();
  await page.waitForFunction(() => murrayOn('terrain') && !murray.state.terrain.loading &&
    viewer.terrainProvider === murray.state.terrain.provider, null, { timeout: 120000 });
  result = await state();
  assert.equal(result.flat, false);
  assert.equal(result.localRetryHidden, true);
  assert.equal(result.globalRetryHidden, true);
  assert.match(result.localStatus, /3D terrain is on/);
  assert.equal(result.ctx?.alpha, 1);
  await record('regional retry installs the real elevation provider');

  // Optional live weather check is more expensive; use MARSWALK_TERRAIN_WEATHER=1.
  if (process.env.MARSWALK_TERRAIN_WEATHER === '1') {
    await page.evaluate(() => { document.querySelector('#globalMaps').open = true; });
    await page.locator('#globalLayer').selectOption('surface_pressure');
    await page.waitForFunction(() => displayedLayer === 'surface_pressure' ||
      document.querySelector('#layerStatus').textContent.startsWith('Layer could not load'), null, { timeout: 180000 });
    result = await state();
    assert.equal(result.displayedLayer, 'surface_pressure', 'Real pressure layer loaded');
    assert(result.overlayIndexes.length > 0);
    assert(result.overlayIndexes.every(index => index >= 0 && index < result.ctx.index), 'Pinned photos stay above weather imagery');
    assert.equal(result.providerActive, true);
    await record('pinned photos remain above the real pressure layer');
    await page.evaluate(() => { document.querySelector('#regionalMaps').open = true; });
    await page.locator('#clearBox').click();
    result = await state();
    assert.equal(result.choice, 'surface_pressure');
    assert.equal(result.displayedLayer, 'surface_pressure');
    assert.equal(result.pinned, false);
    assert.equal(result.ctx, null);
    assert.equal(result.flat, true);
    await record('clearing the pinned area preserves the selected weather map');
  }
  await page.screenshot({ path: path.join(out, 'terrain-service-recovered.png') });
  await closePage();

  // A failed global CTX terrain load must not leave a useless retry button on a
  // later map that does not need elevation and has no pinned area.
  page = await open();
  const globalFailedRequests = await failMetadata(page);
  await page.evaluate(() => { document.querySelector('#globalMaps').open = true; });
  await page.locator('#globalLayer').selectOption('map:ctx');
  await page.waitForFunction(() => !murray.state.terrain?.loading && !murrayOn('terrain') &&
    !document.querySelector('#murrayTerrainRetry').hidden);
  assert(globalFailedRequests() > 0);
  assert.equal((await state()).localRetryHidden, true, 'No pinned box means no regional retry');
  await page.locator('#globalLayer').selectOption('map:viking');
  result = await state();
  assert.equal(result.choice, 'map:viking');
  assert.equal(result.flat, true);
  assert.equal(result.globalStatus, '');
  assert.equal(result.globalStatusHidden, true);
  assert.equal(result.globalRetryHidden, true);
  assert.equal(result.localRetryHidden, true);
  await record('changing background clears irrelevant terrain failure and retry');
  await closePage();

  // Hold a genuine metadata response until after Clear. Completion may populate
  // the cache, but must not reactivate terrain or restore the removed photo box.
  page = await open();
  let seen = false, releaseMetadata;
  const gate = new Promise(resolve => { releaseMetadata = resolve; });
  releases.push(releaseMetadata);
  await page.route(metadata, async route => {
    seen = true;
    await gate;
    await route.continue().catch(() => {});
  });
  await pinBox();
  await page.waitForFunction(() => !!murray.state.terrain?.loading);
  const deadline = Date.now() + 30000;
  while (!seen && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 25));
  assert(seen, 'A real metadata request must be held');
  await page.locator('#clearBox').click();
  result = await state();
  assert.equal(result.pinned, false);
  assert.equal(result.ctx, null);
  assert.equal(result.flat, true);
  assert.equal(result.terrainOn, false);
  releaseMetadata();
  await page.waitForFunction(() => !murray.state.terrain.loading && !!murray.state.terrain.provider, null, { timeout: 120000 });
  result = await state();
  assert.equal(result.hasProvider, true, 'The genuine delayed service response completed');
  assert.equal(result.providerActive, false, 'Completion only caches the provider');
  assert.equal(result.terrainOn, false);
  assert.equal(result.flat, true);
  assert.equal(result.pinned, false);
  assert.equal(result.ctx, null);
  assert.equal(result.globalStatus, '');
  assert.equal(result.globalRetryHidden, true);
  assert.equal(result.localRetryHidden, true);
  await record('clearing while metadata loads rejects late terrain activation');
  await closePage();
  assert.deepEqual(pageErrors, []);
  assert.deepEqual(renderErrors, []);
} catch (error) {
  failure = String(error.stack || error);
  await page?.screenshot({ path: path.join(out, 'terrain-failure-audit-failed.png') }).catch(() => {});
} finally {
  releases.forEach(release => release());
  await fs.writeFile(path.join(out, 'terrain-failure-results.json'), JSON.stringify({ checks, pageErrors, renderErrors, failure }, null, 2));
  await browser.close();
}
if (failure) throw new Error(failure);
