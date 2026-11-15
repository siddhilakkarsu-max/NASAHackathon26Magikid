import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import os from 'node:os';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const out = process.env.MARSWALK_AUDIT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'marswalk-audit-'));
await fs.mkdir(out, { recursive: true });
console.log('Audit artifacts: ' + out);
const repo = path.resolve(here, '../..');
const mode = process.env.MARSWALK_SLIDER_MODE || 'live';
const selection = process.env.MARSWALK_SLIDER_SELECTION || 'keyboard';
const revision = process.env.MARSWALK_SLIDER_REVISION;
const runName = mode + (selection ? '-selected' : '') + (revision ? '-before' : '');
assert.ok(!revision || mode === 'fixture', 'Historical source is supported only by the offline fixture');
const html = revision ? execFileSync('git', ['show', revision + ':frontend/index.html'], { cwd: repo, encoding: 'utf8' })
  : await fs.readFile(path.join(repo, 'frontend/index.html'), 'utf8');
const checks = [], errors = [];
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
let page;
async function setup(viewport) {
  const p = await browser.newPage({ viewport });
  p.on('pageerror', e => errors.push(String(e)));
  if (mode === 'fixture') {
    const css = html.match(/<style>([\s\S]*?)<\/style>/)[1];
    const conditions = html.match(/<details id="conditionsPanel"[\s\S]*?<\/details>/)[0];
    await p.setContent(`<style>${css}</style><div id="panel"><input id="budget" value="4" hidden><b id="budgetVal" hidden></b>${conditions}</div><div id="map"></div>`);
    const labels = html.match(/function labels\(\) \{[\s\S]*?(?=\nfunction syncGlobeLighting)/)[0];
    const binding = html.slice(html.indexOf('["hour", "ls", "budget"].forEach'), html.indexOf('["hour", "ls", "vehicle"].forEach'));
    await p.addScriptTag({ content: `const $=id=>document.getElementById(id); const el=(tag,props)=>Object.assign(document.createElement(tag),props); function solForLs(){return null;} function syncGlobeLighting(){}; ${labels}; ${binding}; labels();` });
  } else {
    await p.addInitScript(() => localStorage.setItem('mapManualSeen', '1'));
    await p.goto((process.env.MARSWALK_TEST_URL || 'http://127.0.0.1:8001') + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await p.locator('#startExploring').click();
    await p.locator('#regionsButton').click();
    // Sliders are usable while the camera flies. On narrow screens the open
    // drawer can cover the entire globe, so camera rendering is not UI readiness.
    await p.waitForFunction(() => current && document.querySelector('#globalLayer option[value="map:terrain"]'), null, { timeout: 60000 });
    await p.evaluate(scale => { viewer.resolutionScale = scale; }, Number(process.env.MARSWALK_RENDER_SCALE || 1));
  }
  await p.locator('#conditionsPanel > summary').click();
  await p.locator('#hour').scrollIntoViewIfNeeded();
  if (selection === 'keyboard') {
    await p.locator('#conditionsPanel > p').click();
    await p.keyboard.press('Control+a');
    assert.ok(await p.evaluate(() => getSelection().containsNode(document.getElementById('hour'), true)), 'Native select-all must span the hour range');
  } else if (selection) await p.evaluate(() => {
    const range = document.createRange();
    range.selectNodeContents(document.getElementById('conditionsPanel'));
    getSelection().removeAllRanges();
    getSelection().addRange(range);
  });
  await p.evaluate(() => {
    window.sliderEvents = [];
    for (const type of ['pointerdown','pointermove','pointerup','pointercancel','mousedown','mouseup','input','change','dragstart','dragend']) {
      document.addEventListener(type, e => {
        const id = e.target.id;
        if (!['hour','ls'].includes(id) && !type.startsWith('drag')) return;
        const box = document.getElementById('hour').getBoundingClientRect();
        window.sliderEvents.push({ type, target: id || e.target.tagName, value: e.target.value, x: e.clientX, y: e.clientY,
          buttons: e.buttons, trusted: e.isTrusted, hourTop: box.top, selection: String(getSelection()), defaultPrevented: e.defaultPrevented });
      });
    }
  });
  return p;
}
async function drag(id, fractions, yOffset = 0) {
  await page.locator('#' + id).scrollIntoViewIfNeeded();
  const info = await page.locator('#' + id).evaluate(el => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height, value: +el.value, min: +el.min, max: +el.max };
  });
  const start = (info.value - info.min)/(info.max-info.min), travel = info.width - 15;
  await page.evaluate(() => { window.sliderEvents = []; });
  await page.mouse.move(info.x + 7.5 + travel * start, info.y + info.height/2 + yOffset);
  await page.mouse.down();
  for (const fraction of fractions) {
    await page.mouse.move(info.x + 7.5 + travel * fraction, info.y + info.height/2 + yOffset, { steps: 20 });
  }
  const during = await page.locator('#' + id).inputValue();
  await page.mouse.up();
  const events = await page.evaluate(() => window.sliderEvents);
  const actual = +await page.locator('#' + id).inputValue();
  const expected = info.min + fractions.at(-1) * (info.max-info.min);
  return { id, viewport: page.viewportSize(), yOffset, from: info.value, actual, expected, during: +during,
    inputEvents: events.filter(e => e.type === 'input').length,
    changeEvents: events.filter(e => e.type === 'change').length,
    dragEvents: events.filter(e => e.type.startsWith('drag')),
    cancelEvents: events.filter(e => e.type === 'pointercancel'), events };
}
try {
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 1000, height: 760 }, { width: 700, height: 650 }, { width: 390, height: 844 }]) {
    page = await setup(viewport);
    for (const id of ['hour','ls']) {
      for (const yOffset of [0,-5,5]) {
        const result = await drag(id, [0.48,0.6,0.7,0.9,0.2,yOffset === -5 ? 0.3 : 0.8], yOffset);
        checks.push(result);
        assert.ok(Math.abs(result.actual-result.expected) <= (id === 'hour' ? 0.25 : 0.2), JSON.stringify({ ...result, events: undefined }));
        assert.ok(result.inputEvents > 10, 'Range must follow pointer continuously');
        assert.equal(result.changeEvents, 1, 'One commit on mouse release');
        assert.deepEqual(result.cancelEvents, []);
        assert.ok(result.dragEvents.every(event => event.type === 'dragstart' && event.defaultPrevented), 'Native text dragging must never take over the range gesture');
      }
    }
    await page.getByRole('slider', { name: /Local solar time/i }).focus();
    for (const [key, expected, label] of [['Home',0,'0:00'],['ArrowRight',0.25,'0:15'],['End',24,'24:00'],['ArrowLeft',23.75,'23:45']]) {
      await page.keyboard.press(key);
      assert.equal(+await page.locator('#hour').inputValue(), expected);
      assert.equal(await page.locator('#hourVal').textContent(), label);
    }
    await page.close();
    console.log(`PASS slider gestures and keyboard input at ${viewport.width}×${viewport.height}`);
  }
  console.log(JSON.stringify({ ok: true, mode, selection, pointerDrags: checks.length, keyboardChecks: 16,
    minInputEvents: Math.min(...checks.map(c=>c.inputEvents)), maxInputEvents: Math.max(...checks.map(c=>c.inputEvents)),
    blockedTextDrags: checks.reduce((sum,c)=>sum+c.dragEvents.length,0), pointerCancels: checks.reduce((sum,c)=>sum+c.cancelEvents.length,0), errors }, null, 2));
} catch (error) {
  console.error(error);
  process.exitCode = 1;
  if (page) await page.screenshot({ path: path.join(out, 'time-slider-' + runName + '-failure.png') }).catch(()=>{});
} finally {
  await fs.writeFile(path.join(out, 'time-slider-' + runName + '-results.json'), JSON.stringify({ mode, selection, revision, checks, errors },null,2));
  await browser.close();
}
