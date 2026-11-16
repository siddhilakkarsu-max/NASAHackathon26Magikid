// A late Start driving response must not override a newer pause or popup action.
// All API responses are fixtures; no real callsign or score is created.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../frontend');
const html=await fs.readFile(path.join(root, 'game.html'), 'utf8');
const map=await fs.readFile(path.join(root, 'game-route-map.js'), 'utf8');
const resultsModule=await fs.readFile(path.join(root, 'game-mission-results.js'), 'utf8');
const begin=html.indexOf('const BAKED = [')+'const BAKED = ['.length;
const baked=JSON.parse('['+html.slice(begin,html.indexOf('\n];',begin))+']');
const plan=structuredClone(baked.find(p=>p.settings.vehicle.key==='buggy'));
plan.id='pause-fixture';
const points=plan.candidates[0].route.points.map(({lat,lon})=>({lat,lon}));
const metrics={distance_m:1000,round_trip_distance_m:2000,one_way_time_s:500,
  simulated_time_s:1000,round_trip_time_s:1000,science_time_s:3600,energy_wh:100};
const browser=await chromium.launch({executablePath:process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu']});
try {
  for(const operation of ['start','resume','failure']) for(const action of ['map','map-closed','board','board-closed','pause','blur']) {
    const context=await browser.newContext({viewport:{width:1280,height:900}});
    await context.addInitScript(()=>localStorage.setItem('marswalk.game.player',JSON.stringify({name:'TestPilot',token:'fixture-only'})));
    let attempt,release,blocked=false,hold=operation!=='resume';const errors=[];
    const gate=()=>new Promise(resolve=>{blocked=true;release=resolve;});
    const snapshot=()=>structuredClone(attempt);
    await context.route('**/*',async route=>{
      const u=new URL(route.request().url()),body=route.request().postDataJSON();
      if(u.pathname==='/game.html')return route.fulfill({contentType:'text/html',body:html});
      if(u.pathname==='/game-route-map.js')return route.fulfill({contentType:'text/javascript',body:map});
      if(u.pathname==='/game-mission-results.js')return route.fulfill({contentType:'text/javascript',body:resultsModule});
      if(u.pathname==='/api/mission/options')return route.fulfill({json:{vehicles:{buggy:{label:'Fixture rover'}}}});
      if(u.pathname==='/api/game/plans/pause-fixture')return route.fulfill({json:{plan,candidate:0,available:true,key:'fixture',reference:{points,metrics}}});
      if(u.pathname==='/api/game/route-attempts'){
        if(hold){await gate();hold=false;if(operation==='failure')return route.fulfill({status:503,json:{detail:'Temporary fixture outage'}});}
        attempt={id:'pause-attempt',plan_id:plan.id,candidate:0,key:'fixture',status:'active',mode:'paused',sequence:0,
          position:points[0],active_drive_s:0,samples:0,points,metrics,reference_metrics:metrics};
        return route.fulfill({json:snapshot()});
      }
      if(u.pathname.endsWith('/pause-attempt/progress')){
        attempt={...attempt,sequence:body.sequence,position:body.position,mode:body.mode,samples:body.samples};
        return route.fulfill({json:snapshot()});
      }
      if(u.pathname.endsWith('/pause-attempt/resume')){
        attempt.mode='paused';if(hold){await gate();hold=false;}return route.fulfill({json:snapshot()});
      }
      if(u.pathname.endsWith('/pause-attempt/restart')){attempt.status='invalidated';return route.fulfill({json:snapshot()});}
      if(u.pathname==='/api/tracks')return route.fulfill({json:{segments:[]}});
      if(u.pathname==='/api/game/leaderboard')return route.fulfill({json:{board:[],players:0}});
      return route.fulfill({json:{}});
    });
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://pause.test/game.html?plan=pause-fixture&view=2d&skip=1&mute=1');
    await page.waitForFunction(()=>window.__MW?.getSnapshot().screen==='brief');
    await page.locator('#bLaunch').click();
    if(operation==='resume'){
      await page.waitForFunction(()=>!__MW.getSnapshot().paused);
      await page.locator('#btnPause').click();await page.waitForFunction(()=>__MW.routeTracking().attempt?.mode==='paused');
      hold=true;await page.locator('#pResume').click();
    }
    for(let i=0;!blocked&&i<100;i++)await page.waitForTimeout(20);
    assert.ok(blocked,'request is pending before the newer user action');
    if(action.startsWith('map'))await page.locator('#btnEditMap').click();
    if(action.startsWith('board'))await page.locator('#btnLeaderboard').click();
    if(action==='map-closed')await page.getByRole('button',{name:'Back to rover',exact:true}).click();
    if(action==='board-closed')await page.locator('#boardClose').click();
    if(action==='pause')await page.locator('#btnPause').click();
    if(action==='blur')await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
    release();
    await page.waitForFunction(()=>!document.getElementById('btnDrive').disabled);
    assert.equal(await page.evaluate(()=>__MW.getSnapshot().paused),true,`${operation}/${action}: late response must preserve pause`);
    const time=await page.evaluate(()=>__MW.getSnapshot().t);await page.waitForTimeout(300);
    assert.equal(await page.evaluate(()=>__MW.getSnapshot().t),time,'paused mission time must stay fixed');
    if(attempt)assert.equal(attempt.mode,'paused','server attempt is paused too');
    if(action==='map')await page.getByRole('button',{name:'Back to rover',exact:true}).click();
    if(action==='board')await page.locator('#boardClose').click();
    if(action==='pause'||action==='blur')await page.locator('#pResume').click();else await page.locator('#btnDrive').click();
    await page.waitForFunction(()=>!__MW.getSnapshot().paused);
    assert.deepEqual(errors,[]);await context.close();
    console.log(`PASS ${operation}/${action}: newer pause wins; explicit resume works`);
  }
} finally {await browser.close();}
