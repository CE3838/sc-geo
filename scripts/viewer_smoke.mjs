// End-to-end check of the viewer with real MapLibre in Chromium: the SC
// focus, imagery, merged geology and its popup, and the add-on popup hook.
// Fails on any page error.
// Needs network access (MapLibre from unpkg). Usage: node scripts/viewer_smoke.mjs
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';

const PORT = 8765;

// With SMOKE_LOG_SCREENSHOTS=1, print small JPEG screenshots to the log as
// base64 so they can be inspected without downloading artifacts.
async function snapshot(page, name) {
  await page.screenshot({ path: `viewer-${name}.png` });
  if (process.env.SMOKE_LOG_SCREENSHOTS !== '1') return;
  const jpeg = await page.screenshot({ type: 'jpeg', quality: 60, scale: 'css', clip: { x: 0, y: 0, width: 1200, height: 800 } });
  console.log(`SCREENSHOT ${name} ${jpeg.toString('base64')}`);
}

const server = spawn('python3', ['-m', 'http.server', '-d', 'web', String(PORT)], { stdio: 'ignore' });
let failed = false;
const check = (ok, msg) => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${msg}`);
  if (!ok) failed = true;
};

try {
  await new Promise((r) => setTimeout(r, 1000));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`http://localhost:${PORT}/`);
  await page.waitForFunction(() => window.scGeo?.map.loaded(), null, { timeout: 30000 });

  // Imagery and the South Carolina focus.
  const settle = () => page.waitForFunction(() => window.scGeo.map.areTilesLoaded(), null, { timeout: 60000 });
  await settle();
  const region = await page.evaluate(() => {
    const { map } = window.scGeo;
    return {
      outline: map.queryRenderedFeatures({ layers: ['sc-outline'] }).length,
      mask: map.queryRenderedFeatures({ layers: ['mask'] }).map((f) => f.properties.name),
    };
  });
  check(region.outline > 0, 'South Carolina outline renders');
  check(['Georgia', 'North Carolina'].every((n) => region.mask.includes(n)), `neighbors masked (${[...new Set(region.mask)]})`);
  await snapshot(page, 'state');

  // Merged geology (merge/build.py output), built before this script runs.
  await page.waitForFunction(() => window.scGeo.map.getLayer('merged-surficial-fill'), null, { timeout: 60000 });
  await settle();
  const geo = await page.evaluate(() => {
    const { map } = window.scGeo;
    const count = (id) => map.queryRenderedFeatures({ layers: [id] }).length;
    return {
      surficial: count('merged-surficial-fill'),
      bedrock: count('merged-bedrock-fill'),
      legend: [...document.querySelectorAll('.geo-legend li')].map((li) => li.textContent),
    };
  });
  console.log(JSON.stringify(geo));
  check(geo.surficial > 50, `merged surficial units render (${geo.surficial})`);
  check(geo.bedrock > 50, `merged bedrock units render (${geo.bedrock})`);
  check(geo.legend.length >= 5, `legend lists classes (${geo.legend.join(', ')})`);
  await page.evaluate(() => window.scGeo.map.jumpTo({ center: [-79.96, 32.86], zoom: 12 }));
  await settle();
  const here = await page.evaluate(() => {
    const { map, geology } = window.scGeo;
    const f = geology.unitAt(map.project([-79.96, 32.86]));
    return f && { ...f.properties, text: geology.describe(f).textContent };
  });
  console.log(JSON.stringify(here));
  check(Boolean(here && here.source), 'a merged unit is found in North Charleston');
  check(Boolean(here && /confidence/.test(here.text)), 'popup explains confidence and source');
  await snapshot(page, 'merged-charleston');
  await page.locator('#geo-mode').selectOption('confidence');
  await settle();
  await snapshot(page, 'merged-confidence');
  await page.evaluate(() => window.scGeo.map.jumpTo({ center: [-80.9, 33.6], zoom: 6.6 }));
  await page.locator('#geo-mode').selectOption('age');
  await settle();
  await snapshot(page, 'merged-state');
  await page.evaluate(() => window.scGeo.map.jumpTo({ center: [-79.93, 32.78], zoom: 16 }));
  await settle();
  const naip = await page.evaluate(() => window.scGeo.map.isSourceLoaded('naip'));
  check(naip, 'live NAIP loads at street scale over Charleston');
  await snapshot(page, 'charleston-z16');

  // Add-ons (the desktop app) put their own content in the click popup.
  await page.evaluate(() => window.scGeo.popupItems.push(() => {
    const div = document.createElement('div');
    div.className = 'smoke-item';
    div.textContent = 'add-on item';
    return div;
  }));
  await page.mouse.click(600, 400);
  await page.waitForSelector('.maplibregl-popup .smoke-item', { timeout: 5000 });
  check(true, 'add-on popup item shows on click');
  check(await page.locator('#cad-file-input').count() === 0, 'no CAD import on the public site');
  check(errors.length === 0, `no page errors ${JSON.stringify(errors)}`);
  await snapshot(page, 'popup');
  await browser.close();
} catch (err) {
  console.log(`FAIL ${err.message}`);
  failed = true;
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
