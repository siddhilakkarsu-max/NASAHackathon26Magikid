// Replay the original planner route after player edits, including an uncached run.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../frontend');
const files=Object.fromEntries(await Promise.all(['game.html','game-route-map.js','game-mission-results.js'].map(async name=>[name,await fs.readFile(path.join(root,name),'utf8')])));
const browser=await chromium.launch({executablePath:process.env.CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
  for(const mode of ['2d','3d']){
  const page=await browser.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{const name=new URL(route.request().url()).pathname.slice(1);return files[name]?route.fulfill({contentType:name.endsWith('.js')?'text/javascript':'text/html',body:files[name]}):route.fulfill({json:{}});});
  await page.goto('http://baseline.test/game.html?baked=0&skip=1&view='+mode+'&mute=1');
  await page.waitForFunction(()=>window.__MW?.state.R);
  if(mode==='3d')assert.equal(await page.locator('body').evaluate(el=>el.classList.contains('v3d')),true,'3D handling is enabled');
  await page.evaluate(()=>__MW.startBaked(__MW.state.baked.findIndex(n=>n.veh.key==='buggy'),0,'astronaut'));
  async function comparison(){
    // End locally without completing/submitting a ranked attempt.
    await page.evaluate(()=>__MW.kill('battery'));
    await page.waitForFunction(()=>['complete','failed'].includes(__MW.state.R.aiComparison?.status));
    return page.evaluate(()=>{
      const W=__MW.state.W,b=W.comparisonBaseline,calibration={};
      for(const field of Object.keys(b.calibration))calibration[field]=W[field];
      return {result:__MW.state.R.aiComparison,calibration,original:b.original.cands[W.ci].route.points,points:W.C.route.points};
    });
  }
  const before=await comparison();
  assert.equal(before.result.status,'complete');
  assert.equal(before.result.reference.status,'complete');
  assert.equal(before.result.own.ticks,before.result.reference.ticks,'initial player route is exactly the planner route');
  await page.evaluate(async()=>{
    const ctx=__MW.mapBridge.getContext(),points=ctx.C.route.points.map(p=>({...p}));
    points[Math.floor((points.length-1)/2)].lon+=.001;
    await __MW.mapBridge.applyRoute(points);
    // Recompute instead of returning a cached result; changing live weather must
    // also leave the benchmark's original comparison conditions alone.
    const G=__MW.state;G.W.comparisonBaseline.results.clear();
    const W=G.W;
    for(let h=0;h<48;h++)G.wxLive[[W.N.region,W.N.id,W.N.season.ls,W.lat0,W.lon0,h].join('|')]={ready:true,wind:30,to:90};
  });
  const edited=await comparison();
  assert.equal(edited.result.status,'complete');
  assert.equal(edited.result.own.status,'complete',JSON.stringify(edited.result.own));
  assert.notDeepEqual(edited.points,before.points,'the fixture actually edits the player route');
  assert.deepEqual(edited.original,before.original,'the original planner path remains intact');
  assert.deepEqual(edited.calibration,before.calibration,'player edits cannot recalibrate the vehicle or clock');
  assert.deepEqual(edited.result.reference,before.result.reference,'a fresh original-route replay is exactly unchanged');
  assert.notEqual(edited.result.own.ticks,before.result.own.ticks,'the AI player-route drive reflects the edit');
  await page.locator('#eRetry').click();
  const retried=await comparison();
  assert.deepEqual(retried.result.reference,edited.result.reference,'retry keeps the same original benchmark');
  assert.deepEqual(retried.result.own,edited.result.own,'same edited route reproduces the same AI drive');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({mode,originalTicks:before.result.reference.ticks,editedRouteTicks:edited.result.own.ticks,replayedOriginalTicks:edited.result.reference.ticks}));
  await page.close();
  }
  console.log('PASS original AI benchmark stays fixed across player edits, uncached replay and retry');
}finally{await browser.close();}
