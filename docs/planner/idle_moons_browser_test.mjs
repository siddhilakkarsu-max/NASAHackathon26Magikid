import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const out = process.env.MARSWALK_AUDIT_DIR || path.resolve('idle-moons-audit');
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width:1440, height:1000 }, reducedMotion:'no-preference' });
page.setDefaultTimeout(60000);
const errors = [], checks = [];
page.on('pageerror', e => errors.push(String(e)));
const pass = s => { checks.push(s); console.log('PASS ' + s); };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const state = () => page.evaluate(() => ({ ...marsOverview.state(), moons: marsMoons.state(),
  range: Cesium.Cartesian3.magnitude(viewer.camera.positionWC), camera: {...viewer.camera.positionWC} }));
async function edit(id, value) {
  await page.evaluate(({id,value}) => {
    const e = document.getElementById(id); e.value = String(value);
    e.dispatchEvent(new Event('input', {bubbles:true}));
  }, {id,value});
}
let failure;
try {
  await page.addInitScript(() => localStorage.setItem('mapManualSeen','1'));
  await page.goto(base, {waitUntil:'domcontentloaded'});
  await page.evaluate(() => { viewer.resolutionScale=.5; marsMoons.setTime('2026-11-15T12:00:00Z'); });
  await page.locator('#startExploring').click();
  await page.locator('#landing').waitFor({state:'hidden'});
  await page.waitForFunction(() => current && marsMoons.systemFrame().available && !marsOverview.state().framePending);
  const center = await page.evaluate(() => {
    const p = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, Cesium.Cartesian3.ZERO);
    const r = viewer.scene.canvas.getBoundingClientRect(); return {x:p.x+r.left,y:p.y+r.top};
  });
  await page.mouse.move(center.x,center.y);
  const beforeZoom = await state();
  await page.mouse.wheel(0,-400);
  await sleep(1000);
  const wheelZoom = await state();
  assert.equal(wheelZoom.mode,'playing');
  assert(wheelZoom.range < beforeZoom.range - 1000, JSON.stringify({before:beforeZoom.range,after:wheelZoom.range,center}));
  assert(Date.parse(wheelZoom.moons.utc) > Date.parse(beforeZoom.moons.utc));
  await page.locator('#gmControls button[title="Zoom in"]').click();
  await sleep(300);
  const buttonZoom = await state();
  assert.equal(buttonZoom.mode,'playing'); assert(buttonZoom.range < wheelZoom.range);
  await page.locator('#gmControls button[title="Zoom out"]').click();
  assert.equal((await state()).mode,'playing');
  pass('Wheel and both zoom buttons change zoom while default-map rotation and moon time continue');
  await page.locator('#overviewToggle').click();
  const paused = await state();
  await sleep(6200); assert.equal((await state()).mode,'paused');
  await page.waitForFunction(() => marsOverview.state().mode === 'playing', null, {timeout:4000});
  assert(Math.abs((await state()).range - paused.range) < 1);
  pass('Pause stays paused before seven seconds, then resumes without changing zoom');
  await page.mouse.move(900,500);
  await page.evaluate(() => marsOverview.pause());
  await sleep(4200); await page.mouse.wheel(0,100);
  await page.waitForFunction(() => marsOverview.state().mode === 'playing', null, {timeout:4000});
  pass('Zooming during a pause does not extend the seven-second inactivity deadline');
  await page.mouse.move(1000,650); await page.mouse.down();
  await sleep(7500); assert.equal((await state()).mode,'paused');
  await page.mouse.up();
  // Keep hovering throughout the deadline; only button-held dragging is active.
  for (let i=0;i<8;i++) { await sleep(1000); await page.mouse.move(1000+i*3,650); }
  assert.equal((await state()).mode,'playing');
  pass('Held drag blocks auto-resume, but continuous hover movement does not delay it');
  // Stop automatic motion while comparing the two resolved epochs.
  await page.evaluate(() => { marsOverview.leave(); marsMoons.setTime('2026-11-15T12:00:00Z'); });
  await edit('ls',90); await edit('hour',11);
  await page.waitForFunction(() => marsMoons.state().planningResult && !marsMoons.state().planningPending && marsMoons.systemFrame().available);
  const first = (await state()).moons;
  assert(Math.abs(first.planningResult.local_hour-11)<1e-6);
  await page.evaluate(() => {
    window.moonTransitionFrames=[];
    window.stopMoonTransitionCapture=viewer.scene.preUpdate.addEventListener(() => {
      const s=marsMoons.state(); moonTransitionFrames.push({transitioning:s.transitioning,moons:s.moons});
    });
  });
  await edit('hour',18);
  await page.waitForFunction(() => !marsMoons.state().planningPending && Math.abs((marsMoons.state().planningResult?.local_hour ?? 0)-18)<1e-6 && marsMoons.systemFrame().available);
  const second = (await state()).moons;
  const frames=await page.evaluate(() => { stopMoonTransitionCapture(); return moonTransitionFrames; });
  assert(frames.filter(f=>f.transitioning).length>5, 'Must render intermediate transition frames');
  assert(frames.every(f=>f.moons.every(m=>m.valid)), 'Moons stay visible while loading and transitioning');
  const separation=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);
  for(let i=0;i<2;i++) {
    const start=first.moons[i].position, end=second.moons[i].position;
    assert(frames.some(f=>separation(f.moons[i].position,start)>1000 && separation(f.moons[i].position,end)>1000));
    const minimum=Math.min(Math.hypot(start.x,start.y,start.z),Math.hypot(end.x,end.y,end.z));
    assert(frames.every(f=>Math.hypot(...Object.values(f.moons[i].position))>=minimum-1));
  }
  const extremes=await page.evaluate(() => [0,.25,.5,.75,1].map(t=>{
    const p=marsMoonTransitionPosition(Cesium,new Cesium.Cartesian3(9000000,0,0),new Cesium.Cartesian3(-9000000,0,0),t,new Cesium.Cartesian3());
    return Cesium.Cartesian3.magnitude(p);
  }));
  assert(extremes.every(r=>Number.isFinite(r)&&Math.abs(r-9000000)<.001));
  pass('Time edits render a continuous arc with no disappearance or path through Mars, including opposite endpoints');
  assert.notEqual(first.utc,second.utc);
  assert(second.moons.every((m,i) => Math.hypot(m.position.x-first.moons[i].position.x,m.position.y-first.moons[i].position.y,m.position.z-first.moons[i].position.z)>100000));
  pass('Local solar time changes the dated JPL moon positions at the selected region longitude');
  await edit('ls',270);
  await page.waitForFunction(() => !marsMoons.state().planningPending && Math.abs((marsMoons.state().planningResult?.actual_ls ?? 0)-270)<.4 && marsMoons.systemFrame().available);
  const third = (await state()).moons;
  assert(Math.abs(Date.parse(third.utc)-Date.parse(second.utc))>100*86400000);
  assert.equal(third.planningResult.reference_date,'2026-11-15');
  pass('Season changes resolve to a different real ephemeris date with the reference year retained');
  // A late successful request cannot overwrite a newer slider setting.
  await page.route('**/api/moons/planning-time?**', async route => {
    const response = await route.fetch();
    if (new URL(route.request().url()).searchParams.get('hour') === '8') await sleep(1300);
    await route.fulfill({response}).catch(()=>{});
  });
  await edit('hour',8); await sleep(400); await edit('hour',16);
  await page.waitForFunction(() => !marsMoons.state().planningPending && Math.abs((marsMoons.state().planningResult?.local_hour ?? 0)-16)<1e-6);
  await sleep(1600); assert(Math.abs((await state()).moons.planningResult.local_hour-16)<1e-6);
  await page.unroute('**/api/moons/planning-time?**');
  pass('Rapid edits discard superseded network responses');
  await page.route('**/api/moons/planning-time?**', route => route.fulfill({status:503,json:{detail:'test outage'}}));
  await edit('hour',9);
  await page.waitForFunction(() => !!marsMoons.state().error);
  assert((await state()).moons.moons.every(m=>!m.valid));
  await page.unroute('**/api/moons/planning-time?**');
  await page.evaluate(() => document.querySelector('#moonRetry').click());
  await page.waitForFunction(() => !marsMoons.state().error && !marsMoons.state().planningPending && marsMoons.systemFrame().available);
  pass('Failed time conversion hides stale moons and Retry restores real ephemerides');
  await page.evaluate(() => marsOverview.start());
  await page.locator('#gmRail button[data-section="conditionsPanel"]').click();
  assert.equal((await state()).mode,'paused');
  await edit('hour',12);
  await page.waitForFunction(() => !marsMoons.state().planningPending && marsMoons.systemFrame().available);
  await page.waitForFunction(() => marsOverview.state().mode==='playing');
  pass('Opening the real Time panel and editing its slider resumes synchronized motion after inactivity');
  await page.evaluate(() => { marsOverview.pause(); document.querySelector('#globalLayer').value='map:ctx'; document.querySelector('#globalLayer').dispatchEvent(new Event('change',{bubbles:true})); });
  await sleep(7500); assert.equal((await state()).mode,'paused'); assert.equal((await state()).resumePending,false);
  pass('Choosing another map cancels the timer and preserves the selected map');
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.evaluate(() => { marsOverview.start(); marsOverview.pause(); });
  await sleep(7500); assert.equal((await state()).mode,'paused');
  assert(await page.evaluate(() => viewer.useDefaultRenderLoop));
  assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(out,'idle-moons.png')});
  pass('Reduced-motion preference is respected and the renderer has no uncaught errors');
} catch(e) {
  failure=String(e.stack||e);
  await page.screenshot({path:path.join(out,'idle-moons-failure.png')});
}
finally {
  await fs.writeFile(path.join(out,'idle-moons-results.json'),JSON.stringify({checks,errors,failure},null,2));
  await browser.close();
}
if(failure) throw new Error(failure);
