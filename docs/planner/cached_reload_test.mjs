// A real HTTP-cache regression. No Playwright routes: routing disables cache.
// The fixture primes the lighting module published at ae5c0d1, then serves the
// current app from the same origin while that older script remains fresh.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001';
const out = process.env.MARSWALK_AUDIT_DIR || path.resolve('cache-audit');
const reproduce = process.env.MARSWALK_REPRODUCE_CACHE === '1';
await fs.mkdir(out, { recursive:true });
const oldLighting = await fs.readFile(new URL('../../tests/fixtures/mars_lighting_pre_overview.js', import.meta.url));
const lightingRequests = [], browserResponses = [], checks = [], errors = [];
let priming = true;
const proxy = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://fixture');
    if (url.pathname === '/cache-seed') {
      res.writeHead(200, {'Content-Type':'text/html', 'Cache-Control':'no-store'});
      res.end('<script src="/mars_lighting.js"></script><title>Legacy cache fixture</title>'); return;
    }
    if (url.pathname === '/mars_lighting.js') {
      lightingRequests.push({ url:req.url, priming });
      if (priming) {
        res.writeHead(200, {'Content-Type':'text/javascript', 'Cache-Control':'public, max-age=86400'});
        res.end(oldLighting); return;
      }
    }
    const body = []; for await (const chunk of req) body.push(chunk);
    const headers = { ...req.headers }; delete headers.host; delete headers.connection;
    // Node fetch decompresses; omit encoding so Content-Length still matches.
    headers['accept-encoding'] = 'identity';
    const response = await fetch(base + req.url, { method:req.method, headers,
      body:body.length ? Buffer.concat(body) : undefined });
    const forwarded = Object.fromEntries(response.headers);
    delete forwarded['transfer-encoding']; delete forwarded['content-encoding'];
    res.writeHead(response.status, forwarded);
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) { if (!res.headersSent) res.writeHead(502); res.end(String(error)); }
});
await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve));
const url = 'http://127.0.0.1:' + proxy.address().port;
const browser = await chromium.launch({ executablePath:process.env.CHROME || undefined, headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport:{width:1440,height:1000} });
page.setDefaultTimeout(45000);
page.on('pageerror', e => errors.push(String(e)));
const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable');
cdp.on('Network.responseReceived', event => {
  if (event.response.url.includes('/mars_lighting.js')) browserResponses.push({ url:event.response.url,
    fromDiskCache:!!event.response.fromDiskCache, status:event.response.status });
});
const pass = name => { checks.push(name); console.log('PASS ' + name); };
let failure;
try {
  await page.addInitScript(() => localStorage.setItem('mapManualSeen','1'));
  await page.goto(url + '/cache-seed', {waitUntil:'load'});
  assert.equal(await page.evaluate(() => typeof createMarsLighting), 'function');
  assert.equal(lightingRequests.length, 1); priming = false;
  await page.goto(url + '/?audit=cached-upgrade', {waitUntil:'domcontentloaded'});
  await page.evaluate(() => {
    viewer.resolutionScale=.5; window.cacheRenderErrors=[];
    viewer.scene.renderError.addEventListener((_,e)=>cacheRenderErrors.push(String(e)));
  });
  await page.locator('#startExploring').click();
  if (reproduce) {
    await page.waitForFunction(() => !viewer.useDefaultRenderLoop);
    const renderErrors = [...errors, ...await page.evaluate(() => cacheRenderErrors)];
    assert(renderErrors.some(e=>e.includes('lighting.updateFromPosition is not a function') || e.includes('lighting.clearEphemeris is not a function')));
    assert.equal(lightingRequests.length, 1, 'Old module must come from the real browser cache');
    pass('Reproduced the renderer crash using the older lighting module from the browser HTTP cache');
    await page.screenshot({path:path.join(out,'cached-upgrade-before.png')});
  } else {
    await page.waitForFunction(() => marsOverview.state().mode === 'playing' && !marsOverview.state().framePending);
    assert(lightingRequests.some(r=>!r.priming && /\?v=[a-f0-9]+/.test(r.url)));
    assert.equal(await page.evaluate(() => typeof globeLighting.updateFromPosition),'function');
    assert.deepEqual(await page.evaluate(() => cacheRenderErrors),[]);
    pass('A browser with the older cached lighting module loads the content-versioned current module');
    await page.locator('#overviewToggle').click();
    await page.screenshot({path:path.join(out,'cached-upgrade-after.png')});
    for (let i=0;i<3;i++) {
      await page.reload({waitUntil:'domcontentloaded'});
      await page.evaluate(() => { viewer.resolutionScale=.5; window.cacheRenderErrors=[];
        viewer.scene.renderError.addEventListener((_,e)=>cacheRenderErrors.push(String(e))); });
      await page.locator('#startExploring').click();
      await page.waitForFunction(() => marsOverview.state().mode === 'playing' && !marsOverview.state().framePending);
      await page.locator('#overviewToggle').click();
      assert.deepEqual(await page.evaluate(() => cacheRenderErrors),[]);
      assert(await page.evaluate(() => viewer.useDefaultRenderLoop));
      pass(`Cached reload ${i+1}: overview starts, pauses and keeps the renderer running`);
    }
    assert.deepEqual(errors,[]);
    // Deliberate partial-deployment fixtures. These are separate from the real
    // HTTP-cache pass above: Playwright routing disables cache in these pages.
    for (const module of ['lighting','moons']) {
      const guarded = await browser.newPage({viewport:{width:1200,height:850},reducedMotion:'reduce'});
      guarded.on('pageerror',e=>errors.push(String(e)));
      await guarded.addInitScript(()=>localStorage.setItem('mapManualSeen','1'));
      const pattern = '**/mars_' + module + '.js*';
      await guarded.route(pattern, async route => {
        let source = oldLighting;
        if(module==='moons') {
          const response=await route.fetch();
          source=await response.text() + '\nconst completeMoonFactory=createMarsMoons; createMarsMoons=(...args)=>{const api=completeMoonFactory(...args); delete api.systemFrame; return api;};';
        }
        await route.fulfill({status:200,contentType:'text/javascript',body:source});
      });
      await guarded.goto(base+'/?audit=missing-'+module,{waitUntil:'domcontentloaded'});
      await guarded.evaluate(()=>{viewer.resolutionScale=.5;window.guardFrames=0;
        viewer.scene.postRender.addEventListener(()=>guardFrames++);});
      await guarded.locator('#startExploring').click();
      await guarded.waitForFunction(()=>typeof marsOverview!=='undefined' && marsOverview.state().mode==='unavailable' && guardFrames>2);
      assert(await guarded.evaluate(()=>viewer.useDefaultRenderLoop));
      assert.match(await guarded.locator('#overviewReadout').textContent(),/refresh/i);
      await guarded.locator('#gmRail button[data-section="globalMaps"]').click();
      await guarded.waitForFunction(()=>document.querySelector('#globalLayer option[value="map:ctx"]'));
      await guarded.locator('#globalLayer').selectOption('map:ctx');
      assert.equal(await guarded.evaluate(()=>plannerLayout.globalChoice()),'map:ctx');
      await guarded.locator('#drawerClose').click();
      await guarded.unroute(pattern);
      await guarded.locator('#overviewToggle').click();
      await guarded.waitForURL(/refresh=/);
      await guarded.locator('#startExploring').click();
      await guarded.waitForFunction(()=>marsOverview.state().mode==='paused' && !marsOverview.state().framePending);
      assert(await guarded.evaluate(()=>viewer.useDefaultRenderLoop));
      assert.deepEqual(errors,[]);
      pass(`Missing ${module} capability leaves a working map and recovers with Refresh animation`);
      await guarded.close();
    }
    const kit = await browser.newPage(); kit.on('pageerror',e=>errors.push(String(e)));
    await kit.goto(base+'/kit.html',{waitUntil:'domcontentloaded'});
    await kit.locator('#sheet .head').waitFor({state:'visible',timeout:45000});
    assert(await kit.evaluate(() => [...document.querySelectorAll('script[src],link[rel="stylesheet"]')]
      .map(node=>new URL(node.src||node.href,location.href)).filter(url=>url.origin===location.origin)
      .every(url=>/^[a-f0-9]{16}$/.test(url.searchParams.get('v')))));
    assert.equal(await kit.locator('#sheet .err').count(),0);
    await kit.close(); pass('Gear page loads its versioned scripts/styles and builds its normal kit');
    const game = await browser.newPage(); game.on('pageerror',e=>errors.push(String(e)));
    await game.goto(base+'/game.html?baked=0&mute=1',{waitUntil:'domcontentloaded'});
    await game.waitForFunction(()=>window.__MW && document.querySelector('#bLaunch'));
    assert.deepEqual(errors,[]); await game.close();
    pass('The standalone game still loads without JavaScript errors');
  }
} catch(error) { failure=String(error.stack||error); }
finally {
  await fs.writeFile(path.join(out,reproduce?'cached-upgrade-before.json':'cached-upgrade-results.json'),
    JSON.stringify({checks,errors,lightingRequests,browserResponses,failure},null,2));
  await browser.close(); proxy.closeAllConnections(); await new Promise(resolve=>proxy.close(resolve));
}
if(failure) throw new Error(failure);
