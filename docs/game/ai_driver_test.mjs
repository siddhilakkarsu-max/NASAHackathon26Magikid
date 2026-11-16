// Real fixed-step driving simulations, with no leaderboard writes or UI renderer.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({executablePath:process.env.CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const base=process.env.MARSWALK_TEST_URL||'http://127.0.0.1:8001';
try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/game.html?baked=0&skip=1&mute=1&view=2d');
  await page.waitForFunction(()=>window.__MW?.state.R);
  const payloads=await page.evaluate(()=>{
    const G=__MW.state;return G.baked.flatMap((N,i)=>N.cands.map((C,ci)=>{
      __MW.startBaked(i,ci,'astronaut');const W=G.W,calibration={};for(const k of ['TS','kSpeed','kDist','kO2','kWh'])calibration[k]=W[k];
      return {mission:JSON.parse(JSON.stringify(N)),candidate:ci,difficulty:'astronaut',seed:W.seed,calibration,driving3d:true,speedLimit:45};
    }));
  });
  await page.goto(base+'/game.html?drive-benchmark=1');
  await page.waitForFunction(()=>window.__MW?.state.benchmark);
  const results=[];
  for(const payload of payloads){
    const result=await page.evaluate(p=>__MW.runDriveBenchmark(p),payload);
    results.push({mission:payload.mission.id,vehicle:payload.mission.veh.key,candidate:payload.candidate,...result});
    console.log(JSON.stringify(results.at(-1)));
    assert.equal(result.status,'complete');assert.ok(result.seconds>0&&result.seconds<1800);
    assert.ok(Math.abs(result.seconds-result.ticks/30)<1e-6,'AI time is measured simulation ticks, not a planner estimate');
    assert.ok(Math.hypot(result.end.x-result.destination.x,result.end.y-result.destination.y)<9);
    const top={on_foot:6,two_wheel:8,four_wheel:13,buggy:10}[payload.mission.veh.key];
    assert.ok(result.maxKmh<=top+1e-9,'ideal driver respects its physical speed envelope');
    const points=payload.mission.cands[payload.candidate].route.points,lat0=points[0].lat;
    const metres=59274.6975; // Game's local Mars map projection.
    const exact=points.slice(1).reduce((sum,p,i)=>sum+Math.hypot((p.lon-points[i].lon)*metres*Math.cos(lat0*Math.PI/180),(p.lat-points[i].lat)*metres),0)*payload.calibration.kDist;
    assert.ok(Math.abs(result.distanceM-exact)<.1,'every original segment is included; corners are not cut');
  }
  const repeated=await page.evaluate(p=>__MW.runDriveBenchmark(p),payloads[0]);
  assert.equal(repeated.seconds,results[0].seconds,'same seed and route reproduce the actual drive');
  assert.deepEqual(errors,[]);
  await fs.writeFile('game_state/ai-driver-audit.json',JSON.stringify(results,null,2));
  console.log('PASS actual AI driving comparisons: '+results.length+' routes, repeatability, arrival and common clock');
}finally{await browser.close();}
