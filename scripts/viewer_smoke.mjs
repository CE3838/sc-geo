// End-to-end check of the viewer with real MapLibre in Chromium: the layout
// (header, Layers and Map units panels, status bar), the SC focus, imagery,
// merged geology, faults, live roads (SCDOT) and parcels (county services),
// the click callout (State Plane, elevation, road, parcel), the property card
// (confidence, references, soil), USGS water stations and their chart, and
// the add-on popup hook.
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

  // Block bodies that return nothing: jumpTo() returns the map, and
  // Playwright would try to serialize the whole MapLibre object into Node.
  // Move the map and wait until it has drawn the new view (areTilesLoaded()
  // can still be true from the old view right after a jump). Returns nothing,
  // so Playwright never copies the map object into Node.
  const jumpTo = (view) => page.evaluate((v) => new Promise((resolve) => {
    const { map } = window.scGeo;
    const done = () => { clearTimeout(timer); resolve(); };
    const timer = setTimeout(() => { map.off('idle', done); resolve(); }, 20000);
    map.once('idle', done);
    map.jumpTo(v);
  }), view);
  // Screen point (page coordinates) of a lon/lat.
  const screenPoint = (lngLat) => page.evaluate((ll) => {
    const p = window.scGeo.map.project(ll);
    const r = window.scGeo.map.getContainer().getBoundingClientRect();
    return { x: p.x + r.left, y: p.y + r.top };
  }, lngLat);

  // Layout: header, Layers and Map units panels, status bar.
  const layout = await page.evaluate(() => ({
    title: document.querySelector('.app-title')?.textContent,
    sections: [...document.querySelectorAll('.side-section h2')].map((h) => h.textContent),
    status: document.querySelector('.status-bar')?.textContent ?? '',
  }));
  check(layout.title === 'SC Geo Viewer', `header shows the app name (${layout.title})`);
  check(layout.sections.join() === 'Layers,Map units', `left panel has Layers and Map units (${layout.sections})`);
  await page.mouse.move(700, 400);
  const status = await page.locator('.status-bar').textContent();
  check(/N [\d,]+ ft · E [\d,]+ ft/.test(status) && /° N, .*° W/.test(status) && /1:[\d,]+/.test(status),
    `status bar shows State Plane feet, lat/lon and scale (${status.replace(/\s+/g, ' ').trim()})`);

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
      layers: [...document.querySelectorAll('.layer-row label')].map((l) => l.textContent),
    };
  });
  console.log(JSON.stringify(geo));
  check(geo.surficial > 50, `merged surficial units render (${geo.surficial})`);
  check(geo.bedrock > 50, `merged bedrock units render (${geo.bedrock})`);
  check(geo.legend.length >= 5, `legend lists classes (${geo.legend.join(', ')})`);
  check(['Surficial geology', 'Bedrock geology', 'Faults and shear zones', 'Roads and route numbers', 'Parcels',
    'Aerial imagery'].every((n) =>
    geo.layers.some((l) => l.startsWith(n))), `Layers panel lists each layer (${geo.layers.join(', ')})`);

  // Faults (harvest/sgmc.py output) in the Piedmont.
  await page.waitForFunction(() => window.scGeo.map.getLayer('faults-certain'), null, { timeout: 30000 });
  await jumpTo({ center: [-81.4, 34.6], zoom: 8 });
  await settle();
  const faultCount = await page.evaluate(() => window.scGeo.map.queryRenderedFeatures(
    { layers: ['faults-certain', 'faults-approximate', 'faults-concealed'] }).length);
  check(faultCount > 10, `SGMC faults and shear zones render (${faultCount})`);
  await snapshot(page, 'faults');

  await jumpTo({ center: [-79.96, 32.86], zoom: 12 });
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

  // Click callout: coordinates, State Plane, elevation (USGS 3DEP), actions.
  const pt = await screenPoint([-79.96, 32.86]);
  await page.mouse.click(pt.x, pt.y);
  await page.waitForSelector('.maplibregl-popup .callout', { timeout: 5000 });
  await page.waitForFunction(() => !/Loading/.test(document.querySelector('.callout-elev')?.textContent ?? ''), null,
    { timeout: 20000 }).catch(() => {});
  const callout = await page.locator('.maplibregl-popup .callout').textContent();
  console.log(callout);
  check(/Clicked point/.test(callout) && /N [\d,]+ ft · E [\d,]+ ft/.test(callout), 'callout shows the point in State Plane feet');
  check(/ft \(NAVD88\)|Elevation unavailable/.test(callout), 'callout shows ground elevation or says it is unavailable');
  if (!/NAVD88/.test(callout)) console.log('NOTE elevation service did not answer');
  check(await page.locator('.callout button', { hasText: 'Card' }).count() === 1
    && await page.locator('.callout button', { hasText: 'Open Street View' }).count() === 1, 'callout offers Card and Street View');
  await snapshot(page, 'callout');

  // Property card: unit, confidence with its reasons, references, soil.
  await page.locator('.callout button', { hasText: 'Card' }).click();
  await page.waitForSelector('#card:not([hidden]) .card-title', { timeout: 5000 });
  await page.waitForFunction(() => document.querySelectorAll('.card-refs li').length > 1, null, { timeout: 20000 }).catch(() => {});
  await page.waitForFunction(() => !/Loading soil/.test(document.querySelector('.card-soil')?.textContent ?? ''), null,
    { timeout: 30000 }).catch(() => {});
  const cardInfo = await page.evaluate(() => ({
    title: document.querySelector('.card-title')?.textContent,
    badge: document.querySelector('.card-conf .badge')?.textContent ?? '',
    why: document.querySelectorAll('.card-why tr').length,
    rows: document.querySelectorAll('.card-props tr').length,
    refs: document.querySelectorAll('.card-refs li').length,
    soil: document.querySelector('.card-soil')?.textContent ?? '',
  }));
  console.log(JSON.stringify(cardInfo));
  check(Boolean(cardInfo.title), `property card names the unit (${cardInfo.title})`);
  check(/^\d\.\d\d · (High|Medium|Low)$/.test(cardInfo.badge) && cardInfo.why >= 4,
    `card shows a confidence badge and why (${cardInfo.badge})`);
  check(cardInfo.rows >= 2, `card lists cited properties (${cardInfo.rows})`);
  check(cardInfo.refs >= 2, `card lists key references (${cardInfo.refs})`);
  check(/NRCS SSURGO|Soil data unavailable|No soil map unit/.test(cardInfo.soil), 'card shows soil or says it is unavailable');
  if (!/NRCS SSURGO via Soil Data Access/.test(cardInfo.soil)) console.log('NOTE soil service did not answer');
  await snapshot(page, 'card');
  await page.getByRole('button', { name: 'Close card' }).click();
  check(await page.locator('#card').isHidden(), 'card closes');

  await page.locator('#geo-mode').selectOption('confidence');
  await settle();
  await snapshot(page, 'merged-confidence');
  await jumpTo({ center: [-80.9, 33.6], zoom: 6.6 });
  await page.locator('#geo-mode').selectOption('age');
  await settle();
  await snapshot(page, 'merged-state');
  await jumpTo({ center: [-79.93, 32.78], zoom: 16 });
  await settle();
  const naip = await page.evaluate(() => window.scGeo.map.isSourceLoaded('naip'));
  check(naip, 'live NAIP loads at street scale over Charleston');
  await snapshot(page, 'charleston-z16');

  // Roads (SCDOT road inventory, live): highways and interstates at z12.
  // A clean "service unavailable" note is accepted so an outage is not a failure.
  const layerNote = (id) => page.evaluate((i) => document.getElementById(`layer-${i}`)?.closest('li')?.textContent ?? '', id);
  await jumpTo({ center: [-79.96, 32.83], zoom: 12 });
  await page.waitForFunction(() => !/loading/.test(document.getElementById('layer-roads')?.closest('li')?.textContent ?? ''),
    null, { timeout: 45000 }).catch(() => {});
  await settle();
  const roadInfo = await page.evaluate(() => {
    const { map } = window.scGeo;
    const ids = ['roads-state-line', 'roads-hwy-line', 'roads-local-line'].filter((id) => map.getLayer(id));
    const feats = map.queryRenderedFeatures({ layers: ids });
    const shields = ['roads-shields-state', 'roads-shields-hwy'].filter((id) => map.getLayer(id));
    return {
      lines: feats.length,
      classes: [...new Set(feats.map((f) => f.properties.cls))],
      refs: [...new Set(feats.map((f) => f.properties.ref).filter(Boolean))].slice(0, 8),
      shields: map.queryRenderedFeatures({ layers: shields }).length,
    };
  });
  console.log(JSON.stringify(roadInfo));
  const roadNote = await layerNote('roads');
  if (/unavailable/.test(roadNote)) {
    console.log(`NOTE roads service did not answer (${roadNote.trim()})`);
    check(true, 'roads layer reports the SCDOT service as unavailable');
  } else {
    check(roadInfo.lines > 20 && ['interstate', 'us'].every((c) => roadInfo.classes.includes(c)),
      `roads render with interstates and US highways (${roadInfo.lines}; ${roadInfo.refs.join(', ')})`);
    check(roadInfo.shields > 0, `route shields render (${roadInfo.shields})`);
  }
  await snapshot(page, 'roads-z12');

  // Parcels (Charleston County's own service, live) from z15: lines, IDs and a click.
  await jumpTo({ center: [-79.9311, 32.7765], zoom: 17 });
  await page.waitForFunction(() => {
    const t = document.querySelector('.parcel-status')?.textContent ?? '';
    return /Charleston County:/.test(t) && !/loading/.test(document.getElementById('layer-parcels')?.closest('li')?.textContent ?? '');
  }, null, { timeout: 60000 }).catch(() => {});
  await settle();
  const parcelStatus = await page.locator('.parcel-status').textContent();
  const parcelCount = await page.evaluate(() => window.scGeo.map.queryRenderedFeatures({ layers: ['parcels-fill'] }).length);
  console.log(`parcels: ${parcelCount}; ${parcelStatus}`);
  if (parcelCount > 0) {
    check(/Charleston County: [\d,]+ parcels/.test(parcelStatus), `Charleston parcels load (${parcelStatus})`);
    const c = await screenPoint([-79.9311, 32.7765]);
    await page.mouse.click(c.x, c.y);
    await page.waitForSelector('.maplibregl-popup .callout', { timeout: 5000 });
    const parcelCallout = await page.locator('.maplibregl-popup .callout').textContent();
    console.log(parcelCallout);
    const hasParcel = /Parcel ID \(TMS\/PIN\)/.test(parcelCallout);
    if (hasParcel) {
      check(/Charleston County parcel service/.test(parcelCallout), 'parcel callout cites the county service');
      check(!/owner/i.test(parcelCallout), 'parcel callout shows no owner');
    } else {
      console.log('NOTE no parcel under the clicked point');
      check(true, 'parcel click handled');
    }
    await snapshot(page, 'parcels-charleston');
  } else {
    check(/Charleston County: (parcel service unavailable|service blocks|no public)/.test(parcelStatus),
      `Charleston parcels: a clear note when the county service does not answer (${parcelStatus})`);
    console.log('NOTE Charleston County parcel service did not answer');
  }
  const below = await (async () => {
    await jumpTo({ center: [-79.9311, 32.7765], zoom: 13 });
    await page.waitForTimeout(600);
    return page.locator('.parcel-status').textContent();
  })();
  check(/Zoom in to see parcels/.test(below), `parcels panel says to zoom in below z15 (${below})`);
  await page.locator('.maplibregl-popup-close-button').click().catch(() => {});

  // USGS water monitoring stations (web/water-ui.js), live from USGS Water
  // Data; a service outage is a clean "service unavailable", not a failure.
  {
    const waterNote = () => page.evaluate(() =>
      document.getElementById('layer-water')?.closest('.layer-row').querySelector('.layer-note').textContent ?? '');
    const waitWater = () => page.waitForFunction(() => {
      const n = document.getElementById('layer-water')?.closest('.layer-row').querySelector('.layer-note').textContent;
      return n && !/loading/.test(n);
    }, null, { timeout: 60000 }).catch(() => {});
    const stations = () => page.evaluate(() => {
      const { map } = window.scGeo;
      const r = map.getContainer().getBoundingClientRect();
      return map.queryRenderedFeatures({ layers: ['water-stations'] }).map((f) => {
        const p = map.project(f.geometry.coordinates);
        return { id: f.properties.id, type: f.properties.type, x: p.x + r.left, y: p.y + r.top };
      });
    });
    check(await page.locator('#layer-water').count() === 1, 'Layers panel lists Water monitoring (USGS)');
    let unavailable = false;
    for (const [name, center] of [['Columbia', [-81.03, 34.0]], ['Charleston', [-79.95, 32.85]]]) {
      await jumpTo({ center, zoom: 10.5 });
      await page.waitForTimeout(600); // the layer loads 400 ms after the map stops
      await waitWater();
      const note = await waterNote();
      const found = await stations();
      unavailable ||= /unavailable/.test(note);
      check(found.length > 0 || /unavailable/.test(note),
        `water stations around ${name}: ${found.length} (${[...new Set(found.map((s) => s.type))].join(', ')})${note ? `, note "${note.trim()}"` : ''}`);
    }
    if (unavailable) console.log('NOTE USGS Water Data did not answer');
    const target = (await stations()).find((s) => s.x > 420 && s.y > 120);
    if (target) {
      await page.mouse.click(target.x, target.y);
      await page.waitForSelector('.water-panel:not([hidden]) :is(.wc, .water-unavailable, .water-empty)', { timeout: 30000 });
      const chart = await page.evaluate(() => ({
        title: document.querySelector('.water-panel .card-title')?.textContent,
        svg: Boolean(document.querySelector('.water-panel .wc path.wc-line')),
        link: document.querySelector('.water-panel .water-link')?.href ?? '',
        cite: document.querySelector('.water-panel .water-cite')?.textContent ?? '',
        text: document.querySelector('.water-panel .water-chart')?.textContent ?? '',
        callout: document.querySelectorAll('.maplibregl-popup').length,
      }));
      console.log(JSON.stringify(chart));
      check(Boolean(chart.title), `clicking a station opens its chart panel (${chart.title} ${target.id})`);
      check(chart.svg ? /USGS Water Data.*retrieved/.test(chart.cite) : /unavailable|No (daily values|readings)/.test(chart.text),
        `chart drawn with a USGS Water Data citation, or says why not (${chart.svg ? 'chart' : chart.text})`);
      check(chart.link === `https://waterdata.usgs.gov/monitoring-location/${target.id}/`, 'chart links to the station page');
      check(chart.callout === 0, 'a station click opens the chart instead of the callout');
      await snapshot(page, 'water-chart');
      await page.locator('.water-panel .card-close').click();
      check(await page.locator('.water-panel').isHidden(), 'water chart closes');
    } else {
      check(unavailable, 'a station to click (or the service is unavailable)');
    }
  }

  // Add-ons (the desktop app) put their own content in the click popup.
  await page.evaluate(() => {
    window.scGeo.popupItems.push(() => {
      const div = document.createElement('div');
      div.className = 'smoke-item';
      div.textContent = 'add-on item';
      return div;
    });
  });
  await page.mouse.click(600, 400);
  await page.waitForSelector('.maplibregl-popup .smoke-item', { timeout: 5000 });
  check(true, 'add-on popup item shows on click');
  check(await page.locator('.maplibregl-popup .feature-info').count() === 0, 'add-on item takes the place of the geology summary');
  check(await page.locator('#cad-file-input').count() === 0, 'no CAD import on the public site');
  check(errors.length === 0, `no page errors ${JSON.stringify(errors)}`);
  await snapshot(page, 'popup');

  // Phone width: the panels become a drawer and the status bar stays.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  check(await page.locator('#panels-toggle').isVisible(), 'phone width: Layers button in the header');
  await page.locator('#panels-toggle').click();
  await page.waitForTimeout(400);
  const drawer = await page.evaluate(() => document.getElementById('panels').getBoundingClientRect().left);
  check(drawer >= -1, `phone width: Layers drawer opens (${drawer})`);
  check(await page.locator('.status-bar').isVisible(), 'phone width: status bar visible');
  await snapshot(page, 'phone');
  await browser.close();
} catch (err) {
  console.log(`FAIL ${err.message}`);
  failed = true;
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
