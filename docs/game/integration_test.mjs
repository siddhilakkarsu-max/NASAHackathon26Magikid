// Browser integration regression checks. See README.md for dependencies and invocation.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const here=path.dirname(fileURLToPath(import.meta.url));
const frontend=process.argv[2] || path.join(here,'../../frontend');
const html=await fs.readFile(path.join(frontend,'game.html'),'utf8');
const launch=await fs.readFile(path.join(frontend,'game-launch.js'),'utf8');
const routeMap=await fs.readFile(path.join(frontend,'game-route-map.js'),'utf8');
const resultsModule=await fs.readFile(path.join(frontend,'game-mission-results.js'),'utf8');
const a=html.indexOf('const BAKED = [')+'const BAKED = ['.length;
const baked=JSON.parse('['+html.slice(a,html.indexOf('\n];',a))+']');
const fixture={...baked[0],request_region:'area_saved'};
const planner=`<!doctype html><title>Launcher test</title><button id="runMission">Plan</button><input id="goal" value="edited draft"><input id="mVehicle" value="buggy"><input id="mPriority" value="science"><input id="region" value="here"><input id="ls" value="20"><input id="hour" value="15"><input id="greenOnly" type="checkbox"><details id="missionResults" open><summary>Mission results</summary><div id="mResult"></div></details><script>let mission=${JSON.stringify(fixture)},selected=2;function regionId(){return 'area_resolved';}</script><script src="game-launch.js" defer></script>`;
const kit='<!doctype html><title>Kit test</title><form id="form"><input id="vehicle" value="astronaut"><input id="ls" value="247.5"><input id="region" value="gale"><div id="goals"></div></form><div id="sheet"><div class="head"><div class="tools"></div></div></div><script src="game-launch.js" defer></script>';
const browser=await chromium.launch({executablePath:process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext();const requests=[],errors=[];
context.on('page',page=>page.on('pageerror',error=>errors.push(error.message)));
const svg=color=>'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="${color}"/></svg>`);
const image=svg('brown'),scienceImage=svg('green');
const gale=structuredClone(baked[0]);
function shiftCoordinates(value) {
  if(!value || typeof value!=='object')return;
  if(typeof value.lat==='number')value.lat-=23;
  if(typeof value.lon==='number')value.lon+=60;
  Object.values(value).forEach(shiftCoordinates);
}
shiftCoordinates(gale);
gale.rect={west:baked[0].rect.west+60,east:baked[0].rect.east+60,south:baked[0].rect.south-23,north:baked[0].rect.north-23};
gale.science_image=scienceImage;gale.offlimits_image='';
gale.tracks=null;
const landing=gale.candidates[0].A;
const imageRect={west:landing.lon-.15,east:landing.lon+.2,south:landing.lat-.17,north:landing.lat+.18};
await context.addInitScript(()=>{
  window.__geoDraws=[];
  const draw=CanvasRenderingContext2D.prototype.drawImage;
  CanvasRenderingContext2D.prototype.drawImage=function(img,...args){
    if(img instanceof HTMLImageElement && img.src.startsWith('data:image/svg+xml,')){
      window.__geoDraws.push({canvas:this.canvas.id,source:img.src,args,width:img.width,height:img.height});
      if(window.__geoDraws.length>200)window.__geoDraws.shift();
    }
    return draw.call(this,img,...args);
  };
});
await context.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());requests.push({path:url.pathname,query:url.searchParams,body:req.postDataJSON()});
  if(url.pathname==='/game.html')return route.fulfill({contentType:'text/html',body:html});
  if(url.pathname==='/game-launch.js')return route.fulfill({contentType:'text/javascript',body:launch});
  if(url.pathname==='/game-route-map.js')return route.fulfill({contentType:'text/javascript',body:routeMap});
  if(url.pathname==='/game-mission-results.js')return route.fulfill({contentType:'text/javascript',body:resultsModule});
  if(url.pathname==='/planner.html')return route.fulfill({contentType:'text/html',body:planner});
  if(url.pathname==='/kit.html')return route.fulfill({contentType:'text/html',body:kit});
  if(url.pathname==='/api/mission/options')return route.fulfill({json:{vehicles:{on_foot:{label:'On foot'}}}});
  if(url.pathname==='/api/mission/stream')return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'result',mission:req.postDataJSON().region==='gale'?gale:baked[0]})+'\n\n'});
  if(url.pathname==='/api/layer/imagery')return route.fulfill({json:{image,rect:req.postDataJSON().region==='gale'?imageRect:baked[0].rect}});
  if(url.pathname==='/api/tracks')return route.fulfill({json:{segments:[]}});
  return route.fulfill({json:{}});
});
try{
 const page=await context.newPage();await page.goto('http://mars.test/planner.html');
 await page.locator('#playMission').waitFor({state:'visible'});
 assert.equal(await page.locator('#gameSection').evaluate(e=>e.open),false,'game section stays collapsed');
 assert.equal(await page.locator('#playMission').textContent(),'Play route #3');
 assert.equal(await page.locator('#playLink').count(),0,'no duplicate link near gear controls');
 const popupPromise=page.waitForEvent('popup');await page.locator('#playMission').click();const game=await popupPromise;
 await game.waitForFunction(()=>window.__MW?.getSnapshot().screen==='brief');
 assert.equal(await game.evaluate(()=>document.body.classList.contains('v3d')),true,'latest default first-person renderer starts');
 assert.equal(await game.evaluate(()=>window.__MW.getSnapshot().cand),2);
 assert.equal(await game.evaluate(()=>window.__MW.state.N.region),'area_saved');
 assert.equal(await game.evaluate(()=>window.__MW.state.N.goal),fixture.settings.goal);
 await game.close();
 await page.evaluate(()=>{selected=1;document.getElementById('mResult').replaceChildren(document.createElement('p'));});
 await page.waitForFunction(()=>document.getElementById('playMission').textContent==='Play route #2');
 await page.evaluate(()=>{document.getElementById('runMission').disabled=true;});
 await page.locator('#gameMissionActions').waitFor({state:'hidden'});assert.equal(await page.locator('#gameOpen').isDisabled(),true);
 await page.evaluate(()=>{mission=null;document.getElementById('runMission').disabled=false;document.getElementById('mResult').replaceChildren();});
 await page.waitForFunction(()=>document.getElementById('gameOpen').textContent==='Browse game missions');
 await page.goto('http://mars.test/kit.html');await page.locator('#playGame').waitFor();
 await page.evaluate(()=>{document.getElementById('sheet').innerHTML='<div class="head"><div class="tools"></div></div>';});
 await page.locator('#playGame').waitFor();assert.equal(await page.locator('#playGame').count(),1);
 const live=await context.newPage();await live.goto('http://mars.test/game.html?goal=olivine&vehicle=on_foot&region=jezero&cand=2&ls=247.5&skip=1&mute=1');
 await live.waitForFunction(()=>window.__MW?.getSnapshot().screen==='brief');
 assert.equal(await live.evaluate(()=>window.__MW.getSnapshot().cand),2,'fallback keeps the selected route');
 assert.equal(requests.find(r=>r.path==='/api/mission/stream').body.ls,247.5,'exact slider season reaches planning API');
 await live.waitForFunction(()=>window.__MW.state.imgs.imagery!==null);
 await live.evaluate(()=>{window.__MW.state.baked[0].region='gale';window.__MW.startBaked(0,0);});
 await live.waitForFunction(()=>window.__MW.state.tracksReal==='gale|on_foot');
 assert.ok(requests.some(r=>r.path==='/api/layer/imagery'&&r.body.region==='gale'),'another region fetches new imagery');
 assert.ok(requests.some(r=>r.path==='/api/tracks'&&r.query.get('region')==='gale'),'another region fetches new tracks');
 assert.equal(await live.evaluate(()=>window.__MW.state.tracksLL.length),0,'empty regional tracks do not reuse Jezero tracks');

 // Pixel/crop alignment below targets the supported 2D fallback. The default
 // game is now first-person WebGL and does not issue these Canvas2D draw calls.
 const geo=await context.newPage();await geo.goto('http://mars.test/game.html?goal=olivine&region=gale&skip=1&mute=1&view=2d');
 await geo.waitForFunction(()=>window.__MW?.state.imgs.imagery && window.__MW.state.imgs.science);
 assert.ok((await geo.locator('#bDos').textContent()).includes('No rover-track survey was supplied for this region.'),'missing regional tracks must not invent Jezero survey totals');
 const brief=await geo.evaluate(([im,science])=>({
   image:window.__geoDraws.filter(d=>d.canvas==='bMap'&&d.source===im).at(-1),
   science:window.__geoDraws.filter(d=>d.canvas==='bMap'&&d.source===science).at(-1),
 }),[image,scienceImage]);
 const close=(got,want,message)=>assert.ok(Math.abs(got-want)<1e-7,`${message}: ${got} vs ${want}`);
 assert.ok(brief.image,'briefing draws georeferenced imagery');
 assert.equal(brief.science,undefined,'briefing keeps the satellite preview clear of science heatmap overlays');
 const center=await geo.locator('#bMap').evaluate(c=>({x:c.width/2,y:c.height/2}));
 const [ix,iy,iw,ih]=brief.image.args, points=gale.candidates[0].route.points;
 close(imageRect.west+(center.x-ix)/iw*(imageRect.east-imageRect.west),
   (Math.min(...points.map(p=>p.lon))+Math.max(...points.map(p=>p.lon)))/2,'briefing imagery is centered on selected route longitude');
 close(imageRect.north-(center.y-iy)/ih*(imageRect.north-imageRect.south),
   (Math.min(...points.map(p=>p.lat))+Math.max(...points.map(p=>p.lat)))/2,'briefing imagery is centered on selected route latitude');
 await geo.locator('#bLaunch').click();
 await geo.evaluate(()=>{window.__geoDraws=[];window.__MW.state.layers.imagery=true;window.__MW.state.layers.science=true;});
 await geo.waitForFunction(([im,science])=>window.__geoDraws.some(d=>d.canvas!=='bMap'&&d.source===im&&d.args.length===8)&&window.__geoDraws.some(d=>d.canvas!=='bMap'&&d.source===science&&d.args.length===8),[image,scienceImage]);
 const play=await geo.evaluate(([im,science])=>({
   image:window.__geoDraws.filter(d=>d.canvas!=='bMap'&&d.source===im&&d.args.length===8).at(-1),
   science:window.__geoDraws.filter(d=>d.canvas!=='bMap'&&d.source===science&&d.args.length===8).at(-1),
   point:{x:innerWidth/2,y:innerHeight/2}
 }),[image,scienceImage]);
 function coordinateAt(draw,rect,pixel){
   const [sx,sy,sw,sh,dx,dy,dw,dh]=draw.args;
   return {lon:rect.west+(sx+(pixel.x-dx)/dw*sw)/draw.width*(rect.east-rect.west),
     lat:rect.north-(sy+(pixel.y-dy)/dh*sh)/draw.height*(rect.north-rect.south)};
 }
 const actual=coordinateAt(play.image,imageRect,play.point),reference=coordinateAt(play.science,gale.rect,play.point);
 close(actual.lon,reference.lon,'gameplay imagery aligns with mission raster longitude');
 close(actual.lat,reference.lat,'gameplay imagery aligns with mission raster latitude');
 await geo.close();await live.close();

 const delayed=await context.newPage();
 await delayed.addInitScript(raw=>{
   const fetch=window.fetch;
   window.fetch=(url,options)=>{
     if(String(url)==='/api/mission/stream'&&JSON.parse(options.body).goal==='delayed plan'){
       // Deliberately ignore AbortSignal: the generation guard must reject a late transport response too.
       return new Promise(resolve=>{window.releaseLatePlan=()=>resolve(new Response('data: '+JSON.stringify({type:'result',mission:raw})+'\n\n',{headers:{'Content-Type':'text/event-stream'}}));});
     }
     return fetch(url,options);
   };
 },baked[0]);
 await delayed.goto('http://mars.test/game.html?goal=delayed%20plan&skip=1&mute=1');
 await delayed.waitForFunction(()=>typeof window.releaseLatePlan==='function');
 await delayed.locator('#quick button').nth(1).click();await delayed.locator('#bLaunch').click();
 const chosen=await delayed.evaluate(()=>window.__MW.getSnapshot().mission.id);
 await delayed.evaluate(async()=>{window.releaseLatePlan();await new Promise(resolve=>setTimeout(resolve,100));});
 assert.equal(await delayed.evaluate(()=>window.__MW.getSnapshot().screen),'play','late plan cannot replace active gameplay');
 assert.equal(await delayed.evaluate(()=>window.__MW.getSnapshot().mission.id),chosen,'late plan cannot change the chosen mission');
 assert.equal(await delayed.locator('#fPlan').isDisabled(),false,'leaving live planning releases its button');
 assert.deepEqual(errors,[]);
 console.log('PASS: compact launch UI, selected-route handoff, planning/clear states, kit rerender, exact season fallback, regional raster alignment, and cancelled-plan isolation');
}finally{await browser.close();}
