import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const out = process.env.MARSWALK_AUDIT_DIR || path.resolve('moons-audit');
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
page.setDefaultTimeout(60000);
const checks = [], errors = [];
page.on('pageerror', error => errors.push(String(error)));
const pass = name => { checks.push(name); console.log('PASS ' + name); };
const frame = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const state = () => page.evaluate(() => marsMoons.state());
let failure;
try {
  await page.addInitScript(() => localStorage.setItem('mapManualSeen', '1'));
  await page.goto(base + '/?view=moons', { waitUntil: 'domcontentloaded' });
  await page.locator('#startExploring').click();
  await page.waitForFunction(() => typeof marsMoons !== 'undefined' && marsMoons.state().moons.every(m => m.valid));
  await page.evaluate(() => { viewer.resolutionScale = 0.65; window.moonRenderErrors = [];
    viewer.scene.renderError.addEventListener((_, e) => moonRenderErrors.push(String(e)));
    marsMoons.setSpeed(0); marsMoons.setTime('2026-11-15T12:00:00Z'); });
  await page.waitForFunction(() => marsMoons.state().moons.every(m => m.valid));
  const s = await state();
  assert.equal(s.speed, 0);
  for (const m of s.moons) {
    const radius = Math.hypot(m.position.x, m.position.y, m.position.z);
    assert(m.id === 'phobos' ? radius > 9e6 && radius < 9.7e6 : radius > 23e6 && radius < 24e6);
    assert.equal(m.scale, 1000);
  }
  pass('Both moons load at real Mars-centered distances with physical model scale');
  const truth = JSON.parse(await fs.readFile(new URL('../../tests/fixtures/mars_moons_interpolation.json', import.meta.url), 'utf8'));
  let worst = 0;
  for (const row of truth.rows) {
    await page.evaluate(utc => marsMoons.setTime(utc), row.utc); await frame();
    for (const m of (await state()).moons) {
      const expected = row.positions[m.id];
      const error = Math.hypot(m.position.x-expected[0], m.position.y-expected[1], m.position.z-expected[2]);
      worst = Math.max(worst, error); assert(error < 1, `Browser interpolation departure ${error} m`);
    }
  }
  await page.evaluate(() => marsMoons.setTime('2026-11-15T12:00:00Z'));
  pass(`Browser interpolation agrees with direct SPICE at intermediate epochs (worst ${worst.toFixed(3)} m)`);
  await page.locator('#gmRail button[data-section="conditionsPanel"]').click();
  await page.locator('#moonControls > summary').click();
  await page.locator('#moonSpeed').selectOption('0');
  const spheres = {};
  for (const name of ['Phobos', 'Deimos']) {
    await page.locator('#moon' + name).click();
    await page.waitForFunction(name => viewer.trackedEntity?.name === name, name);
    await page.waitForFunction(() => {
      const sphere = new Cesium.BoundingSphere();
      return viewer.dataSourceDisplay.getBoundingSphere(viewer.trackedEntity, false, sphere) === Cesium.BoundingSphereState.DONE && sphere.radius > 1000;
    });
    spheres[name] = await page.evaluate(() => {
      const sphere = new Cesium.BoundingSphere(); viewer.dataSourceDisplay.getBoundingSphere(viewer.trackedEntity, false, sphere);
      return { radius: sphere.radius, exaggerated: viewer.trackedEntity.model.enableVerticalExaggeration.getValue() };
    });
    assert(spheres[name].radius < 22000 && spheres[name].radius > 4000);
    assert.equal(spheres[name].exaggerated, false);
    await page.locator('#drawerClose').click();
    await frame();
    await page.screenshot({ path: path.join(out, name.toLowerCase() + '-nasa.png') });
    await page.locator('#gmRail button[data-section="conditionsPanel"]').click();
  }
  pass('Both NASA textured models render and can be followed without terrain exaggeration');
  await page.locator('#moonSystemView').click();
  await page.waitForFunction(() => !viewer.trackedEntity && !viewer.camera._currentFlight);
  await page.locator('#drawerClose').click(); await frame();
  await page.screenshot({ path: path.join(out, 'mars-and-moons.png') });
  pass('Mars and moons view restores a wide camera with no enlarged orbit or moon sizes');
  await page.evaluate(() => {
    const p = marsMoons.state().moons[0].position;
    const opposite = Cesium.Cartesian3.multiplyByScalar(Cesium.Cartesian3.normalize(p, new Cesium.Cartesian3()), -MARS.maximumRadius * 3, new Cesium.Cartesian3());
    viewer.camera.setView({ destination: opposite, orientation: { heading:0, pitch:-Math.PI/2, roll:0 } });
  }); await frame();
  assert.equal((await state()).moons[0].markerVisible, false);
  assert.equal(await page.evaluate(() => viewer.dataSources.getByName('NASA/JPL Mars moons')[0].entities.getById('mars-moon-phobos').model.show.getValue()), false);
  pass('Mars occludes a far-side moon model and its locator label');
  await page.evaluate(() => { marsMoons.focus('phobos'); document.querySelector('#region').dispatchEvent(new Event('change')); });
  assert.equal(await page.evaluate(() => !!viewer.trackedEntity), false);
  pass('Choosing a region releases moon tracking');
  // Labels stay in the datasource during movement: do not depend on moveEnd filtering.
  await page.evaluate(() => {
    window.occlusionAudit = new Cesium.CustomDataSource('occlusion audit'); viewer.dataSources.add(occlusionAudit);
    window.nearAudit = murrayLabel(occlusionAudit, 0, 0, 'VISIBLE NEAR SIDE', 1e9);
    window.farAudit = murrayLabel(occlusionAudit, 180, 0, 'HIDDEN FAR SIDE', 1e9);
    viewer.camera.cancelFlight();
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(0, 0, 6e6, MARS), orientation: {heading:0,pitch:-Math.PI/2,roll:0} });
  }); await frame();
  assert.deepEqual(await page.evaluate(() => [nearAudit.label.show.getValue(), farAudit.label.show.getValue()]), [true, false]);
  await page.screenshot({ path: path.join(out, 'labels-near-side-only.png') });
  await page.evaluate(() => viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(180, 0, 6e6, MARS), orientation: {heading:0,pitch:-Math.PI/2,roll:0} }));
  await frame();
  assert.deepEqual(await page.evaluate(() => [nearAudit.label.show.getValue(), farAudit.label.show.getValue()]), [false, true]);
  await page.evaluate(() => viewer.dataSources.remove(occlusionAudit, true));
  pass('Place labels hide behind Mars and reverse visibility as the camera rotates');
  await page.evaluate(() => marsMoons.setSpeed(60));
  const before = await state();
  await new Promise(resolve => setTimeout(resolve, 350));
  await frame();
  const after = await state();
  assert(Date.parse(after.utc) - Date.parse(before.utc) > 1000);
  await page.evaluate(() => { marsMoons.setSpeed(0); marsMoons.setTime('2026-11-15T12:00:00Z'); });
  const fixed = await state(); await frame();
  assert.equal((await state()).utc, fixed.utc);
  pass('Playback advances ephemeris time and pause freezes the moon positions');
  // Real new-day data is delayed to exercise cancelled/stale replies.
  let release, seen = false;
  await page.route('**/api/moons/ephemeris?date=2026-11-17', async route => {
    const response = await route.fetch(); seen = true;
    await new Promise(resolve => { release = resolve; });
    await route.fulfill({ response }).catch(() => {});
  });
  await page.evaluate(() => marsMoons.setTime('2026-11-17T12:00:00Z'));
  for (let n=0; !seen && n<100; n++) await new Promise(resolve => setTimeout(resolve, 50));
  assert(seen);
  await page.evaluate(() => marsMoons.setTime('2026-11-15T12:00:00Z'));
  release(); await frame();
  assert.deepEqual((await state()).moons, fixed.moons);
  pass('A late ephemeris response cannot replace a newer cached date');
  await page.route('**/api/moons/ephemeris?date=2026-11-20', route => route.fulfill({ status:503, json:{detail:'Deliberate audit outage'} }));
  await page.evaluate(() => marsMoons.setTime('2026-11-20T12:00:00Z'));
  await page.waitForFunction(() => marsMoons.state().error && !marsMoons.state().pendingDay);
  assert((await state()).moons.every(m => !m.valid && !m.markerVisible));
  await page.evaluate(() => { marsMoons.setEnabled(false); marsMoons.setTime('2026-11-15T12:00:00Z'); });
  assert((await state()).moons.every(m => !m.valid));
  await page.evaluate(() => marsMoons.setEnabled(true)); await frame();
  assert((await state()).moons.every(m => m.valid));
  pass('Unavailable data hides moons without fabricated positions; toggle restores cached data');
  assert.deepEqual(errors, []); assert.deepEqual(await page.evaluate(() => moonRenderErrors), []);
  assert(await page.evaluate(() => viewer.useDefaultRenderLoop), 'Cesium render loop must still be running');
  pass('No uncaught JavaScript or renderer errors');
} catch (error) {
  failure = String(error.stack || error);
  await page.screenshot({ path: path.join(out, 'moons-failure.png') }).catch(() => {});
} finally {
  await fs.writeFile(path.join(out, 'moons-browser-results.json'), JSON.stringify({ checks, errors, failure }, null, 2));
  await browser.close();
}
if (failure) throw new Error(failure);
