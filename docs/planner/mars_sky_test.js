// Deterministic lifecycle tests; no network and no generated scientific values.
const assert = require('node:assert/strict');
const { createMarsSky, marsDustHazeFactor } = require('../../frontend/mars_sky.js');

function event() {
  const listeners = new Set();
  return { addEventListener(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    raise() { for (const fn of listeners) fn(); }, get size() { return listeners.size; } };
}
function setup(api = async () => ({ value: 0.3, grid_step_deg: 5 })) {
  const oldSky = {}, preRender = event(), moveEnd = event(), calls = [], statuses = [];
  const skyCoefficient = { x: 14e-6, y: 9e-6, z: 5e-6 };
  const groundCoefficient = { x: 21e-6, y: 21e-6, z: 21e-6 };
  const fog = { enabled: true, density: 0.0001 };
  const viewer = { scene: { preRender, skyBox: oldSky, fog, requestRender() {},
    globe: { enableLighting: true, atmosphereMieCoefficient: { ...groundCoefficient } },
    skyAtmosphere: { show: true, atmosphereMieCoefficient: { ...skyCoefficient } } },
    camera: { moveEnd, positionCartographic: { height: 30000 } } };
  const condition = { ls: 90, local_hour: 12 }, location = { lat: 18.45, lon: 77.45 };
  const engine = { Cartesian3: { clone: v => ({ ...v }), multiplyByScalar(v, s, out) {
    Object.assign(out, { x: v.x * s, y: v.y * s, z: v.z * s }); return out;
  } }, SkyBox: class { constructor(options) { Object.assign(this, options); this.dead = false; }
    destroy() { this.dead = true; } isDestroyed() { return this.dead; } } };
  const sky = createMarsSky({ viewer, Cesium: engine, getLocation: () => location,
    getConditions: () => condition, loadStarFaces: async () => ({ testFaces: true }),
    onStatus: (...args) => statuses.push(args), api: (...args) => { calls.push(args); return api(...args); } });
  return { viewer, sky, calls, statuses, condition, location, oldSky, skyCoefficient, groundCoefficient };
}
function baseline(ctx) {
  assert.deepEqual(ctx.viewer.scene.skyAtmosphere.atmosphereMieCoefficient, ctx.skyCoefficient);
  assert.deepEqual(ctx.viewer.scene.globe.atmosphereMieCoefficient, ctx.groundCoefficient);
}
async function run() {
  const checks = [];
  async function test(name, fn) { await fn(); checks.push(name); console.log('PASS ' + name); }
  await test('stars install behind the globe through native SkyBox and restore on destroy', async () => {
    const x = setup(); assert.equal(await x.sky.ready, true);
    const owned = x.viewer.scene.skyBox;
    assert.equal(owned.show, true); x.sky.setStarsEnabled(false); assert.equal(owned.show, false);
    x.sky.setStarsEnabled(true); assert.equal(owned.show, true);
    assert.equal(x.viewer.scene.preRender.size, 1); assert.equal(x.viewer.camera.moveEnd.size, 1);
    x.sky.destroy(); assert.equal(x.viewer.scene.skyBox, x.oldSky); assert.equal(owned.isDestroyed(), true);
    assert.equal(x.viewer.scene.preRender.size, 0); assert.equal(x.viewer.camera.moveEnd.size, 0);
    baseline(x);
  });
  await test('dust disabled, whole-planet view and disabled lighting make zero requests', async () => {
    const x = setup(); await x.sky.ready; await x.sky.refresh(); x.viewer.camera.moveEnd.raise();
    assert.equal(x.calls.length, 0);
    x.viewer.camera.positionCartographic.height = 500000; await x.sky.setDustEnabled(true);
    assert.equal(x.sky.getState().dustPhase, 'zoom-in'); assert.equal(x.calls.length, 0);
    x.viewer.camera.positionCartographic.height = 1000; x.viewer.scene.globe.enableLighting = false;
    await x.sky.refresh({ immediate: true }); assert.equal(x.sky.getState().dustPhase, 'lighting-off');
    assert.equal(x.calls.length, 0); baseline(x); x.sky.destroy();
  });
  await test('haze changes only scattering, preserves source opacity and restores off', async () => {
    const x = setup(); await x.sky.setDustEnabled(true);
    assert.equal(x.sky.getState().dustTau, 0.3); assert.equal(x.sky.getState().gridStepDeg, 5);
    const factor = marsDustHazeFactor(0.3, 30000);
    assert.equal(x.viewer.scene.skyAtmosphere.atmosphereMieCoefficient.x, x.skyCoefficient.x * factor);
    assert.equal(x.viewer.scene.globe.atmosphereMieCoefficient.x, x.groundCoefficient.x * factor);
    assert.deepEqual(x.viewer.scene.fog, { enabled: true, density: 0.0001 });
    assert(x.sky.getState().message.includes('not observed clouds'));
    assert(x.statuses.every(([text]) => typeof text === 'string'));
    x.viewer.scene.globe.enableLighting = false; x.viewer.scene.preRender.raise(); baseline(x);
    await x.sky.refresh({ immediate: true }); assert.equal(x.sky.getState().dustPhase, 'lighting-off');
    x.viewer.scene.globe.enableLighting = true; await x.sky.refresh({ immediate: true });
    assert.equal(x.calls.length, 1); assert.equal(x.sky.getState().dustTau, 0.3);
    await x.sky.setDustEnabled(false); baseline(x); assert.equal(x.sky.getState().dustTau, null); x.sky.destroy();
  });
  await test('nearest-cell cache matches north-first backend and exact boundaries', async () => {
    const x = setup(); await x.sky.setDustEnabled(true);
    x.location.lat = 19; x.location.lon = 79; await x.sky.refresh({ immediate: true });
    assert.equal(x.calls.length, 1); assert.equal(x.sky.getState().location.lat, 19);
    x.location.lat = 20; await x.sky.refresh({ immediate: true }); assert.equal(x.calls.length, 1);
    x.location.lat = 20.0001; await x.sky.refresh({ immediate: true }); assert.equal(x.calls.length, 2);
    x.location.lon = 80; await x.sky.refresh({ immediate: true }); assert.equal(x.calls.length, 3);
    x.sky.destroy();
  });
  await test('rapid season changes debounce to the latest season', async () => {
    const x = setup(); await x.sky.setDustEnabled(true);
    x.condition.ls = 100; const a = x.sky.refresh(); x.condition.ls = 110; const b = x.sky.refresh();
    x.condition.ls = 120; const c = x.sky.refresh();
    await Promise.all([a, b, c]); assert.equal(x.calls.length, 2);
    assert.equal(x.calls[1][1].ls, 120); assert.equal(x.sky.getState().ls, 120); x.sky.destroy();
  });
  await test('late response cannot revive disabled dust or replace a newer season', async () => {
    const pending = []; const x = setup(() => new Promise(resolve => pending.push(resolve)));
    const first = x.sky.setDustEnabled(true); await x.sky.setDustEnabled(false);
    pending[0]({ value: 0.8 }); await first; assert.equal(x.sky.getState().dustPhase, 'off'); baseline(x);
    const second = x.sky.setDustEnabled(true); x.condition.ls = 180;
    const third = x.sky.refresh({ immediate: true });
    pending[2]({ value: 0.4 }); await third; pending[1]({ value: 0.9 }); await second;
    assert.equal(x.sky.getState().ls, 180); assert.equal(x.sky.getState().dustTau, 0.4); x.sky.destroy();
  });
  await test('missing data and source failure remove stale haze', async () => {
    let response = { value: 0.4 }; const x = setup(async () => { if (response instanceof Error) throw response; return response; });
    await x.sky.setDustEnabled(true); response = { value: null }; x.condition.ls = 180;
    await x.sky.refresh({ immediate: true }); baseline(x); assert.equal(x.sky.getState().dustPhase, 'unavailable');
    response = Error('Source unavailable'); x.condition.ls = 270; await x.sky.refresh({ immediate: true });
    baseline(x); assert.equal(x.sky.getState().dustTau, null); assert.equal(x.sky.getState().dustError, 'Source unavailable');
    x.sky.destroy();
  });
  await test('bounded visualization fades to zero at orbit and does not manufacture missing dust', async () => {
    assert.equal(marsDustHazeFactor(null, 0), 1); assert.equal(marsDustHazeFactor(-1, 0), 1);
    assert.equal(marsDustHazeFactor(0, 0), 1); assert.equal(marsDustHazeFactor(1, 350000), 1);
    assert(marsDustHazeFactor(1, 235000) > 1); assert(marsDustHazeFactor(100, 0) < 4);
  });
  console.log(JSON.stringify({ passed: checks.length, checks }, null, 2));
}
run().catch(error => { console.error(error); process.exitCode = 1; });
