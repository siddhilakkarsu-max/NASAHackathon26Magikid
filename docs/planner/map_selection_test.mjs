import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import os from 'node:os';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const out = process.env.MARSWALK_AUDIT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'marswalk-audit-'));
await fs.mkdir(out, { recursive: true });
console.log('Audit artifacts: ' + out);
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const checks = [], pageErrors = [], sourceFailures = [];
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
let page, failure;
async function open() {
  const p = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  p.setDefaultTimeout(45000);
  p.on('pageerror', e => pageErrors.push(String(e)));
  await p.addInitScript(() => localStorage.setItem('mapManualSeen', '1'));
  p.on('response', r => { if (r.status() >= 400 && /\/OnMars\/|\/murray\/ctx\//.test(r.url())) sourceFailures.push({url:r.url(), status:r.status()}); });
  p.on('requestfailed', r => { if (/\/OnMars\/|\/murray\/ctx\//.test(r.url())) sourceFailures.push({url:r.url(), error:r.failure()?.errorText}); });
  await p.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.locator('#startExploring').click();
  await p.locator('#gmRail button[data-section="globalMaps"]').click();
  await p.waitForFunction(() => murray.defs.length && current && !viewer.camera._currentFlight && document.querySelector('#globalLayer option[value="map:terrain"]'));
  await p.evaluate(scale => {
    viewer.resolutionScale = scale;
    document.querySelector('#globalMaps').open = true;
    window.selectionRenderErrors = [];
    viewer.scene.renderError.addEventListener((scene, error) => window.selectionRenderErrors.push(String(error)));
  }, Number(process.env.MARSWALK_RENDER_SCALE || 1));
  return p;
}
async function state(p = page) {
  return p.evaluate(() => ({ choice: plannerLayout.globalChoice(), visible: document.querySelector('#globalLayer').value,
    canonical: document.querySelector('#layer').value, regional: document.querySelector('#regionalLayer').value,
    selectedMap: murray.selectedMap,
    activeSurfaces: murray.defs.filter(d => ['terrain','tiles'].includes(d.kind) && murrayOn(d.id)).map(d => d.id),
    imagerySurfaces: murray.defs.filter(d => d.kind === 'tiles' && murray.state[d.id]?.layer && imageLayers().contains(murray.state[d.id].layer)).map(d => d.id),
    own: [baseMap.show, trekLayer.show, ...(ctxLayer ? [ctxLayer.show] : []), ...(photoLayer ? [photoLayer.show] : [])],
    flat: viewer.terrainProvider instanceof Cesium.EllipsoidTerrainProvider, depthTest: viewer.scene.globe.depthTestAgainstTerrain,
    overlayCount: overlay.length, displayedLayer, radiation: !document.querySelector('#radiationControls').hidden,
    status: document.querySelector('#layerStatus').textContent,
    annotations: Object.fromEntries(['names','quads','m2020'].map(id => [id, { on: murrayOn(id), checked: !!document.querySelector('#murray_' + id)?.checked,
      attached: !!murray.state[id]?.ds && viewer.dataSources.contains(murray.state[id].ds) }])),
    renderErrors: window.selectionRenderErrors }));
}
async function check(value, p = page, annotations = true) {
  const mapId = value.startsWith('map:') ? value.slice(4) : null;
  const weather = !!value && !mapId;
  const own = !weather && !mapId;
  const s = await state(p);
  assert.equal(s.choice, value); assert.equal(s.visible, value);
  assert.equal(s.canonical, mapId ? '' : value); assert.equal(s.regional, '');
  assert.equal(s.selectedMap, mapId);
  assert.deepEqual(s.activeSurfaces, mapId === 'terrain' ? ['ctx', 'terrain'] : mapId ? [mapId] : []);
  assert.deepEqual(s.imagerySurfaces, mapId === 'terrain' ? ['ctx'] : mapId ? [mapId] : []);
  assert(s.own.every(visible => visible === own), 'Planner imagery visibility must follow surface choice: ' + JSON.stringify(s));
  const terrain = mapId === 'terrain';
  assert.equal(s.flat, !terrain); assert.equal(s.depthTest, terrain);
  assert.equal(s.overlayCount, weather ? 1 : 0); assert.equal(s.displayedLayer, weather ? value : '');
  assert.equal(s.radiation, value === 'radiation_dose');
  assert.equal(s.status, '', 'Selected layer failed: ' + s.status);
  assert.deepEqual(s.renderErrors, []);
  if (annotations) for (const [id, a] of Object.entries(s.annotations)) assert.deepEqual(a, { on:true, checked:true, attached:true }, id + ' overlay must persist');
  return s;
}
async function choose(value, p = page, annotations = true) {
  if (!await p.locator('#globalLayer').isVisible()) {
    await p.locator('#gmRail button[data-section="globalMaps"]').click();
  }
  await p.locator('#globalLayer').selectOption(value);
  if (value === 'map:terrain') await p.waitForFunction(() => murray.state.terrain?.on && !murray.state.terrain.loading && viewer.terrainProvider === murray.state.terrain.provider, null, { timeout: 120000 });
  else if (value && !value.startsWith('map:')) {
    await p.waitForFunction(value => displayedLayer === value || document.querySelector('#layerStatus').textContent.startsWith('Layer could not load'), value, { timeout: 180000 });
  }
  const s = await check(value, p, annotations);
  checks.push({ name: 'select ' + (value || 'planner'), choice: s.choice, activeSurfaces: s.activeSurfaces, overlayCount: s.overlayCount });
  console.log('PASS selection ' + (value || 'planner'));
}
try {
  page = await open();
  const options = await page.locator('#globalLayer option').evaluateAll(options => options.map(o => ({value:o.value, disabled:o.disabled})));
  assert.equal(new Set(options.map(o => o.value)).size, options.length, 'No duplicate map choices');
  assert(!options.some(o => o.value === 'openmars_surface_temperature'), 'Removed OpenMARS reference must be absent');
  assert.equal(await page.locator('#layer option[value="openmars_surface_temperature"]').count(), 0);
  for (const id of ['murray_none','murray_ctx','murray_mola','murray_viking','murray_terrain']) assert.equal(await page.locator('#'+id).count(), 0, 'Old surface chooser must be removed');
  for (const id of ['names','quads','m2020']) {
    await page.locator('#murray_' + id).setChecked(true);
    await page.waitForFunction(id => murray.state[id]?.on && murray.state[id].ds && viewer.dataSources.contains(murray.state[id].ds), id, { timeout: 90000 });
  }
  await page.evaluate(() => { viewer.camera.cancelFlight(); showWholeMars(); });
  for (const option of options.filter(o => !o.disabled)) await choose(option.value);
  await page.screenshot({ path: path.join(out, 'global-selection-all-options.png') });

  // A real weather response held after fetch ignores abort on purpose; the request generation must reject it.
  await choose('map:ctx');
  await page.evaluate(() => {
    window.selectionOriginalApi = api;
    window.selectionGateReady = false;
    api = async function(path, body, signal) {
      if (path === '/api/layer/surface_pressure') {
        const response = await window.selectionOriginalApi(path, body);
        await new Promise(resolve => { window.selectionReleaseResponse = resolve; window.selectionGateReady = true; });
        return response;
      }
      return window.selectionOriginalApi(path, body, signal);
    };
  });
  await page.locator('#globalLayer').selectOption('surface_pressure');
  await page.waitForFunction(() => window.selectionGateReady, null, { timeout: 120000 });
  await choose('map:viking');
  await page.evaluate(() => { api = window.selectionOriginalApi; window.selectionReleaseResponse(); });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await check('map:viking');
  checks.push({ name: 'late weather response cannot replace newer imagery' });

  // Switch surfaces repeatedly in the same task; older terrain/weather operations may still be pending.
  await page.evaluate(() => {
    for (const value of ['map:terrain','air_temperature','map:mola','radiation_dose','map:ctx','']) {
      const select = document.querySelector('#globalLayer'); select.value = value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });
  await check('');
  checks.push({ name: 'rapid mixed selection keeps only final planner surface' });

  // Regional selection returns to planner imagery and synchronizes the global menu.
  await choose('map:ctx');
  await page.locator('#gmRail button[data-section="regionalMaps"]').click();
  await page.locator('#regionalLayer').selectOption('temperature');
  await page.waitForFunction(() => displayedLayer === 'temperature' || document.querySelector('#layerStatus').textContent.startsWith('Layer could not load'), null, { timeout: 120000 });
  const regional = await state();
  assert.equal(regional.visible, ''); assert.equal(regional.choice, ''); assert.equal(regional.canonical, 'temperature');
  assert.equal(regional.regional, 'temperature'); assert.deepEqual(regional.activeSurfaces, []);
  assert(regional.own.every(Boolean)); assert.equal(regional.displayedLayer, 'temperature');
  checks.push({ name: 'regional map returns global selection to planner' });
  await page.evaluate(() => { document.querySelector('#globalMaps').open = true; });
  await choose('');

  // A fresh page has no cached terrain provider. Hold its real metadata request across a newer choice.
  await page.close();
  const lateTerrainPage = page = await open();
  let releaseTerrain, terrainSeen = false;
  const terrainMetadataPath = await lateTerrainPage.evaluate(() =>
    new URL(murray.defs.find(def => def.id === 'terrain').url, location.href).pathname.replace(/\/$/, ''));
  await lateTerrainPage.route(url => url.pathname.replace(/\/$/, '') === terrainMetadataPath, async route => {
    terrainSeen = true;
    await new Promise(resolve => releaseTerrain = resolve);
    await route.continue().catch(() => {});
  });
  await lateTerrainPage.locator('#globalLayer').selectOption('map:terrain');
  await lateTerrainPage.waitForFunction(() => !!murray.state.terrain?.loading);
  const deadline = Date.now() + 30000;
  while (!terrainSeen && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 25));
  assert(terrainSeen, 'Terrain metadata must be requested');
  await choose('map:mola', lateTerrainPage, false);
  releaseTerrain();
  await lateTerrainPage.waitForFunction(() => !murray.state.terrain.loading, null, { timeout: 120000 });
  await check('map:mola', lateTerrainPage, false);
  assert(await lateTerrainPage.evaluate(() => !!murray.state.terrain.provider), 'Real delayed terrain provider finished loading');
  checks.push({ name: 'late terrain metadata cannot reactivate terrain after imagery selection' });
  await lateTerrainPage.close();
  assert.deepEqual(pageErrors, []);
} catch (error) {
  failure = String(error.stack || error);
  await page?.screenshot({ path: path.join(out, 'global-selection-failure.png') }).catch(() => {});
} finally {
  await fs.writeFile(path.join(out, 'global-selection-results.json'), JSON.stringify({ checks, pageErrors, sourceFailures, failure }, null, 2));
  await browser.close();
}
if (failure) throw new Error(failure);
