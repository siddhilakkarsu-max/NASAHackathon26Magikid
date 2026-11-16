// Full original-game playthroughs in headless WebGL, using its demo autopilot.
// Use an isolated local server. No callsign is configured and no score is submitted.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=(process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8013').replace(/\/$/,'');
const browser=await chromium.launch({executablePath:process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
let completed=0;
try{
  const probe=await browser.newPage();
  await probe.goto(base+'/game.html?skip=1&mute=1');
  await probe.waitForFunction(()=>!!window.__MW);
  const counts=await probe.evaluate(()=>__MW.state.baked.map(n=>n.cands.length));
  await probe.close();
  for(let m=0;m<counts.length;m++)for(let c=0;c<counts[m];c++){
    const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[];
    let attempts=0;
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>{if(request.url().includes('/api/game/route-attempts'))attempts++;});
    await page.goto(`${base}/game.html?baked=${m}&cand=${c}&autopilot=1&skip=1&speed=40&mute=1`);
    await page.waitForFunction(()=>window.__MW?.getSnapshot().screen==='play');
    assert.equal(await page.locator('body').evaluate(el=>el.classList.contains('v3d')),true,'WebGL game is active');
    let snapshot,nan=false;const start=Date.now();
    do{
      snapshot=await page.evaluate(()=>__MW.getSnapshot());nan=nan||snapshot.nan;
      if(snapshot.over)break;
      await page.waitForTimeout(200);
    }while(Date.now()-start<120000);
    assert.equal(snapshot.outcome,'success',`mission ${m}, route ${c+1}: ${snapshot.cause||'timeout'}`);
    assert.equal(nan,false);assert.equal(snapshot.samples,3);assert.equal(attempts,0);assert.deepEqual(errors,[]);
    completed++;console.log(`PASS original 3D mission ${m}, route ${c+1}: ${snapshot.mission.vehicle}, 3 samples, storm ${snapshot.storm}`);
    await page.close();
  }
  console.log(`PASS ${completed}/${counts.reduce((n,c)=>n+c,0)} original routes; no NaNs, page errors or ranked autopilot attempts`);
}finally{await browser.close();}
