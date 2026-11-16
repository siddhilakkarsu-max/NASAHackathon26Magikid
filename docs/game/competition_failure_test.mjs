// Failure-state audit using the existing 2D fallback; the full gameplay audit uses WebGL.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=process.env.COMPETITION_BASE_URL || 'http://127.0.0.1:8012';
const browser=await chromium.launch({executablePath:process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const context=await browser.newContext({viewport:{width:1100,height:850}}),page=await context.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));
const snap=()=>page.evaluate(()=>window.__MW.competition.snapshot());
const wait=fn=>page.waitForFunction(fn,null,{timeout:20000});
try {
  await page.goto(base+'/game.html?mode=competition&view=2d&mute=1');
  await wait(()=>window.__MW?.competition && !document.getElementById('cpGenerate').disabled);
  await page.locator('#cpGenerate').click();await page.locator('#cpPlay').waitFor({state:'visible'});
  await page.locator('#cpPlay').click();await page.locator('#cpMapButton').click();
  await page.locator('#cpConfirmRoute').click();await wait(()=>!!window.__MW.competition.snapshot().evaluation);
  await page.locator('#cpMapStart').click();
  await page.locator('#cpHome').waitFor({state:'visible'});
  await page.locator('#cpCallsign').fill('fail'+Date.now().toString(36));
  await page.getByRole('button',{name:'Claim callsign',exact:true}).click();
  await page.locator('#cpIdentity').getByText('Driving as',{exact:false}).waitFor();
  const planned=await snap();
  await page.locator('#cpPlay').click();assert.deepEqual((await snap()).route,planned.route);
  console.log('PASS: starting without a callsign returns to a usable claim form and preserves the plan');
  await page.locator('#cpMapButton').click();await page.locator('#cpConfirmRoute').click();
  await wait(()=>!!window.__MW.competition.snapshot().evaluation);
  await page.locator('#cpRouteList button').nth(1).click();
  const routeBefore=structuredClone((await snap()).route);
  await page.locator('#cpPointX').fill('-1');await page.locator('#cpMovePoint').click();
  await wait(()=>document.getElementById('cpRouteStatus').textContent.toLowerCase().includes('boundary'));
  assert.deepEqual((await snap()).route,routeBefore);
  console.log('PASS: numeric editor rejects points outside the mission boundary before changing the route');
  await page.locator('#cpMapStart').click();await wait(()=>window.__MW.competition.snapshot().running);
  await page.locator('#cpMapButton').click();await page.waitForTimeout(300);
  let failedRestart=false;
  await page.route('**/api/competition/attempts/*/restart',async route=>{
    if(!failedRestart){failedRestart=true;await route.fulfill({status:503,json:{detail:'Injected restart outage'}});}else await route.continue();
  });
  await page.locator('#cpRouteList button').nth(1).click();
  await page.locator('#cpPointX').fill(String(routeBefore[1][0]+1));await page.locator('#cpMovePoint').click();
  await wait(()=>window.__MW.competition.snapshot().attempt===null);
  await page.waitForTimeout(300);assert.ok(failedRestart);
  await page.locator('#cpConfirmRoute').click();await wait(()=>!!window.__MW.competition.snapshot().evaluation);
  console.log('PASS: a failed attempt-invalidation request can be retried; confirmation is not permanently poisoned');
  // Ignore a late score for an earlier geometry when the user edits in flight.
  let release,requested=false;
  const gate=new Promise(resolve=>release=resolve);
  const evaluatePattern='**/api/competition/missions/*/evaluate';
  const delay=async route=>{requested=true;const response=await route.fetch();await gate;await route.fulfill({response});};
  await page.route(evaluatePattern,delay);
  await page.locator('#cpConfirmRoute').click();
  while(!requested) await page.waitForTimeout(50);
  await page.locator('#cpPointX').fill(String(routeBefore[1][0]+2));await page.locator('#cpMovePoint').click();
  release();await page.waitForTimeout(300);await page.unroute(evaluatePattern,delay);
  assert.equal((await snap()).evaluation,null);assert.ok(await page.locator('#cpMapStart').isDisabled());
  console.log('PASS: late evaluation cannot confirm an edited route');
  await page.locator('#cpConfirmRoute').click();await wait(()=>!!window.__MW.competition.snapshot().evaluation);
  await page.locator('#cpMapStart').click();await wait(()=>window.__MW.competition.snapshot().running);
  await page.locator('#cpMapButton').click();await page.waitForTimeout(300);
  // Model another tab invalidating this attempt through the real authorized API.
  await page.evaluate(async()=>{const a=window.__MW.competition.snapshot().attempt,p=JSON.parse(localStorage.getItem('marswalk.game.player'));
    const r=await fetch('/api/competition/attempts/'+a.id+'/restart',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});if(!r.ok)throw Error('test invalidation failed');});
  await page.reload();await wait(()=>window.__MW?.competition && !document.getElementById('cpGenerate').disabled);
  await page.getByRole('button',{name:'Restore paused attempt',exact:true}).click();
  await page.waitForTimeout(500);
  assert.equal((await snap()).running,false);
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('marswalk.competition.attempt'))),null);
  console.log('PASS: an invalidated saved attempt cannot resume or submit');
  assert.deepEqual(errors,[]);
  console.log('PASS: failure and regression audit (6 checks), no uncaught browser errors');
} catch(error) {
  console.error(error);const s=await snap().catch(()=>null);if(s?.evaluation)s.evaluation={metrics:s.evaluation.metrics};console.error(JSON.stringify(s));
  console.error('STATUS',await page.locator('#cpHomeStatus,#cpRouteStatus,#cpHudProgress').allTextContents().catch(()=>[]));
  console.error('BROWSER ERRORS',errors);process.exitCode=1;
} finally {await browser.close();}
