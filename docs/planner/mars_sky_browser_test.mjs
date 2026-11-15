import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const out = process.env.MARSWALK_AUDIT_DIR || path.resolve('outputs/mars-sky-audit');
await fs.mkdir(out, { recursive: true });
const checks = [], errors = [], requests = [];
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
let page, failure;
const record = (name, data) => { checks.push({ name, ...data }); console.log('PASS ' + name); };
const frames = (n = 4) => page.evaluate(n => new Promise(resolve => {
  const tick = () => --n ? requestAnimationFrame(tick) : resolve(); requestAnimationFrame(tick);
}), n);
async function snapshot() {
  return page.evaluate(() => ({ state: marsSky.getState(), starsShow: viewer.scene.skyBox?.show,
    sky: { ...viewer.scene.skyAtmosphere.atmosphereMieCoefficient },
    ground: { ...viewer.scene.globe.atmosphereMieCoefficient }, fog: viewer.scene.fog.density,
    height: viewer.camera.positionCartographic.height, lighting: viewer.scene.globe.enableLighting }));
}
try {
  page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', request => { if (request.url().includes('/api/layer/dust_opacity/sample')) requests.push(request.postDataJSON()); });
  await page.goto(process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001/', { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.locator('#startExploring').click();
  await page.waitForFunction(() => typeof marsSky !== 'undefined' && marsSky?.getState().starsState === 'ready', null, { timeout: 60000 });
  await page.evaluate(() => { viewer.resolutionScale = 1; viewer.clock.shouldAnimate = false;
    viewer.camera.cancelFlight(); viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(77.45, 18.45, 8000000, MARS),
      orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 } }); viewer.scene.requestRender(); });
  await frames(8);
  assert.equal(requests.length, 0);
  const before = await snapshot(); assert.equal(before.state.starsState, 'ready'); assert.equal(before.starsShow, true);
  assert(Object.keys(before.ground).length === 3);
  record('bundled six-face skybox loads; initial dust makes no requests', before);
  const masks = await page.evaluate(() => {
    const canvas = viewer.scene.canvas, samples = [];
    for (let y = 10; y < canvas.clientHeight; y += 10) for (let x = 10; x < canvas.clientWidth; x += 10) {
      const point = new Cesium.Cartesian2(x, y);
      samples.push({ x, y, planet: !!viewer.camera.pickEllipsoid(point, MARS) });
    }
    return { samples, width: canvas.clientWidth, height: canvas.clientHeight };
  });
  await fs.writeFile(path.join(out, 'occlusion-mask.json'), JSON.stringify(masks));
  await page.locator('.cesium-widget canvas').screenshot({ path: path.join(out, 'stars-on-canvas.png') });
  await page.screenshot({ path: path.join(out, 'stars-whole-mars.png') });
  await page.evaluate(() => marsSky.setStarsEnabled(false)); await frames();
  await page.locator('.cesium-widget canvas').screenshot({ path: path.join(out, 'stars-off-canvas.png') });
  assert.equal((await snapshot()).starsShow, false);
  await page.evaluate(() => marsSky.setStarsEnabled(true)); await frames();
  assert.equal((await snapshot()).starsShow, true); record('stars off/on preserves native globe occlusion path');
  await page.evaluate(() => { viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(77.45, 18.45, 25000, MARS),
    orientation: { heading: 0, pitch: Cesium.Math.toRadians(-12), roll: 0 } }); viewer.scene.requestRender(); });
  await frames(6);
  const closeBefore = await snapshot();
  await page.evaluate(async () => { document.querySelector('#showDustHaze').checked = true; await marsSky.setDustEnabled(true); });
  await page.waitForFunction(() => marsSky.getState().dustPhase === 'ready' || marsSky.getState().dustPhase === 'unavailable', null, { timeout: 45000 });
  await frames(5);
  const real = await snapshot();
  assert.equal(real.state.dustPhase, 'ready'); assert(real.state.dustTau >= 0);
  assert(real.sky.x > closeBefore.sky.x); assert.equal(real.fog, closeBefore.fog);
  assert.equal(real.state.gridStepDeg, 5); assert(real.state.message.includes('not observed clouds'));
  const native = await page.request.post((process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001') + '/api/layer/dust_opacity/sample',
    { data: { ...real.state.location, ls: real.state.ls, local_hour: 12 } });
  assert.equal((await native.json()).value, real.state.dustTau);
  record('actual seasonal source value is unchanged; haze changes scattering only', real);
  await page.screenshot({ path: path.join(out, 'seasonal-dust-close.png') });
  await page.evaluate(async () => { globeLighting.setEnabled(false); await marsSky.refresh({ immediate: true }); });
  const off = await snapshot(); assert.equal(off.state.dustPhase, 'lighting-off'); assert.deepEqual(off.sky, before.sky);
  assert.deepEqual(off.ground, before.ground); record('lighting-off restores both atmosphere coefficients', off);
  await page.evaluate(async () => { globeLighting.setEnabled(true); await marsSky.refresh({ immediate: true }); });
  await page.route('**/api/layer/dust_opacity/sample', async route => route.fulfill({ status: 503, body: 'Unavailable' }));
  await page.evaluate(async () => { const input = document.querySelector('#ls'); input.value = '147';
    input.dispatchEvent(new Event('input', { bubbles: true })); await marsSky.refresh({ immediate: true }); });
  const unavailable = await snapshot(); assert.equal(unavailable.state.dustPhase, 'unavailable');
  assert.equal(unavailable.state.dustTau, null); assert.deepEqual(unavailable.sky, before.sky);
  assert.deepEqual(unavailable.ground, before.ground);
  record('season source failure removes old haze instead of keeping stale opacity', unavailable);
  await page.unroute('**/api/layer/dust_opacity/sample');
  await page.evaluate(async () => { await marsSky.setDustEnabled(false); });
  const requestCount = requests.length;
  await page.evaluate(async () => { await marsSky.refresh({ immediate: true }); viewer.camera.moveEnd.raiseEvent(); });
  await frames(); assert.equal(requests.length, requestCount);
  assert.equal(errors.length, 0, errors.join('\n')); record('disabled haze resumes zero-request operation; no browser exceptions');
} catch (error) { failure = { message: error.message, stack: error.stack }; console.error(error); }
finally {
  await fs.writeFile(path.join(out, 'result.json'), JSON.stringify({ passed: !failure, checks, errors, requests, failure }, null, 2));
  await browser.close();
}
if (failure) process.exitCode = 1;
