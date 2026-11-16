// Normal-speed keyboard mission against an isolated local API; never use the public leaderboard.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=process.env.MARSWALK_TEST_URL||'http://127.0.0.1:8014',request={goal:'find clay where water once flowed',vehicle:'buggy',season:'ls_90',ls:90,priority:'safety',green_only:false,local_hour:12};
await fs.mkdir('game_state/single-site-audit',{recursive:true});
const mission=await(await fetch(base+'/api/mission',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...request,region:'jezero'})})).json();
const callsign='Drive'+Date.now().toString().slice(-7);
const browser=await chromium.launch({executablePath:process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({viewport:{width:1280,height:900}});
const page=await context.newPage(),errors=[],packets=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',async r=>{if(r.url().includes('route-attempts')&&r.status()>=400){const entry={url:r.url(),status:r.status(),detail:await r.text(),request:r.request().postDataJSON()};packets.push(entry);console.log('API ERROR',JSON.stringify(entry));}});
const held=new Set();async function keys(want){for(const k of [...held])if(!want.includes(k)){await page.keyboard.up(k);held.delete(k);}for(const k of want)if(!held.has(k)){await page.keyboard.down(k);held.add(k);}}
const snap=()=>page.evaluate(()=>{const R=__MW.state.R;return{...__MW.getSnapshot(),siteState:R.site?{i:R.site.i,mode:R.site.mg?.mode}:null,atB:R.arrivedB,rank:__MW.routeTracking()};});
let lastRepair=0;
async function drive(points){let i=0,start=Date.now(),lastPrint=0;while(i<points.length){const s=await snap();if(s.over){if(s.outcome==='success'){await keys([]);return;}throw Error('Ended '+s.outcome+' '+s.cause);}assert.equal(s.autopilot,false);assert.equal(s.speed,1);assert.equal(s.rank.unranked,false,s.rank.note);if(Date.now()-start>180000)throw Error('Drive timeout');if(s.paused){await keys([]);await page.locator('#btnDrive').click();await page.waitForTimeout(150);continue;}if(s.cut){await keys([]);await page.keyboard.press('Escape');continue;}if((s.wheel||s.hull||s.leak||s.stuck)&&Date.now()-lastRepair>2000){await page.keyboard.press('f');lastRepair=Date.now();}const p=points[i],dx=p.x-s.x,dy=p.y-s.y,d=Math.hypot(dx,dy);if(d<5){i++;continue;}const want=[];if(Math.abs(dx)>2)want.push(dx>0?'d':'a');if(Math.abs(dy)>2)want.push(dy>0?'w':'s');await keys(want);if(Date.now()-lastPrint>10000){console.log('drive',i,Math.round(s.s),Math.round(d),s.storm,s.rank.attempt?.sequence);lastPrint=Date.now();}await page.waitForTimeout(120);}await keys([]);await page.waitForTimeout(300);}
try{
 await page.goto(base+'/game.html?plan='+mission.id+'&cand=0&mute=1&skip=1&view=2d&seed=368934532');await page.waitForFunction(()=>window.__MW?.getSnapshot().screen==='brief');await page.locator('#bLaunch').click();await page.waitForFunction(()=>!__MW.getSnapshot().paused);
 const path=await page.evaluate(()=>{const W=__MW.state.W;return W.C.route.points.map(p=>({x:W.toX(p.lon),y:W.toY(p.lat)}));});console.log('route',mission.id,path);
 await drive(path.slice(1));await page.waitForTimeout(700);let s=await snap();assert.equal(s.rank.attempt.visited_destination,true);console.log('Reached B',s.rank.attempt.sequence);
 const spot=await page.evaluate(()=>{const W=__MW.state.W;return W.spots.reduce((a,b)=>Math.hypot(a.x-W.B.x,a.y-W.B.y)<Math.hypot(b.x-W.B.x,b.y-W.B.y)?a:b);});await drive([spot]);await page.keyboard.press('e');await page.waitForFunction(()=>!!__MW.state.R.site);const beforeSite=await snap();
 const siteStart=Date.now();while(!(await snap()).over){
   s=await snap();if(Date.now()-siteStart>90000)throw Error('Sample timeout');
   if(s.siteState?.mode==='hold')await keys(['e']);else{await keys([]);if(s.siteState?.mode)await page.keyboard.press('e');}
   await page.waitForTimeout(150);
 }
 await keys([]);await page.waitForFunction(()=>__MW.getSnapshot().screen==='end');
 await page.waitForFunction(()=>__MW.state.R.routeFinalConfirmed===true,{},{timeout:20000});
 s=await snap();assert.equal(s.samples,1);assert.equal(s.spots,1);assert.equal(s.phase,'site');
 assert.equal(s.rank.attempt.objective_complete,true);
 assert.equal(s.rank.attempt.metrics.simulated_time_s,s.rank.attempt.metrics.one_way_time_s);
 for(const key of ['total-time','driving-time','player-model-time','reference-model-time'])assert.notEqual(await page.locator('#missionResultsSummary [data-result="'+key+'"]').textContent(),'Unavailable');
 await page.waitForFunction(()=>__MW.state.R.aiComparison?.status==='complete');
 const comparisons=await page.evaluate(()=>__MW.state.R.aiComparison);
 assert.equal(comparisons.own.status,'complete');assert.equal(comparisons.reference.status,'complete');
 const times=await page.evaluate(()=>({elapsed:__MW.state.R.elapsedS,drive:__MW.state.R.drivingElapsedS,energy:__MW.state.R.energyUsedWh}));
 assert.ok(comparisons.own.seconds<=times.drive,'AI completes the same route faster than this keyboard run');
 assert.ok(times.elapsed>times.drive);assert.ok(times.energy>0);
 console.log('Objective sampled at B',JSON.stringify({...times,ai:comparisons}));
 s=await snap();assert.equal(s.outcome,'success');assert.equal(s.rank.attempt.status,'active','completion must not submit automatically');assert.equal(await page.locator('#submitRouteScore').isVisible(),true);await page.screenshot({path:'game_state/single-site-audit/keyboard-complete-before-submit.png'});
 assert.equal(await page.evaluate(()=>localStorage.getItem('marswalk.game.player')),null,'No callsign was needed before playing');
 await page.locator('#submitRouteScore').click();await page.locator('#routeCallsign').fill(callsign);
 await page.locator('#routeJoinForm').screenshot({path:'game_state/single-site-audit/callsign-form.png'});
 await page.setViewportSize({width:390,height:844});
 const inputBox=await page.locator('#routeCallsign').boundingBox(),submitBox=await page.locator('#submitRouteScore').boundingBox();
 assert.ok(inputBox.width>=200&&inputBox.x>=0&&inputBox.x+inputBox.width<=390,'Callsign stays readable on a phone');
 assert.ok(submitBox.x>=0&&submitBox.x+submitBox.width<=390,'Join button fits a phone');
 await page.locator('#routeJoinForm').screenshot({path:'game_state/single-site-audit/callsign-form-phone.png'});
 await page.setViewportSize({width:1280,height:900});
 // A taken name must keep the completed result available for a new callsign.
 await context.request.post(base+'/api/game/players',{data:{name:callsign}});
 await page.locator('#submitRouteScore').click();await page.waitForFunction(()=>__MW.state.R.routeReceiptError?.includes('taken'));
 const submittedName=callsign+'X';await page.locator('#routeCallsign').fill(submittedName);await page.locator('#submitRouteScore').click();
 await page.waitForFunction(()=>__MW.routeTracking().attempt?.status==='finished',{},{timeout:20000});s=await snap();assert.ok(s.rank.attempt.rank);
 assert.equal(s.rank.attempt.ai_drive_ticks,comparisons.own.ticks);
 const board=await(await context.request.get(base+'/api/game/route-leaderboard?key='+s.rank.attempt.key)).json();
 const entry=board.board.find(row=>row.name===submittedName);assert.ok(entry);assert.equal(entry.ai_drive_ticks,comparisons.own.ticks);assert.ok(Math.abs(entry.ai_driving_time_s-comparisons.own.seconds)<.000001);
 await page.getByRole('button',{name:'View leaderboard',exact:true}).click();await page.getByRole('cell',{name:submittedName,exact:true}).waitFor();
 assert.ok((await page.locator('#routeBoardContent').textContent()).includes('AI driving time'));await page.locator('#boardClose').click();
 assert.deepEqual(errors,[]);assert.deepEqual(packets,[]);console.log('PASS guest keyboard run, post-objective callsign, taken-name retry, AI-time ranking and visible leaderboard',JSON.stringify({name:submittedName,rank:s.rank.attempt.rank,ai:entry.ai_driving_time_s,active:s.rank.attempt.active_drive_s}));await page.screenshot({path:'game_state/single-site-audit/keyboard-complete-ranked.png'});
}catch(e){await fs.writeFile('game_state/single-site-audit/keyboard-failure.json',JSON.stringify({error:e.message,state:await snap(),errors,packets},null,2));await page.screenshot({path:'game_state/single-site-audit/keyboard-failure.png'});throw e;}finally{await browser.close();}
