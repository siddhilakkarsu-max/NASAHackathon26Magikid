import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const out = process.env.MARSWALK_AUDIT_DIR || path.resolve('overview-audit');
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const checks = [], errors = [];
let page, failure;
const pass = name => { checks.push(name); console.log('PASS ' + name); };
const frame = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
async function open({ reducedMotion = 'no-preference', suffix = '', delayedMetadata = false } = {}) {
  const p = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion });
  p.setDefaultTimeout(60000); p.on('pageerror', e => errors.push(String(e)));
  await p.addInitScript(() => localStorage.setItem('mapManualSeen', '1'));
  let release; const gate = new Promise(resolve => release = resolve);
  if (delayedMetadata) await p.route('**/api/regions', async route => {
    const response = await route.fetch(); await gate;
    await route.fulfill({ response }).catch(() => {});
  });
  await p.goto(base + '/' + suffix, { waitUntil: 'domcontentloaded' });
  await p.evaluate(() => {
    viewer.resolutionScale = .5; window.overviewRenderErrors = [];
    viewer.scene.renderError.addEventListener((_, e) => overviewRenderErrors.push(String(e)));
    marsMoons.setSpeed(0); marsMoons.setTime('2026-11-15T12:00:00Z');
  });
  await p.locator('#startExploring').click();
  await p.locator('#landing').waitFor({ state:'hidden' });
  await p.waitForFunction(() => marsMoons.systemFrame().available && !marsOverview.state().framePending);
  return { p, release: () => release?.() };
}
const state = () => page.evaluate(() => ({ ...marsOverview.state(), moons: marsMoons.state(),
  sun: { ...marsMoons.systemFrame().sunPosition }, camera: { ...viewer.camera.positionWC },
  lighting: { ...viewer.scene.light.direction }, choice: plannerLayout.globalChoice(),
  layer: document.querySelector('#layer').value, flat: viewer.terrainProvider instanceof Cesium.EllipsoidTerrainProvider,
  plannerVisible: baseMap.show && trekLayer.show, overlays: overlay.length,
  hour: document.querySelector('#hour').value, ls: document.querySelector('#ls').value }));
const distance = (a, b) => Math.hypot(a.x-b.x, a.y-b.y, a.z-b.z);
try {
  const opening = await open({ delayedMetadata: true }); page = opening.p;
  let s = await state();
  assert.equal(s.mode, 'playing'); assert.equal(s.moons.speed, 3600);
  assert.equal(s.choice, ''); assert.equal(s.layer, ''); assert(s.flat && s.plannerVisible); assert.equal(s.overlays, 0);
  assert(s.moons.moons.every(m => m.valid && m.scale === 1000));
  pass('Default entry selects planner imagery and automatically plays the physical moon system at 3,600×');
  const before = s; await new Promise(r => setTimeout(r, 650)); await frame(); s = await state();
  assert(Date.parse(s.moons.utc) - Date.parse(before.moons.utc) > 1200000);
  assert(distance(s.camera, before.camera) > 100000);
  assert(distance(s.sun, before.sun) > 1e8);
  assert(s.moons.moons.every((m, i) => distance(m.position, before.moons.moons[i].position) > 100000));
  const norm = Math.hypot(s.sun.x, s.sun.y, s.sun.z);
  assert(distance(s.lighting, { x:-s.sun.x/norm, y:-s.sun.y/norm, z:-s.sun.z/norm }) < 1e-8);
  assert.equal(s.hour, before.hour); assert.equal(s.ls, before.ls);
  pass('Camera, Sun lighting and moons advance together while planning time and season stay unchanged');
  await page.locator('#overviewToggle').click(); await frame();
  const paused = await state(); assert.equal(paused.mode, 'paused'); assert.equal(paused.moons.speed, 0);
  opening.release(); await page.waitForFunction(() => current && regions.length > 0); await frame();
  s = await state(); assert(distance(s.camera, paused.camera) < 1);
  assert.equal(s.moons.utc, paused.moons.utc);
  pass('Pause freezes motion; late startup metadata cannot fly back to Jezero or restart it');
  await page.screenshot({ path: path.join(out, 'overview-planner.png') });
  // Sweep actual ephemeris epochs in a paused view to verify Sun visibility and
  // occlusion, without inventing a decorative near-Mars Sun.
  let sawSun = false, sawHiddenSun = false; const sunChecks = [];
  for (let hour = 0; hour < 24; hour++) {
    await page.evaluate(hour => marsMoons.setTime(`2026-11-15T${String(hour).padStart(2,'0')}:00:00Z`), hour);
    await frame();
    const visible = await page.locator('#marsSun').evaluate(el => !el.hidden);
    sunChecks.push(await page.evaluate(hour => {
      const sun = marsMoons.systemFrame().sunPosition, cam = viewer.camera;
      const p = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, sun);
      const look = Cesium.Cartesian3.subtract(sun, cam.positionWC, new Cesium.Cartesian3());
      return { hour, sun, camera:cam.positionWC, pixel:p, forward:Cesium.Cartesian3.dot(look,cam.directionWC),
        hit:!!(p && cam.pickEllipsoid(p,MARS)), enabled:viewer.scene.globe.enableLighting,
        hidden:document.querySelector('#marsSun').hidden };
    }, hour));
    if (visible && !sawSun) await page.screenshot({ path: path.join(out, 'overview-sun.png') });
    sawSun ||= visible; sawHiddenSun ||= !visible;
  }
  await fs.writeFile(path.join(out,'sun-visibility.json'),JSON.stringify(sunChecks,null,2));
  assert(sawSun && sawHiddenSun);
  pass('The distant Sun enters and leaves the view as source-based time changes');
  await page.locator('#overviewToggle').click(); await frame();
  await page.mouse.move(900, 650); await page.mouse.down(); await page.mouse.move(940, 650); await page.mouse.up();
  assert.equal((await state()).mode, 'paused');
  pass('Dragging the map immediately pauses the automatic camera and clock');
  await page.locator('#overviewToggle').click(); await frame();
  await page.locator('#gmRail button[data-section="globalMaps"]').click();
  await page.locator('#globalLayer').selectOption('map:ctx'); await frame();
  assert.equal((await state()).ownsLight, false); assert.equal((await state()).choice, 'map:ctx');
  await page.locator('#drawerClose').click(); await page.locator('#overviewToggle').click(); await frame();
  s = await state(); assert.equal(s.choice, ''); assert(s.plannerVisible); assert.equal(s.mode, 'playing');
  pass('Map selection stops the overview; Play overview restores only the planner background');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable:true, value:true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const hidden = await state(); await frame();
  assert.equal(hidden.moons.speed, 0); assert.equal((await state()).moons.utc, hidden.moons.utc);
  await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); });
  await frame(); assert.equal((await state()).moons.speed, 3600);
  pass('A hidden tab suspends the accelerated clock and resumes without accumulating hidden time');
  // Exercise the ordinary clock across midnight, including its prefetch.
  await page.evaluate(() => { marsOverview.pause(); marsMoons.setTime('2026-11-15T21:00:00Z'); marsMoons.setSpeed(3600); });
  await page.waitForFunction(() => marsMoons.state().utc.startsWith('2026-11-16') && marsMoons.systemFrame().available);
  assert((await state()).moons.moons.every(m => m.valid));
  pass('Accelerated playback crosses a UTC day boundary with valid Sun and moon data');
  await page.route('**/api/moons/ephemeris?date=2026-11-20', route => route.fulfill({ status:503, json:{detail:'Deliberate audit source failure'} }));
  await page.evaluate(() => { marsMoons.setTime('2026-11-20T12:00:00Z'); marsOverview.start(); });
  await page.waitForFunction(() => marsMoons.systemFrame().error && marsOverview.state().mode === 'paused');
  assert.equal((await state()).moons.speed, 0);
  assert((await state()).moons.moons.every(m => !m.valid));
  assert(await page.locator('#marsSun').evaluate(el => el.hidden));
  assert.match(await page.locator('#overviewReadout').textContent(), /unavailable/);
  await page.unroute('**/api/moons/ephemeris?date=2026-11-20');
  await page.locator('#overviewToggle').click();
  await page.waitForFunction(() => marsMoons.systemFrame().available && !marsOverview.state().framePending);
  assert.equal((await state()).mode, 'playing');
  pass('An unavailable ephemeris pauses and hides stale bodies; Play overview retries successfully');
  await page.emulateMedia({ reducedMotion:'reduce' });
  await page.evaluate(() => marsOverview.start());
  await page.emulateMedia({ reducedMotion:'no-preference' });
  await page.emulateMedia({ reducedMotion:'reduce' }); await frame();
  assert.equal((await state()).mode, 'paused');
  assert.deepEqual(await page.evaluate(() => overviewRenderErrors), []);
  await page.close();
  ({ p:page } = await open({ reducedMotion:'reduce' }));
  assert.equal((await state()).mode, 'paused'); assert.equal((await state()).moons.speed, 0);
  await page.setViewportSize({ width:430, height:900 });
  await page.locator('#overviewToggle').click(); await frame();
  assert(Object.values((await state()).camera).every(Number.isFinite));
  assert(await page.locator('#overviewToggle').isVisible());
  await page.screenshot({ path: path.join(out, 'overview-portrait.png') });
  pass('Reduced-motion preference pauses autoplay; explicit play and portrait framing remain usable');
  assert.deepEqual(await page.evaluate(() => overviewRenderErrors), []); await page.close();
  ({ p:page } = await open({ suffix:'?view=terrain', reducedMotion:'reduce' }));
  assert.equal((await state()).mode, 'idle');
  await page.waitForFunction(() => plannerLayout.globalChoice() === 'map:terrain');
  pass('Explicit terrain links keep their intended map and do not start an overview');
  assert.deepEqual(await page.evaluate(() => overviewRenderErrors), []);
  assert.deepEqual(errors, []); pass('No uncaught JavaScript or Cesium render errors');
} catch (error) {
  failure = String(error.stack || error);
  await page?.screenshot({ path: path.join(out, 'overview-failure.png') }).catch(() => {});
} finally {
  await fs.writeFile(path.join(out, 'overview-browser-results.json'), JSON.stringify({checks, errors, failure}, null, 2));
  await browser.close();
}
if (failure) throw new Error(failure);
