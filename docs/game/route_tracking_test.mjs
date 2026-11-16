// Browser regression for slow/lost route-tracking responses. All APIs are mocked;
// this test neither contacts a server nor creates a real player or leaderboard entry.
// PLAYWRIGHT_MODULE and CHROME accept the same overrides as integration_test.mjs.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const here=path.dirname(fileURLToPath(import.meta.url));
const frontend=process.argv[2] || path.join(here,'../../frontend');
const html=await fs.readFile(path.join(frontend,'game.html'),'utf8');
const routeMap=await fs.readFile(path.join(frontend,'game-route-map.js'),'utf8');
const resultsModule=await fs.readFile(path.join(frontend,'game-mission-results.js'),'utf8');
const begin=html.indexOf('const BAKED = [')+'const BAKED = ['.length;
const baked=JSON.parse('['+html.slice(begin,html.indexOf('\n];',begin))+']');
const plan=structuredClone(baked.find(p=>p.settings.vehicle.key==='buggy') || baked[0]);
plan.id='tracking-fixture';
const points=plan.candidates[0].route.points.map(({lat,lon})=>({lat,lon}));
const metrics={distance_m:1000,round_trip_distance_m:2000,one_way_time_s:500,
  simulated_time_s:1000,round_trip_time_s:1000,science_time_s:3600,energy_wh:100};
const browser=await chromium.launch({
  executablePath:process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']
});
const context=await browser.newContext({viewport:{width:1280,height:900}});
await context.addInitScript(()=>localStorage.setItem('marswalk.game.player',JSON.stringify({name:'TestPilot',token:'fixture-only'})));
let state,updated=0,delayed=false,dropNext=false,dropped=false;
const errors=[],rejections=[],accepted=[];
const snapshot=()=>structuredClone(state);
const metres=(a,b)=>Math.hypot((a.lat-b.lat)*59158,(a.lon-b.lon)*59158*Math.cos(a.lat*Math.PI/180));
await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url()),body=request.postDataJSON();
  if(url.pathname==='/game.html')return route.fulfill({contentType:'text/html',body:html});
  if(url.pathname==='/game-route-map.js')return route.fulfill({contentType:'text/javascript',body:routeMap});
  if(url.pathname==='/game-mission-results.js')return route.fulfill({contentType:'text/javascript',body:resultsModule});
  if(url.pathname==='/api/mission/options')return route.fulfill({json:{vehicles:{buggy:{label:'Fixture rover'}}}});
  if(url.pathname==='/api/game/plans/tracking-fixture')return route.fulfill({json:{plan,candidate:0,available:true,key:'fixture',reference:{points,metrics}}});
  if(url.pathname==='/api/game/route-attempts'){
    state={id:'fixture-attempt',plan_id:plan.id,candidate:0,key:'fixture',status:'active',mode:'paused',sequence:0,
      position:points[0],active_drive_s:0,samples:0,visited_destination:false,points,metrics,reference_metrics:metrics};
    updated=Date.now();return route.fulfill({json:snapshot()});
  }
  if(url.pathname.endsWith('/fixture-attempt/progress')){
    const now=Date.now(),elapsed=(now-updated)/1000;
    const allowance=state.mode==='driving'&&elapsed<=4?60*elapsed:0;
    const distance=metres(state.position,body.position);
    if(body.sequence!==state.sequence+1 || distance>allowance+.001){
      rejections.push({sequence:body.sequence,elapsed,distance,allowance});
      return route.fulfill({status:400,json:{detail:'Movement exceeds the active driving allowance.'}});
    }
    state={...state,sequence:body.sequence,position:body.position,mode:body.mode,samples:body.samples,
      active_drive_s:state.active_drive_s+(state.mode==='driving'&&elapsed<=4?elapsed:0)};
    updated=now;accepted.push({sequence:state.sequence,mode:state.mode,elapsed,distance});
    const response=snapshot();
    // The server accepts first; only its ACK is delayed. Old clients replayed
    // queued positions immediately afterward and exceeded the server clock.
    if(!delayed&&body.sequence===2){delayed=true;await new Promise(resolve=>setTimeout(resolve,1600));}
    else if(dropNext&&body.mode==='driving'){dropNext=false;dropped=true;return route.abort('failed');}
    return route.fulfill({json:response});
  }
  if(url.pathname.endsWith('/fixture-attempt/resume')){
    state.mode='paused';updated=Date.now();return route.fulfill({json:snapshot()});
  }
  if(url.pathname.endsWith('/fixture-attempt/restart')){
    state.status='invalidated';return route.fulfill({json:snapshot()});
  }
  if(url.pathname==='/api/tracks')return route.fulfill({json:{segments:[]}});
  if(url.pathname==='/api/game/leaderboard')return route.fulfill({json:{board:[],players:0}});
  return route.fulfill({json:{}});
});

try{
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://tracking.test/game.html?plan=tracking-fixture&cand=0&view=2d&skip=1&mute=1');
  await page.waitForFunction(()=>window.__MW?.getSnapshot().screen==='brief');
  await page.locator('#bLaunch').click();await page.locator('#btnDrive').click();
  await page.waitForFunction(()=>!__MW.getSnapshot().paused);
  // Use an ordinary movement key, selected from the original route heading.
  const direction=await page.evaluate(()=>{const W=__MW.state.W,dx=W.B.x-W.A.x,dy=W.B.y-W.A.y;return Math.abs(dx)>Math.abs(dy)?dx>0?'d':'a':dy>0?'w':'s';});
  await page.keyboard.down(direction);await page.waitForTimeout(4800);await page.keyboard.up(direction);
  assert.equal(delayed,true);
  assert.equal(await page.evaluate(()=>__MW.getSnapshot().paused),false,'a delayed ACK must not cause a stale-position burst');
  assert.deepEqual(rejections,[]);
  assert.ok(accepted.length>=4,'driving resumes normal heartbeats after the delayed ACK');

  await page.locator('#btnEditMap').click();
  await page.waitForFunction(()=>__MW.routeTracking().attempt?.mode==='paused');
  assert.equal(state.mode,'paused','pausing must still send its final position');
  await page.getByRole('button',{name:'Back to rover',exact:true}).click();
  await page.locator('#btnDrive').click();await page.waitForFunction(()=>!__MW.getSnapshot().paused);
  dropNext=true;await page.keyboard.down(direction);
  await page.waitForFunction(()=>__MW.getSnapshot().paused&&__MW.routeTracking().attempt?.mode==='paused');
  await page.keyboard.up(direction);assert.equal(dropped,true);
  const recovered=await page.evaluate(()=>{const R=__MW.state.R;return{lat:R.W.toLat(R.y),lon:R.W.toLon(R.x)};});
  assert.ok(metres(recovered,state.position)<.001,'lost ACK recovery must use the latest server position');
  await page.locator('#btnDrive').click();await page.waitForFunction(()=>!__MW.getSnapshot().paused);
  assert.equal(await page.evaluate(()=>__MW.routeTracking().unranked),false);
  assert.deepEqual(rejections,[]);assert.deepEqual(errors,[]);
  console.log('PASS delayed ACK coalescing, final pause packet, authoritative lost-ACK recovery and ranked resume');
}finally{await browser.close();}
