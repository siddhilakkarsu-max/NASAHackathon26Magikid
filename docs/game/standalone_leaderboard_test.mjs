// Real standalone game, real sampling UI and API; isolated test database required.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.MARSWALK_TEST_URL||'http://127.0.0.1:8012';
const browser=await chromium.launch({executablePath:process.env.CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/game.html?baked=1&skip=1&mute=1&view=3d');
  await page.waitForFunction(()=>window.__MW?.state.R);
  // Standalone play must receive the same physical envelope as ranked play.
  const calibration=await page.evaluate(()=>{const W=__MW.state.W,value=W.kSpeed;W.kSpeed=100;return value;});
  await page.keyboard.down('w');await page.waitForTimeout(1800);await page.keyboard.up('w');
  const speed=await page.evaluate(()=>__MW.state.R.kmh);
  assert.ok(speed>0&&speed<=13+1e-6,'untracked standalone rover obeys the Apollo-class envelope');
  await page.evaluate(value=>{__MW.state.W.kSpeed=value;},calibration);
  await page.evaluate(()=>__MW.teleport(__MW.state.W.L));
  await page.keyboard.press('e');await page.waitForFunction(()=>!!__MW.state.R.site);
  const until=Date.now()+60000;
  while(!await page.evaluate(()=>__MW.state.R.over)){
    if(Date.now()>until)throw Error('Sampling timed out');
    const mode=await page.evaluate(()=>__MW.state.R.site?.mg?.mode);
    if(mode==='hold')await page.keyboard.down('Space');else{await page.keyboard.up('Space');if(mode)await page.keyboard.press('Space');}
    await page.waitForTimeout(80);
  }
  await page.keyboard.up('Space');
  await page.waitForFunction(()=>__MW.state.R.aiComparison?.status==='complete');
  assert.equal(await page.evaluate(()=>__MW.state.R.outcome),'success');
  assert.equal(await page.locator('#submitRouteScore').textContent(),'Leaderboard');
  assert.equal(await page.locator('#submitRouteScore').isEnabled(),true);
  await page.locator('#submitRouteScore').click();
  const callsign='Solo'+Date.now().toString().slice(-9);
  await page.locator('#routeCallsign').fill(callsign);await page.locator('#submitRouteScore').click();
  await page.waitForFunction(()=>!!__MW.state.R.routeReceipt||!!__MW.state.R.routeReceiptError);
  const result=await page.evaluate(()=>({receipt:__MW.state.R.routeReceipt,error:__MW.state.R.routeReceiptError,ai:__MW.state.R.aiComparison.own}));
  assert.ok(result.receipt,result.error);assert.equal(result.receipt.ai_drive_ticks,result.ai.ticks);
  assert.equal(result.receipt.source,'completed-game');
  const board=await (await page.request.get(base+'/api/game/route-leaderboard?key='+result.receipt.key)).json();
  assert.ok(board.board.some(r=>r.name===callsign&&r.ai_drive_ticks===result.ai.ticks));
  await page.getByRole('button',{name:'View leaderboard',exact:true}).click();
  await page.waitForFunction(name=>document.querySelector('#routeBoardContent').textContent.includes(name),callsign);
  assert.deepEqual(errors,[]);
  console.log('PASS standalone completion → highlighted Leaderboard → callsign → database → visible rank; AI ticks='+result.ai.ticks);
}finally{await browser.close();}
