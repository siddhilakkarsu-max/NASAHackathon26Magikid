// Original-game controls: pause clocks, refill accounting, cancel extraction and finish one site.
// Baked fixture and debug positioning avoid network/ranking; mini-games use keyboard controls.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../frontend');
const files=Object.fromEntries(await Promise.all(['game.html','game-route-map.js','game-mission-results.js'].map(async name=>[name,await fs.readFile(path.join(root,name),'utf8')])));
const browser=await chromium.launch({executablePath:process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu']});
try{
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{const name=new URL(route.request().url()).pathname.slice(1);return files[name]?route.fulfill({contentType:name.endsWith('.js')?'text/javascript':'text/html',body:files[name]}):route.fulfill({json:{}});});
  await page.goto('http://single-site.test/game.html?baked=0&skip=1&view=2d&mute=1');
  await page.waitForFunction(()=>window.__MW?.state.R && __MW.state.screen==='play');
  const read=()=>page.evaluate(()=>{const R=__MW.state.R;return{elapsed:R.elapsedS,driving:R.drivingElapsedS,oxygen:R.oxygenUsedKg,energy:R.energyUsedWh,o2:R.o2,bat:R.bat,t:R.t,site:!!R.site,samples:R.samples.length,completed:R.completedSamples,over:R.over,spots:R.W.spots.length};});
  assert.equal((await read()).spots,1);
  await page.keyboard.press('p');await page.waitForFunction(()=>__MW.state.paused);
  const paused=await read();await page.waitForTimeout(250);assert.deepEqual(await read(),paused,'paused game freezes all new counters');
  await page.keyboard.press('p');await page.waitForTimeout(250);assert.ok((await read()).elapsed>paused.elapsed);
  const refill=await page.evaluate(()=>{const R=__MW.state.R;R.o2=R.W.o2Cap*.3;return{o2:R.o2,used:R.oxygenUsedKg,added:__MW.CFG.O2_BOTTLE_KG};});
  await page.keyboard.press('o');await page.waitForTimeout(100);const afterO=await read();
  assert.ok(afterO.o2>refill.o2);assert.ok(Math.abs(afterO.oxygen-refill.used-(refill.o2+refill.added-afterO.o2))<1e-8,'refill cannot subtract past oxygen use');
  await page.evaluate(()=>{const i=__MW.state.baked.findIndex(n=>n.veh.key==='four_wheel');__MW.startBaked(i,0,'cadet');});
  const fresh=await read();assert.ok(fresh.elapsed<.1&&fresh.oxygen<.001&&fresh.energy<1,'new mission clears counters');
  const battery=await page.evaluate(()=>{const R=__MW.state.R;R.bat=R.W.batCap*.3;return{bat:R.bat,used:R.energyUsedWh,added:__MW.CFG.BATPACK_WH};});
  await page.keyboard.press('b');await page.waitForTimeout(100);const afterB=await read();
  assert.ok(afterB.bat>battery.bat);assert.ok(Math.abs(afterB.energy-battery.used-(battery.bat+battery.added-afterB.bat))<1e-7,'battery pack cannot subtract past energy use');
  await page.evaluate(()=>{__MW.teleport(__MW.state.R.W.L);__MW.setSpeed(10);});
  await page.waitForTimeout(150);await page.keyboard.press('e');await page.waitForFunction(()=>!!__MW.state.R.site);
  const atSite=await read();await page.waitForTimeout(300);const duringSite=await read();
  assert.ok(duringSite.elapsed>atSite.elapsed);assert.equal(duringSite.driving,atSite.driving,'mini-game time is excluded from driving');
  await page.keyboard.press('p');const sitePaused=await read();await page.waitForTimeout(200);assert.deepEqual(await read(),sitePaused,'mini-game pause freezes resource and clock counters');await page.keyboard.press('p');
  async function workUntil(predicate){
    const deadline=Date.now()+45000;
    while(Date.now()<deadline){
      const state=await page.evaluate(()=>{const R=__MW.state.R;return{over:R.over,extracted:!!R.site?.sample,wait:R.site?.wait||0,mode:R.site?.mg?.mode};});
      if(predicate(state)){await page.keyboard.up('Space');return;}
      if(state.wait>0){await page.keyboard.up('Space');await page.waitForTimeout(50);continue;}
      if(state.mode==='hold')await page.keyboard.down('Space');else{await page.keyboard.up('Space');if(state.mode)await page.keyboard.press('Space');}
      await page.waitForTimeout(50);
    }
    throw Error('Mini-game did not reach expected state');
  }
  await workUntil(s=>s.extracted);
  assert.equal((await read()).completed,0,'extraction alone is not a completed sample');
  await page.locator('#siteLeave').click();const cancelled=await read();
  assert.equal(cancelled.samples,0);assert.equal(cancelled.completed,0);assert.equal(cancelled.over,false,'cancelled sample cannot complete objective');
  await page.keyboard.press('e');await page.waitForFunction(()=>!!__MW.state.R.site);await workUntil(s=>s.over);
  await page.waitForFunction(()=>__MW.state.screen==='end');
  const done=await read();assert.equal(done.completed,1);assert.equal(done.samples,1);assert.equal(done.over,true);
  assert.equal(await page.evaluate(()=>__MW.state.R.outcome),'success');
  assert.ok(await page.evaluate(()=>Math.hypot(__MW.state.R.x-__MW.state.R.W.B.x,__MW.state.R.y-__MW.state.R.W.B.y)<10),'completion is at B without return travel');
  assert.equal(await page.locator('[data-result="oxygen"]').textContent(),done.oxygen.toFixed(3)+' kg');
  assert.equal(await page.locator('[data-result="energy"]').textContent(),done.energy.toFixed(1)+' Wh');
  await page.waitForTimeout(200);assert.deepEqual(await read(),done,'completed results stay frozen');
  await page.locator('#eRetry').click();const retried=await read();assert.equal(retried.completed,0);assert.equal(retried.samples,0);assert.equal(retried.elapsed,0);assert.equal(retried.oxygen,0);assert.equal(retried.energy,0);
  await page.evaluate(async()=>{const ctx=__MW.mapBridge.getContext(),points=ctx.C.route.points.map(p=>({lat:p.lat,lon:p.lon}));points[Math.floor((points.length-1)/2)].lon+=.001;await __MW.mapBridge.applyRoute(points);});
  const editedTime=await page.evaluate(()=>__MW.state.R.W.C.route.one_way_h*3600);
  async function finishAtB(){
    await page.evaluate(async()=>{await __MW.mapBridge.startDriving();__MW.teleport(__MW.state.R.W.L);__MW.setSpeed(10);});
    await page.waitForTimeout(100);await page.keyboard.press('e');await page.waitForFunction(()=>!!__MW.state.R.site);await workUntil(s=>s.over);await page.waitForFunction(()=>__MW.state.screen==='end');
  }
  await finishAtB();await page.locator('#eNext').click();
  const nextTime=await page.evaluate(()=>__MW.state.R.W.C.route.one_way_h*3600);assert.notEqual(editedTime,nextTime,'fixture candidates have different travel models');
  await finishAtB();
  await page.waitForFunction(()=>__MW.state.R.aiComparison?.status==='complete');
  assert.equal(await page.locator('[data-result="player-model-time"]').textContent(),await page.evaluate(()=>MarswalkMissionResults.duration(__MW.state.R.aiComparison.own.seconds)),'next objective uses its own measured driving simulation');
  await page.evaluate(()=>{const i=__MW.state.baked.findIndex(n=>n.veh.key==='buggy');__MW.startBaked(i,0,'cadet');});
  await finishAtB();
  const cabin=await page.evaluate(()=>__MW.state.R.t/24*.895);
  assert.equal(await page.locator('[data-result="oxygen"]').textContent(),cabin.toFixed(3)+' kg','cabin oxygen uses simulated hours, not play seconds or hours treated as seconds');
  assert.ok((await page.locator('#missionResultsSummary').textContent()).includes('cabin estimate'));
  assert.deepEqual(errors,[]);
  console.log('PASS single-site mission: pause and sampling clocks, O2/battery refills, cancelled extraction, one completed sample at B, results, retry reset and edit-to-next-objective model');
}finally{await browser.close();}
