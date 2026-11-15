import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const out = process.env.MARSWALK_AUDIT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'marswalk-terrain-'));
await fs.mkdir(out, { recursive: true });
console.log('Audit artifacts: ' + out);
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const checks = [], pageErrors = [], terrainRequests = [], photoRequests = [];
function record(check) { checks.push(check); console.log('PASS ' + check.name); }
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
let page, failure;
const pauseFrames = async (n = 12) => page.evaluate(n => new Promise(resolve => {
  const tick = () => --n <= 0 ? resolve() : requestAnimationFrame(tick);
  requestAnimationFrame(tick);
}), n);

async function open() {
  const p = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  p.setDefaultTimeout(60000);
  p.on('pageerror', error => pageErrors.push(String(error)));
  p.on('request', request => {
    const match = new URL(request.url()).pathname.match(/^\/murray\/elevation\/tile\/(\d+)\/(\d+)\/(\d+)$/);
    if (match) terrainRequests.push({ level: +match[1], y: +match[2], x: +match[3] });
    const photo = new URL(request.url()).pathname.match(/\/OnMars\/CTX1\/MapServer\/tile\/(\d+)\/(\d+)\/(\d+)$/);
    if (photo) photoRequests.push({ level: +photo[1], y: +photo[2], x: +photo[3] });
  });
  await p.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.locator('#startExploring').click();
  await p.waitForFunction(() => murray.defs.length && current && !viewer.camera._currentFlight &&
    document.querySelector('#globalLayer option[value="map:ctx"]'));
  await p.evaluate(() => {
    window.terrainRenderErrors = [];
    viewer.scene.renderError.addEventListener((scene, error) => window.terrainRenderErrors.push(String(error)));
    // Keep the test image evenly lit; this does not affect the terrain geometry.
    document.querySelector('#globeLighting').checked = false;
    document.querySelector('#globeLighting').dispatchEvent(new Event('change'));
  });
  return p;
}
async function choose(value) {
  await page.evaluate(() => { document.querySelector('#globalMaps').open = true; });
  await page.locator('#globalLayer').selectOption(value);
  if (value === 'map:ctx' || value === 'map:terrain' || await page.evaluate(() => sharpBoxPinned)) {
    await page.waitForFunction(() => murray.state.terrain?.on && !murray.state.terrain.loading &&
      viewer.terrainProvider === murray.state.terrain.provider, null, { timeout: 120000 });
  }
  await pauseFrames();
}
async function view(lon = 77.45, lat = 18.45, height = 60000) {
  await page.evaluate(({lon, lat, height}) => {
    viewer.camera.cancelFlight();
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(lon, lat, height, MARS),
      orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 } });
    viewer.scene.requestRender();
    fadePhoto();
  }, {lon, lat, height});
  await pauseFrames();
}
async function state() {
  return page.evaluate(() => ({ box: sharpBox && { ...sharpBox }, pinned: sharpBoxPinned,
    image: ctxLayer && { show: ctxLayer.show, alpha: ctxLayer.alpha,
      index: viewer.imageryLayers.indexOf(ctxLayer) },
    outline: boxEntity && boxEntity.show, terrain: murrayOn('terrain'),
    flat: viewer.terrainProvider instanceof Cesium.EllipsoidTerrainProvider,
    depthTest: viewer.scene.globe.depthTestAgainstTerrain,
    exaggeration: viewer.scene.verticalExaggeration,
    pitch: viewer.camera.pitch, heading: viewer.camera.heading,
    height: viewer.camera.positionCartographic.height,
    mode, corner: boxCorner, activeButton: document.querySelector('#boxBtn').classList.contains('active'),
    renderErrors: window.terrainRenderErrors }));
}
async function canvasPoint(xFraction, yFraction) {
  const box = await page.locator('#map canvas').first().boundingBox();
  assert(box && box.width > 100 && box.height > 100, 'The globe canvas is visible');
  return { x: box.x + box.width * xFraction, y: box.y + box.height * yFraction };
}
async function drawBox(first = [0.4, 0.4], second = [0.6, 0.6]) {
  await page.evaluate(() => { document.querySelector('#regionalMaps').open = true; });
  await page.locator('#boxBtn').click();
  const a = await canvasPoint(...first), b = await canvasPoint(...second);
  await page.mouse.click(a.x, a.y);
  assert.equal(await page.evaluate(() => mode), 'box2', 'First map click starts a box');
  await page.mouse.click(b.x, b.y);
  await page.waitForFunction(() => sharpBoxPinned && !!ctxLayer && murrayOn('terrain'));
  await page.waitForFunction(() => !murray.state.terrain.loading && viewer.terrainProvider === murray.state.terrain.provider,
    null, { timeout: 120000 });
  return state();
}
function assertPinned(s, expectedBox) {
  assert.equal(s.pinned, true); assert.equal(s.image?.show, true); assert.equal(s.image?.alpha, 1);
  assert.equal(s.outline, true); assert.equal(s.terrain, true); assert.equal(s.flat, false);
  assert.equal(s.depthTest, true); assert.equal(s.exaggeration, 1);
  if (expectedBox) assert.deepEqual(s.box, expectedBox);
  assert.deepEqual(s.renderErrors, []);
}

try {
  page = await open();
  await view(77.45, 18.45, 9000000);
  await choose('map:ctx');
  let s = await state();
  assert.equal(s.terrain, true); assert.equal(s.flat, false); assert.equal(s.exaggeration, 1);
  assert(await page.evaluate(() => murrayOn('ctx') && !!murray.state.ctx.layer));
  record({ name: 'Detailed photos automatically use real terrain without exaggeration' });

  await view();
  await page.waitForFunction(() => {
    const height = viewer.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(77.45, 18.45));
    return Number.isFinite(height) && Math.abs(height) > 1;
  }, null, { timeout: 120000 });
  const picked = await page.evaluate(() => {
    const canvas = viewer.scene.canvas, pixel = new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2);
    const ground = viewer.scene.globe.pick(viewer.camera.getPickRay(pixel), viewer.scene);
    const c = Cesium.Cartographic.fromCartesian(ground, MARS);
    return { actual: pickLatLon(pixel), expected: { lat: Cesium.Math.toDegrees(c.latitude), lon: Cesium.Math.toDegrees(c.longitude) },
      height: c.height };
  });
  assert(Math.abs(picked.actual.lat - picked.expected.lat) < 1e-7);
  assert(Math.abs(picked.actual.lon - picked.expected.lon) < 1e-7);
  assert(Number.isFinite(picked.height) && Math.abs(picked.height) > 1);
  record({ name: 'Picking follows loaded terrain rather than the zero-height ellipsoid', picked });

  const beforeDrag = await state(), center = await canvasPoint(0.5, 0.5);
  await page.mouse.move(center.x, center.y);
  await page.mouse.down({ button: 'right' });
  // Upward drag moves away from nadir; downward drag from exact nadir is correctly clamped.
  // Pace events with rendered frames so a busy software renderer observes the full gesture.
  for (let step = 1; step <= 12; step++) {
    await page.mouse.move(center.x + 60 * step / 12, center.y - 120 * step / 12);
    await pauseFrames(1);
  }
  await page.mouse.up({ button: 'right' });
  await pauseFrames(35);
  s = await state();
  assert(Math.abs(s.pitch - beforeDrag.pitch) > 0.02, 'A real right-button drag tilts the view');
  assert.equal(await page.evaluate(() => viewer.scene.cameraUnderground), false);
  await page.screenshot({ path: path.join(out, 'terrain-right-drag.png') });
  record({ name: 'Right drag tilts the real 3D surface', beforePitch: beforeDrag.pitch, afterPitch: s.pitch });

  await view();
  const beforeWheel = (await state()).height;
  await page.mouse.move(center.x, center.y);
  await page.mouse.wheel(0, -400);
  await page.waitForFunction(height => viewer.camera.positionCartographic.height < height * 0.99, beforeWheel);
  await pauseFrames(35);
  record({ name: 'Wheel still zooms after right-drag is assigned to tilt', beforeHeight: beforeWheel,
    afterHeight: (await state()).height });

  await view();
  s = await drawBox();
  const pinned = s.box;
  assertPinned(s);
  assert.equal(s.mode, null); assert.equal(s.activeButton, false);
  for (const height of [60000, 700000, 9000000]) {
    await view(77.45, 18.45, height);
    assertPinned(await state(), pinned);
  }
  record({ name: 'Two real map clicks pin opaque imagery and terrain at close, middle and whole-planet distances', box: pinned });
  await page.screenshot({ path: path.join(out, 'terrain-pinned-global.png') });

  for (const choice of ['map:mola', 'map:viking', '']) {
    await choose(choice);
    assertPinned(await state(), pinned);
    if (choice) assert(await page.evaluate(choice => viewer.imageryLayers.indexOf(ctxLayer) >
      viewer.imageryLayers.indexOf(murray.state[choice.slice(4)].layer), choice), 'Pinned photos remain above the global background');
  }
  await page.evaluate(() => setSharpBox(current.rect));
  assertPinned(await state(), pinned);
  record({ name: 'Pinned box survives global selections and automatic regional imagery updates' });

  await page.evaluate(() => { document.querySelector('#regionalMaps').open = true; });
  await page.locator('#clearBox').click();
  s = await state();
  assert.equal(s.pinned, false); assert.equal(s.box, null); assert.equal(s.image, null);
  assert.equal(s.flat, true); assert.equal(s.terrain, false);
  record({ name: 'Clear removes the last terrain demand and returns the planner to its normal background' });

  await choose('map:ctx');
  await view();
  await drawBox();
  await page.locator('#clearBox').click();
  s = await state();
  assert.equal(s.box, null); assert.equal(s.pinned, false); assert.equal(s.flat, false); assert.equal(s.terrain, true);
  record({ name: 'Clearing a box preserves terrain still required by Detailed photos' });

  await page.locator('#boxBtn').click();
  const first = await canvasPoint(0.45, 0.45);
  await page.mouse.click(first.x, first.y);
  assert.equal(await page.evaluate(() => mode), 'box2');
  await page.locator('#clearBox').click();
  s = await state();
  assert.equal(s.mode, null); assert.equal(s.corner, null); assert.equal(s.activeButton, false);
  const second = await canvasPoint(0.55, 0.55);
  await page.mouse.click(second.x, second.y);
  assert.equal((await state()).box, null);
  record({ name: 'Clear cancels an incomplete drawing; the next click cannot recreate it' });

  await view(180, 5, 200000);
  s = await drawBox([0.4, 0.4], [0.6, 0.6]);
  assertPinned(s);
  assert(s.box.west > s.box.east, 'A box drawn over the dateline uses a wrapped rectangle');
  const width = (s.box.east - s.box.west + 360) % 360;
  assert(width > 0 && width < 10, 'The drawn dateline box uses the short arc, not almost the whole planet');
  record({ name: 'Drawing across the antimeridian keeps the small intended area', box: s.box, width });

  await page.locator('#clearBox').click();
  await view();
  await page.locator('#boxBtn').click();
  const same = await canvasPoint(0.5, 0.5);
  await page.mouse.click(same.x, same.y);
  // Two separated clicks, not an operating-system double-click gesture.
  await pauseFrames(35);
  await page.mouse.click(same.x, same.y);
  s = await state();
  assert.equal(s.box, null, 'A zero-area box is rejected without creating a malformed imagery provider');
  record({ name: 'Coincident corners do not create invalid image rectangles' });

  await page.locator('#clearBox').click();
  const lowHeight = await page.evaluate(() => viewer.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(77.45, 18.45)) + 100);
  assert(Number.isFinite(lowHeight) && lowHeight < 0, 'The regression site lies below the reference ellipsoid');
  await view(77.45, 18.45, lowHeight);
  const belowReference = await state();
  assert(belowReference.height < 0 && belowReference.terrain, 'Start above real terrain but below the flat ellipsoid');
  await choose('');
  s = await state();
  assert.equal(s.flat, true); assert(s.height >= 24.9, 'Flat-map transition raises the camera above the new surface');
  assert.equal(await page.evaluate(() => viewer.scene.cameraUnderground), false);
  record({ name: 'Switching from a negative-elevation crater floor to a flat map keeps the camera above ground',
    beforeHeight: belowReference.height, afterHeight: s.height });

  assert(terrainRequests.length, 'Real terrain tiles were requested');
  assert(terrainRequests.every(tile => tile.level <= 7), 'No unsupported terrain levels are requested');
  assert(terrainRequests.some(tile => tile.level >= 6), 'Zooming into the surface requests finer real terrain tiles');
  assert(photoRequests.length, 'Real CTX image tiles were requested');
  assert(photoRequests.every(tile => tile.level <= 12), 'No unavailable CTX levels above the real native service are requested');
  assert.deepEqual((await state()).renderErrors, []);
  assert.deepEqual(pageErrors, []);
  record({ name: 'Terrain refines to real source levels without exceeding native coverage',
    requestedLevels: [...new Set(terrainRequests.map(tile => tile.level))].sort((a, b) => a - b),
    photoLevels: [...new Set(photoRequests.map(tile => tile.level))].sort((a, b) => a - b) });
} catch (error) {
  failure = String(error.stack || error);
  await page?.screenshot({ path: path.join(out, 'terrain-navigation-failure.png') }).catch(() => {});
} finally {
  await fs.writeFile(path.join(out, 'terrain-navigation-results.json'), JSON.stringify({ checks, pageErrors, terrainRequests, photoRequests, failure }, null, 2));
  await browser.close();
}
if (failure) throw new Error(failure);
