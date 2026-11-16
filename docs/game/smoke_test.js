// Headless smoke test for frontend/game.html: autopilot must finish every baked mission and route
// with no console errors and no NaN meters.
//
//   npm i puppeteer-core            (anywhere; or set PUPPETEER_CORE to its folder)
//   node docs/game/smoke_test.js http://127.0.0.1:8000          served (online mode)
//   node docs/game/smoke_test.js file:///C:/path/to/frontend    opened as a file (offline mode)
//
// CHROME sets the browser path (default: Chrome on Windows). Exits 1 on any failure.
const puppeteer = require(process.env.PUPPETEER_CORE || 'puppeteer-core');
const base = (process.argv[2] || 'http://127.0.0.1:8000').replace(/\/$/, '') + '/game.html';
const exe = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({ executablePath: exe, headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  let fails = 0, total = 0;
  const probe = await browser.newPage();
  await probe.goto(base + '?skip=1&mute=1', { waitUntil: 'load' });
  const counts = await probe.evaluate(() => window.__MW.state.baked.map((n) => n.cands.length));
  await probe.close();
  for (let m = 0; m < counts.length; m++) for (let c = 0; c < counts[m]; c++) {
    const page = await browser.newPage(); const errs = [];
    await page.setViewport({ width: 1280, height: 800 });
    page.on('console', (x) => { if (x.type() === 'error' || x.type() === 'warning') errs.push(x.text()); });
    page.on('pageerror', (e) => errs.push(String(e.message)));
    await page.goto(base + `?baked=${m}&cand=${c}&autopilot=1&skip=1&speed=40&mute=1`, { waitUntil: 'load' });
    const t0 = Date.now(); let s, nan = false;
    for (;;) {
      s = await page.evaluate(() => window.__MW.getSnapshot());
      if (s.nan) nan = true;
      if (s.over || s.screen === 'end' || Date.now() - t0 > 120000) break;
      await sleep(200);
    }
    const ok = s.outcome === 'success' && !nan && !errs.length;
    total++; if (!ok) fails++;
    console.log(`${ok ? 'PASS' : 'FAIL'} mission ${m} route ${c + 1} ${s.mission.vehicle} "${s.mission.goal}" -> ${s.outcome || 'timeout'}${s.cause ? '/' + s.cause : ''} score ${s.score} ${s.grade || ''}${errs.length ? ' errors: ' + errs.slice(0, 3).join(' | ') : ''}`);
    await page.close();
  }
  console.log(`${total - fails}/${total} passed`);
  await browser.close();
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
