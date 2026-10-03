// End-to-end check of the viewer with real MapLibre in Chromium: imports a
// KML and an SC State Plane DXF over Charleston, confirms features render,
// toggles one layer off, deletes another, and fails on any page error.
// Needs network access (MapLibre from unpkg). Usage: node scripts/viewer_smoke.mjs
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';
import { SC_SPCS, lccForward } from '../web/cad/project.js';

const PORT = 8765;
const ft = (lng, lat) => lccForward(lng, lat, SC_SPCS).map((m) => m / 0.3048);
const [x1, y1] = ft(-79.935, 32.775);
const [x2, y2] = ft(-79.925, 32.785);
const dxf = ['0', 'SECTION', '2', 'TABLES', '0', 'TABLE', '2', 'LAYER',
  '0', 'LAYER', '2', 'CL', '70', '0', '0', 'LAYER', '2', 'ROW', '70', '0', '0', 'ENDTAB', '0', 'ENDSEC',
  '0', 'SECTION', '2', 'ENTITIES',
  '0', 'LINE', '8', 'CL', '10', x1, '20', y1, '11', x2, '21', y2,
  '0', 'LINE', '8', 'ROW', '10', x1, '20', y2, '11', x2, '21', y1,
  '0', 'ENDSEC', '0', 'EOF'].join('\n');
const kml = `<kml><Document><name>Test KML</name><Placemark><name>Pin</name>
  <Point><coordinates>-79.93,32.78</coordinates></Point></Placemark></Document></kml>`;

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
  await page.goto(`http://localhost:${PORT}/?cad`);
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

  // Geology layer (USGS SGMC), harvested before this script runs.
  await page.waitForFunction(() => window.scGeo.map.getLayer('geology-fill'), null, { timeout: 30000 });
  await settle();
  const geo = await page.evaluate(() => {
    const { map } = window.scGeo;
    const units = map.queryRenderedFeatures({ layers: ['geology-fill'] });
    const at = (lng, lat) => map.queryRenderedFeatures(map.project([lng, lat]), { layers: ['geology-fill'] })[0]?.properties;
    return {
      rendered: units.length,
      legend: [...document.querySelectorAll('.geo-legend li')].map((li) => li.textContent),
      columbia: at(-81.03, 34.0)?.name,
      greenville: at(-82.4, 34.85)?.name,
      charleston: at(-80.0, 32.85)?.name,
    };
  });
  console.log(JSON.stringify(geo));
  check(geo.rendered > 50, `geology units render (${geo.rendered})`);
  check(geo.legend.length >= 5, `legend lists classes (${geo.legend.join(', ')})`);
  check(Boolean(geo.columbia && geo.greenville && geo.charleston), 'units found at Columbia, Greenville and near Charleston');
  await page.locator('#geo-mode').selectOption('lith');
  await settle();
  await snapshot(page, 'geology-rock-type');
  await page.locator('#geo-mode').selectOption('age');
  await page.evaluate(() => window.scGeo.map.jumpTo({ center: [-79.93, 32.78], zoom: 16 }));
  await settle();
  const naip = await page.evaluate(() => window.scGeo.map.isSourceLoaded('naip'));
  check(naip, 'live NAIP loads at street scale over Charleston');
  await snapshot(page, 'charleston-z16');

  await page.setInputFiles('#cad-file-input', [
    { name: 'plan.dxf', mimeType: 'application/dxf', buffer: Buffer.from(dxf) },
    { name: 'pins.kml', mimeType: 'application/vnd.google-earth.kml+xml', buffer: Buffer.from(kml) },
  ]);
  await page.waitForFunction(() => window.scGeo.cad.store.files.length === 2, null, { timeout: 10000 });
  await page.evaluate(() => window.scGeo.map.jumpTo({ center: [-79.93, 32.78], zoom: 14 }));
  await page.waitForFunction(() => window.scGeo.map.loaded(), null, { timeout: 30000 });

  const rendered = () => page.evaluate(() => {
    const { map, cad } = window.scGeo;
    const out = {};
    for (const f of cad.store.files) {
      for (const l of f.layers) {
        const ids = [`cad-${l.id}-line`, `cad-${l.id}-point`].filter((id) => map.getLayer(id));
        out[`${f.name}:${l.name}`] = ids.length ? map.queryRenderedFeatures({ layers: ids }).length : -1;
      }
    }
    return out;
  });

  let r = await rendered();
  console.log(JSON.stringify(r));
  check(r['plan.dxf:CL'] > 0, 'DXF layer CL renders over Charleston');
  check(r['plan.dxf:ROW'] > 0, 'DXF layer ROW renders over Charleston');
  check(r['pins.kml:Test KML'] > 0, 'KML layer renders');

  await page.getByLabel('Show layer CL', { exact: true }).uncheck();
  await page.locator('[aria-label="Delete layer ROW"]').click();
  await page.waitForTimeout(500);
  r = await rendered();
  console.log(JSON.stringify(r));
  check(r['plan.dxf:CL'] === 0, 'unchecked layer is hidden');
  check(!('plan.dxf:ROW' in r), 'deleted layer is gone');
  check(r['pins.kml:Test KML'] > 0, 'other layers unaffected');
  check(errors.length === 0, `no page errors ${JSON.stringify(errors)}`);
  await snapshot(page, 'cad');
  await browser.close();
} catch (err) {
  console.log(`FAIL ${err.message}`);
  failed = true;
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
