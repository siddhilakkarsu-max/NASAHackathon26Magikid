import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const out = process.env.MARSWALK_AUDIT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'marswalk-global-terrain-'));
await fs.mkdir(out, { recursive: true });
console.log('Audit artifacts: ' + out);
const checks = [], pageErrors = [], sourceResponses = [], samples = [];
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
let page, failure, renderErrors = [];
const record = (name, data = {}) => { checks.push({ name, ...data }); console.log('PASS ' + name); };
const frames = (n = 4) => page.evaluate(n => new Promise(resolve => {
  const frame = () => --n <= 0 ? resolve() : requestAnimationFrame(frame); requestAnimationFrame(frame);
}), n);

function center(region) {
  const r = region.rectangle;
  return { lon: (r.west + r.east) / 2, lat: (r.south + r.north) / 2 };
}
function provenance(headers) {
  return { status: headers['x-terrain-detail-status'] || null,
    sources: (headers['x-terrain-source-ids'] || '').split(',').filter(Boolean),
    sourceCount: Number(headers['x-terrain-source-count']), failedCount: Number(headers['x-terrain-failed-count']),
    gridSize: Number(headers['x-terrain-grid-size']) };
}
function heightAt(bytes, size, u, northV) {
  // Independent interpolation of the SW-to-NE triangulation used by a regular
  // Cesium heightmap. The backend buffer is Float32LE, first row at the north.
  const column = Math.min(size - 2, Math.floor(u));
  const row = Math.min(size - 2, Math.floor(northV));
  const dx = u - column, dy = 1 - (northV - row);
  const h = (x, y) => bytes.readFloatLE((y * size + x) * 4);
  const nw = h(column, row), ne = h(column + 1, row);
  const sw = h(column, row + 1), se = h(column + 1, row + 1);
  return dy < dx ? sw + dx * (se - sw) + dy * (ne - se)
    : sw + dx * (ne - nw) + dy * (nw - sw);
}
async function choose(value) {
  await page.evaluate(() => { document.querySelector('#globalMaps').open = true; });
  await page.locator('#globalLayer').selectOption(value);
  if (value === 'map:terrain') {
    await page.waitForFunction(() => murrayOn('terrain') && !murray.state.terrain.loading &&
      viewer.terrainProvider === murray.state.terrain.provider, null, { timeout: 120000 });
  } else {
    await page.waitForFunction(() => !murrayOn('terrain') && viewer.terrainProvider instanceof Cesium.EllipsoidTerrainProvider);
  }
  await frames();
}

try {
  page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
  page.setDefaultTimeout(60000);
  page.on('pageerror', error => pageErrors.push(String(error)));
  page.on('response', response => {
    if (/\/terrain\/detail\/\d+\/\d+\/\d+\.bin(?:\?|$)/.test(response.url())) {
      sourceResponses.push({ url: response.url(), httpStatus: response.status(), ...provenance(response.headers()) });
    }
  });
  await page.addInitScript(() => localStorage.setItem('mapManualSeen', '1'));
  await page.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.locator('#startExploring').click();
  await page.locator('#gmRail button[data-section="all"]').click();
  await page.waitForFunction(() => murray.defs.length && current && !viewer.camera._currentFlight &&
    document.querySelector('#globalLayer option[value="map:terrain"]'));
  await page.evaluate(scale => {
    viewer.resolutionScale = scale; viewer.clock.shouldAnimate = false;
    window.globalTerrainRenderErrors = [];
    viewer.scene.renderError.addEventListener((scene, error) => window.globalTerrainRenderErrors.push(String(error)));
    // The orbit view avoids pulling hundreds of remote survey windows while
    // numerical samples explicitly request only the two selected source tiles.
    viewer.camera.cancelFlight();
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(20, 15, 8000000, MARS),
      orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 } });
    document.querySelector('#globeLighting').checked = false;
    document.querySelector('#globeLighting').dispatchEvent(new Event('change'));
    viewer.scene.requestRender();
  }, Number(process.env.MARSWALK_RENDER_SCALE || 0.5));
  await page.waitForFunction(() => marsSky?.getState().starsState === 'ready');
  await page.evaluate(() => { window.globalAuditSkyBox = viewer.scene.skyBox; });

  const response = await page.request.get(base + '/api/terrain/detail', { timeout: 60000 });
  assert(response.ok(), `Detailed terrain catalogue returned HTTP ${response.status()}`);
  const metadata = await response.json();
  assert.equal(metadata.available, true);
  assert(Array.isArray(metadata.regions) && metadata.regions.length >= 2);
  assert.equal(metadata.grid_size, 257); assert.equal(metadata.minimum_level, 8);
  assert.equal(metadata.tile_url, '/terrain/detail/{z}/{y}/{x}.bin');
  // Prefer the requested western/eastern survey examples, with a verified west
  // HRSC source as catalogue fallback. These are separate from Jezero coverage.
  const west = metadata.regions.find(r => r.id === 'hrsc:HMC_11E10_da5') ||
    metadata.regions.find(r => r.id === 'hrsc:HMC_11W10_da5');
  const east = metadata.regions.find(r => r.id === 'hrsc:HMC_13E10_da5');
  assert(west && east, 'The authoritative HRSC catalogue must contain the two audit surveys');
  const sites = [west, east];
  assert(Math.abs(center(west).lon - center(east).lon) > 60);
  assert(sites.every(r => r.kind === 'hrsc' && r.maximum_level >= 10 && r.resolution_m === 50));
  await choose('map:terrain');
  const provider = await page.evaluate(() => ({ regions: viewer.terrainProvider.detailRegions?.length,
    metadataCount: viewer.terrainProvider.regionalMetadata?.regions?.length,
    hasPositionLookup: typeof viewer.terrainProvider.getDetailForPosition === 'function' }));
  assert.equal(provider.regions, metadata.regions.length);
  assert.equal(provider.metadataCount, metadata.regions.length); assert(provider.hasPositionLookup);
  record('actual catalogue loads into the active terrain provider', { ...provider, sourceCounts: metadata.source_counts });

  for (const site of sites) {
    const position = center(site), level = 10, size = metadata.grid_size;
    const tile = await page.evaluate(({ position, level }) => {
      const p = Cesium.Cartographic.fromDegrees(position.lon, position.lat), provider = viewer.terrainProvider;
      const xy = provider.tilingScheme.positionToTileXY(p, level);
      const r = provider.tilingScheme.tileXYToRectangle(xy.x, xy.y, level);
      const detail = provider.getDetailForPosition(p);
      return { x: xy.x, y: xy.y, level, available: provider.getTileDataAvailable(xy.x, xy.y, level),
        detail: detail ? { id: detail.id, kind: detail.kind, resolution_m: detail.resolution_m } : null,
        rectangle: Object.fromEntries(['west', 'south', 'east', 'north'].map(k => [k, Cesium.Math.toDegrees(r[k])])) };
    }, { position, level });
    assert.equal(tile.available, true); assert(tile.detail);
    const tileUrl = metadata.tile_url.replace('{z}', level).replace('{y}', tile.y).replace('{x}', tile.x);
    const raw = await page.request.get(base + tileUrl, { timeout: 90000 });
    assert(raw.ok(), `Terrain tile ${tileUrl} returned HTTP ${raw.status()}`);
    const bytes = await raw.body(), source = provenance(raw.headers());
    assert.equal(bytes.length, size * size * 4); assert.equal(source.gridSize, size);
    assert(['detail', 'partial', 'global-fallback'].includes(source.status));
    let low = Infinity, high = -Infinity;
    for (let i = 0; i < size * size; i++) {
      const height = bytes.readFloatLE(i * 4);
      assert(Number.isFinite(height) && height > -20000 && height < 40000);
      low = Math.min(low, height); high = Math.max(high, height);
    }
    const r = tile.rectangle;
    const points = [[117.25, 131.625], [128.5, 128.25], [142.75, 116.125]].map(([u, v]) => ({
      lon: r.west + u / (size - 1) * (r.east - r.west),
      lat: r.north - v / (size - 1) * (r.north - r.south),
      expected: heightAt(bytes, size, u, v),
    }));
    const actual = await page.evaluate(async ({ level, points }) => {
      const positions = points.map(p => Cesium.Cartographic.fromDegrees(p.lon, p.lat));
      return (await Cesium.sampleTerrain(viewer.terrainProvider, level, positions)).map(p => p.height);
    }, { level, points });
    actual.forEach((height, i) => assert(Number.isFinite(height) && Math.abs(height - points[i].expected) < 0.02,
      `Cesium sample ${site.id}/${i} must match the real raw tile within 2 cm; expected ${points[i].expected}, actual ${height}`));
    const item = { id: site.id, position, tile, source, minimum: low, maximum: high,
      points: points.map((point, i) => ({ ...point, actual: actual[i] })),
      finerSourceContributed: source.status !== 'global-fallback' && source.sources.some(id => id.startsWith('hrsc:') || id.startsWith('ctx:')),
      coverageNote: 'A contributing source header applies to the tile. Footprint membership does not prove every pixel has finer data.' };
    samples.push(item);
    record('level-10 Cesium heights match the raw backend tile at ' + site.id, item);
  }

  await choose('');
  assert(await page.evaluate(() => viewer.scene.skyBox === window.globalAuditSkyBox && viewer.scene.skyBox.show));
  record('planner map removes terrain while preserving the star background');
  await choose('map:terrain');
  assert(await page.evaluate(() => viewer.terrainProvider.detailRegions?.length > 1 &&
    viewer.scene.skyBox === window.globalAuditSkyBox && viewer.scene.skyBox.show));
  record('terrain reactivation restores the catalogue and preserves the star background');

  const illustrated = samples.find(sample => sample.finerSourceContributed);
  if (illustrated && process.env.MARSWALK_CAPTURE_DETAIL !== '0') {
    const point = illustrated.points[1];
    await page.evaluate(point => {
      const target = Cesium.Cartesian3.fromDegrees(point.lon, point.lat, point.actual * viewer.scene.verticalExaggeration, MARS);
      viewer.camera.lookAt(target, new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-35), 9000));
      viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY); viewer.scene.requestRender();
    }, point);
    let tilesReady = true;
    try { await page.waitForFunction(() => viewer.scene.globe.tilesLoaded, null, { timeout: 15000 }); }
    catch (error) { if (error.name !== 'TimeoutError') throw error; tilesReady = false; }
    await frames();
    const visual = await page.evaluate(() => ({ pitch: viewer.camera.pitch,
      cameraHeight: viewer.camera.positionCartographic.height, underground: viewer.scene.cameraUnderground,
      renderedLevels: [...new Set(viewer.scene.globe._surface._tilesToRender.map(tile => tile.level))].sort((a, b) => a - b) }));
    assert.equal(visual.underground, false);
    await page.screenshot({ path: path.join(out, 'survey-angled-view.png') });
    record('angled survey view remains above the measured terrain', { ...visual, tilesReady, source: illustrated.source,
      screenshotNote: tilesReady ? 'Visible tiles finished loading.' : 'Bounded preview: imagery or geometry may still be streaming; not a full-resolution guarantee.' });
  }
  renderErrors = await page.evaluate(() => window.globalTerrainRenderErrors);
  assert.deepEqual(pageErrors, []); assert.deepEqual(renderErrors, []);
  // A fallback sample can still pass transport/interpolation and switching
  // checks, but cannot count as successful fine-source delivery.
  assert.equal(samples.filter(sample => sample.finerSourceContributed).length, 2,
    'Both remote survey tiles must report a real finer source; global fallback is not a high-resolution success');
  record('two separated surveys deliver real finer sources without browser or render errors');
} catch (error) {
  failure = String(error.stack || error);
  await page?.screenshot({ path: path.join(out, 'global-terrain-failure.png') }).catch(() => {});
  console.error(failure);
} finally {
  if (page) renderErrors = await page.evaluate(() => window.globalTerrainRenderErrors || []).catch(() => renderErrors);
  await fs.writeFile(path.join(out, 'global-terrain-results.json'), JSON.stringify({ passed: !failure,
    checks, samples, pageErrors, renderErrors, sourceResponses, failure }, null, 2));
  await browser.close();
}
if (failure) process.exitCode = 1;
