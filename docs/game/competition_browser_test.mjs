// Live-server headless audit. Use an isolated MARSWALK_GAME_STATE_DIR.
// No fabricated terrain, browser score or completion bypass is used.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=process.env.COMPETITION_BASE_URL || 'http://127.0.0.1:8012';
const output=process.env.COMPETITION_ARTIFACTS || 'game_state/competition-browser-audit';
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({viewport:{width:1280,height:900}});
const errors=[],checks=[],failedResponses=[];
const record=s=>{checks.push(s);console.log('PASS: '+s);};
context.on('page',p=>{p.on('pageerror',e=>errors.push(e.message));p.on('response',r=>{if(r.status()>=500)failedResponses.push(r.url()+' '+r.status());});});
const page=await context.newPage();
const state=()=>page.evaluate(()=>window.__MW.competition.snapshot());
const wait=fn=>page.waitForFunction(fn,null,{timeout:30000});
try {
  await page.goto(base+'/game.html?mode=competition&mute=1');
  await wait(()=>window.__MW?.competition && !document.getElementById('cpGenerate').disabled);
  assert.equal((await state()).grid_resolution_m,20);
  await page.locator('#cpCallsign').fill('audit'+Date.now().toString(36));
  await page.getByRole('button',{name:'Claim callsign',exact:true}).click();
  await page.locator('#cpIdentity').getByText('Driving as',{exact:false}).waitFor();
  await page.locator('#cpGenerate').click();
  await page.locator('#cpPlay').waitFor({state:'visible'});
  const generated=await state(), reference=generated.reference;
  assert.ok(reference.length>=3);
  await page.locator('#cpPlay').click();
  await page.locator('#cpMapButton').click();
  await page.locator('#cpMapDialog').waitFor({state:'visible'});
  const initial=await state();
  for(const layer of ['elevation','slope','material','terrain']) {
    await page.locator('#cpLayers [data-layer="'+layer+'"]').click();
    assert.equal((await state()).layer,layer);
    assert.deepEqual((await state()).route,initial.route);
    assert.ok((await page.locator('#cpSource').textContent()).includes('Source:'));
  }
  record('Live measured terrain loads; all layers have sources and preserve the route');
  // The keyboard/numeric editor is also useful when map handles overlap.
  await page.locator('#cpRouteList button').nth(1).click();
  const x=Number(await page.locator('#cpPointX').inputValue());
  await page.locator('#cpPointX').fill(String(x+2));
  await page.locator('#cpMovePoint').click();
  assert.notDeepEqual((await state()).route,initial.route);
  assert.deepEqual((await state()).reference,reference);
  const edited=await state();
  await page.locator('#cpLayers [data-layer="slope"]').click();
  assert.deepEqual((await state()).route,edited.route);
  await page.locator('#cpRemovePoint').click();
  assert.equal((await state()).route.length,edited.route.length-1);
  const removedLength=(await state()).route.length;
  await page.locator('#cpAddPoint').click();
  assert.equal((await state()).route.length,removedLength+1);
  await page.locator('#cpResetRoute').click();
  assert.deepEqual((await state()).route,reference);
  record('Add/move/remove/reset work and the original AI reference remains immutable');
  await page.locator('#cpConfirmRoute').click();
  await wait(()=>!!window.__MW.competition.snapshot().evaluation);
  const score=(await state()).evaluation.metrics;
  assert.ok(score.simulated_time_s>0 && score.energy_wh>0);
  // A whole-route invalidation must be visible and cannot leave Start enabled.
  await page.evaluate(()=>{const c=window.__MW.competition,s=c.snapshot();c.setRoute([s.route[0],[-1,2500],s.route.at(-1)]);});
  await page.locator('#cpConfirmRoute').click();
  await wait(()=>document.getElementById('cpRouteStatus').textContent.includes('crosses the boundary'));
  assert.ok(await page.locator('#cpMapStart').isDisabled());
  await page.locator('#cpResetRoute').click();await page.locator('#cpConfirmRoute').click();
  await wait(()=>!!window.__MW.competition.snapshot().evaluation);
  assert.deepEqual((await state()).evaluation.metrics,score);
  record('Invalid boundary route is rejected; reconfirmed geometry has identical deterministic score');
  await page.screenshot({path:path.join(output,'map.png')});
  await page.locator('#cpMapStart').click();
  await wait(()=>window.__MW.competition.snapshot().running);
  await page.locator('#cpAssistButton').click();
  await wait(()=>window.__MW.competition.snapshot().attempt?.sequence>=3);
  // Lose one acknowledgement after the real server accepts it. Recovery must
  // restore its sequence/position rather than inventing a successful heartbeat.
  const progressPattern='**/api/competition/attempts/*/progress';
  let dropped=false;
  const dropAck=async route=>{
    if(!dropped && route.request().postDataJSON()?.mode==='driving') {
      dropped=true;await route.fetch();await route.abort('failed');
    } else await route.continue();
  };
  await page.route(progressPattern,dropAck);
  await wait(()=>!window.__MW.competition.snapshot().running);
  await page.unroute(progressPattern,dropAck);
  await page.waitForTimeout(500);
  assert.ok(dropped);
  await page.locator('#cpDriveButton').click();await wait(()=>window.__MW.competition.snapshot().running);
  record('A lost progress acknowledgement pauses and recovers authoritative sequence/position');
  await page.locator('#cpMapButton').click();
  await wait(()=>!window.__MW.competition.snapshot().running);
  await page.waitForTimeout(800);
  const paused=await state();
  await page.waitForTimeout(800);
  const still=await state();
  assert.equal(still.attempt.active_drive_s,paused.attempt.active_drive_s);
  assert.deepEqual(still.position,paused.position);
  record('Opening the editor pauses motion and server active-driving time');
  const oldAttempt=still.attempt.id;
  await page.locator('#cpRouteList button').nth(1).click();
  await page.locator('#cpPointX').fill(String(Number(await page.locator('#cpPointX').inputValue())+1));
  await page.locator('#cpMovePoint').click();
  await wait(()=>window.__MW.competition.snapshot().attempt===null);
  await page.locator('#cpResetRoute').click();await page.locator('#cpConfirmRoute').click();
  await wait(()=>!!window.__MW.competition.snapshot().evaluation);
  await page.locator('#cpMapStart').click();await wait(()=>window.__MW.competition.snapshot().running);
  assert.notEqual((await state()).attempt.id,oldAttempt);
  record('Editing during an attempt retires it and starts a new immutable attempt');
  await page.waitForTimeout(1000);
  await page.reload();
  await wait(()=>window.__MW?.competition && !document.getElementById('cpGenerate').disabled);
  await page.getByRole('button',{name:'Restore paused attempt',exact:true}).click();
  await wait(()=>!!window.__MW.competition.snapshot().attempt);
  assert.equal((await state()).running,false);
  assert.equal((await state()).paused,true);
  record('Refresh restores server-owned progress paused, without offline driving credit');
  await page.locator('#cpDriveButton').click();await wait(()=>window.__MW.competition.snapshot().running);
  await page.locator('#cpAssistButton').click();
  // Regression: a failed final pause must not poison future submission retries.
  let rejectedFinalPause=false;
  await page.route(progressPattern,async route=>{
    if(route.request().postDataJSON()?.mode==='paused' && (await state()).attempt?.completed && !rejectedFinalPause) {
      rejectedFinalPause=true;
      await route.fulfill({status:400,json:{detail:'Injected final pause rejection (audit fixture)'}});
    } else await route.continue();
  });
  await page.screenshot({path:path.join(output,'rover.png')});
  // Real wall-clock driving through the normal assist control. No time mock.
  await page.waitForFunction(()=>!document.getElementById('cpResult').hidden,null,{timeout:180000});
  assert.ok(rejectedFinalPause,'the final-pause failure regression was exercised');
  const beforeSubmit=await state();
  assert.equal(beforeSubmit.attempt.completed,true);
  assert.equal(beforeSubmit.attempt.status,'active');
  for(const label of ['Reference simulated time','Your simulated route time','Actual active driving','Time difference'])
    assert.ok((await page.locator('#cpResultBody').textContent()).includes(label),label);
  const boardBefore=await page.evaluate(()=>window.__MW.competition.leaderboard());
  assert.ok(!boardBefore.board.some(r=>r.attempt_id===beforeSubmit.attempt.id));
  await page.locator('#cpSubmit').click();
  await wait(()=>window.__MW.competition.snapshot().attempt?.status==='finished');
  await page.locator('#cpLeaderboard').click();
  const board=await page.evaluate(()=>window.__MW.competition.leaderboard());
  const entry=board.board.find(r=>r.attempt_id===beforeSubmit.attempt.id);
  assert.ok(entry);assert.equal(entry.simulated_time_s,score.simulated_time_s);
  assert.ok(entry.active_drive_s>0 && entry.active_drive_s<score.simulated_time_s);
  await page.evaluate(()=>window.__MW.competition.finish());
  const boardTwice=await page.evaluate(()=>window.__MW.competition.leaderboard());
  assert.equal(boardTwice.players,board.players);
  record('Real drive reaches every objective; three times shown; explicit submission persists and repeated submission is idempotent');
  await page.screenshot({path:path.join(output,'results.png')});
  // A missing-data response is exercised separately from the real-data run.
  const failure=await context.newPage();
  await failure.route('**/api/competition/config',route=>route.fulfill({status:503,json:{detail:'Verified terrain unavailable (audit fixture)'}}));
  await failure.goto(base+'/game.html?mode=competition&mute=1');
  await failure.waitForFunction(()=>document.getElementById('cpHomeStatus').textContent.includes('Competition unavailable'));
  assert.ok(await failure.locator('#cpGenerate').isDisabled());
  record('Unavailable verified data disables competition with an explicit explanation');
  await failure.close();
  assert.deepEqual(errors,[],'uncaught browser errors');
  const unexpected=failedResponses.filter(s=>!s.endsWith('/api/competition/config 503'));
  assert.deepEqual(unexpected,[],'unexpected server failures');
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify({base,checks,errors,score,entry,generatedAt:new Date().toISOString()},null,2));
  console.log('PASS: complete gameplay and failure audit ('+checks.length+' checks)');
} catch(error) {
  console.error('AUDIT FAILURE:',error);
  const s=await state().catch(()=>null);if(s?.evaluation)s.evaluation={metrics:s.evaluation.metrics};
  console.error('STATE:',JSON.stringify(s));
  console.error('STATUS:',await page.locator('#cpHudProgress, #cpRouteStatus, #cpResultStatus').allTextContents().catch(()=>[]));
  console.error('BROWSER ERRORS:',errors);
  await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  process.exitCode=1;
} finally { await browser.close(); }
