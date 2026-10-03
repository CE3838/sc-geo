import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  OGC_BASE, PARAM_CODES, WATER_PARAMS, bboxArea, bboxContains, buildStations, classifyType, createWaterClient,
  debounce, fetchAllPages, ogcAdapter, qualifierLabels, readingStatus, snapBbox, stationPageUrl, stationsToGeoJSON,
} from '../../web/usgs-water.js';

// Real USGS Water Data OGC API responses (captured 2026-10-03, trimmed; see
// tests/fixtures/web/README.md).
const fixture = (name) => JSON.parse(readFileSync(new URL(`../fixtures/web/${name}.json`, import.meta.url)));
const NOW = Date.parse('2026-10-03T21:00:00Z');
const params = (url) => Object.fromEntries(new URL(url).searchParams);

// --- request builders ----------------------------------------------------------

test('latestUrl asks for the latest water readings in a bbox, last 30 days, trimmed properties', () => {
  const url = ogcAdapter.latestUrl([-80.2, 32.6, -79.8, 33], { limit: 2000 });
  assert.ok(url.startsWith(`${OGC_BASE}/collections/latest-continuous/items?`));
  const p = params(url);
  assert.equal(p.f, 'json');
  assert.equal(p.bbox, '-80.2,32.6,-79.8,33');
  assert.equal(p.limit, '2000');
  assert.equal(p.time, 'P30D');
  assert.deepEqual(p.parameter_code.split(','), PARAM_CODES);
  for (const code of ['00065', '62614', '62615', '00060', '72019', '62610', '62611', '62620', '63160']) {
    assert.ok(PARAM_CODES.includes(code), code);
  }
  assert.deepEqual(p.properties.split(',').sort(),
    ['approval_status', 'monitoring_location_id', 'parameter_code', 'qualifier', 'time', 'unit_of_measure', 'value']);
});

test('latestUrl rounds the bbox and rejects bad boxes', () => {
  assert.equal(params(ogcAdapter.latestUrl([-80.123456789, 32.5, -79.1, 33.000001])).bbox, '-80.12346,32.5,-79.1,33');
  assert.throws(() => ogcAdapter.latestUrl([-79, 32, -80, 33]), RangeError);
  assert.throws(() => ogcAdapter.latestUrl([Number.NaN, 32, -80, 33]), RangeError);
});

test('locationsUrl asks for named stations by id; ids are validated', () => {
  const p = params(ogcAdapter.locationsUrl(['USGS-02169500', 'USGS-343144080184001']));
  assert.equal(p.id, 'USGS-02169500,USGS-343144080184001');
  assert.equal(p.limit, '2');
  assert.match(p.properties, /monitoring_location_name/);
  assert.match(p.properties, /site_type_code/);
  assert.throws(() => ogcAdapter.locationsUrl(['USGS-1&x=2']), RangeError);
});

test('seriesUrl: instantaneous values for 7 and 30 days, daily means for a year', () => {
  const week = ogcAdapter.seriesUrl('USGS-02169500', '00065', '7d');
  assert.ok(week.startsWith(`${OGC_BASE}/collections/continuous/items?`));
  assert.equal(params(week).time, 'P7D');
  assert.equal(params(week).monitoring_location_id, 'USGS-02169500');
  assert.equal(params(week).parameter_code, '00065');
  assert.equal(params(ogcAdapter.seriesUrl('USGS-02169500', '00065', '30d')).time, 'P30D');
  const year = ogcAdapter.seriesUrl('USGS-02169500', '00065', '1y');
  assert.ok(year.startsWith(`${OGC_BASE}/collections/daily/items?`));
  assert.equal(params(year).time, 'P1Y');
  assert.equal(params(year).statistic_id, '00003');
  assert.throws(() => ogcAdapter.seriesUrl('USGS-02169500', '00065', '5y'), RangeError);
  assert.throws(() => ogcAdapter.seriesUrl('USGS-02169500', '9999x', '7d'), RangeError);
});

test('nextUrl follows the API paging link, only on the same host', () => {
  const page = fixture('usgs-latest-page');
  const next = ogcAdapter.nextUrl(page);
  assert.match(next, /^https:\/\/api\.waterdata\.usgs\.gov\/ogcapi\/v1\/collections\/latest-continuous\/items\?cursor=/);
  assert.equal(ogcAdapter.nextUrl(fixture('usgs-latest-continuous')), null);
  assert.equal(ogcAdapter.nextUrl({ links: [{ rel: 'next', href: 'https://evil.example/x' }] }), null);
});

test('fetchAllPages follows next links up to a page limit', async () => {
  const page = fixture('usgs-latest-page');
  const seen = [];
  const fakeFetch = async (url) => {
    seen.push(url);
    const last = seen.length >= 2;
    return { ok: true, json: async () => (last ? { ...page, links: [] } : page) };
  };
  const features = await fetchAllPages('https://api.waterdata.usgs.gov/ogcapi/v1/x', { fetch: fakeFetch, adapter: ogcAdapter });
  assert.equal(seen.length, 2);
  assert.equal(features.length, page.features.length * 2);
  assert.equal(seen[1], ogcAdapter.nextUrl(page));

  seen.length = 0;
  const endless = async (url) => { seen.push(url); return { ok: true, json: async () => page }; };
  await fetchAllPages('https://api.waterdata.usgs.gov/ogcapi/v1/x', { fetch: endless, adapter: ogcAdapter, maxPages: 3 });
  assert.equal(seen.length, 3);

  const failing = async () => ({ ok: false, status: 429 });
  await assert.rejects(fetchAllPages('https://api.waterdata.usgs.gov/ogcapi/v1/x', { fetch: failing, adapter: ogcAdapter }),
    /HTTP 429/);
});

// --- parsing --------------------------------------------------------------------

test('parseLatest: one reading per feature with numbers, times, units and qualifiers', () => {
  const r = ogcAdapter.parseLatest(fixture('usgs-latest-continuous'));
  const gage = r.find((x) => x.id === 'USGS-02169500' && x.param === '00065');
  assert.deepEqual(gage, {
    id: 'USGS-02169500', param: '00065', value: 2.9, unit: 'ft', time: Date.parse('2026-10-03T20:00:00Z'),
    approval: 'Provisional', qualifiers: [], lng: -81.049815011957, lat: 33.9932098458759,
  });
  const equip = r.find((x) => x.id === 'USGS-331022080021801');
  assert.equal(equip.value, null);
  assert.deepEqual(equip.qualifiers, ['EQUIP']);
  const ice = r.find((x) => x.id === 'USGS-15747000');
  assert.deepEqual(ice.qualifiers, ['ICE']);
  assert.equal(ice.unit, 'ft^3/s');
});

test('parseLocations: name, number, site type by id', () => {
  const locs = ogcAdapter.parseLocations(fixture('usgs-monitoring-locations'));
  assert.equal(locs.size, 7);
  assert.deepEqual(locs.get('USGS-02172053'), {
    id: 'USGS-02172053', number: '02172053', name: 'COOPER R AT MOBAY NR N CHARLESTON, SC',
    siteTypeCode: 'ST-TS', siteType: 'Tidal stream', state: 'South Carolina', altitude: -7.28, datum: 'NAVD88',
  });
  assert.equal(locs.get('USGS-02168500').siteTypeCode, 'LK');
  assert.equal(locs.get('USGS-343144080184001').siteTypeCode, 'GW');
});

test('parseSeries: points sorted by time, numbers, qualifiers; daily values are dates', () => {
  const s = ogcAdapter.parseSeries(fixture('usgs-continuous-02169500'));
  assert.equal(s.points.length, 28);
  assert.equal(s.unit, 'ft');
  assert.deepEqual(s.points[0], { t: Date.parse('2026-09-26T21:00:00Z'), v: 3.41, approval: 'Provisional', qualifiers: [] });
  assert.ok(s.points.every((p, i) => i === 0 || p.t > s.points[i - 1].t));

  const d = ogcAdapter.parseSeries(fixture('usgs-daily-02169500'));
  assert.equal(d.points.length, 12);
  // Served out of order; sorted here.
  assert.ok(d.points.every((p, i) => i === 0 || p.t > d.points[i - 1].t));
  assert.ok(d.points.some((p) => p.approval === 'Approved'));
  assert.equal(new Date(d.points[0].t).getUTCHours(), 12, 'a daily value is placed at midday');
});

test('qualifierLabels explains provisional, ice, equipment and other codes', () => {
  assert.deepEqual(qualifierLabels(['ICE']).map((q) => q.text), ['Ice affected']);
  assert.deepEqual(qualifierLabels(['EQUIP', 'ESTIMATED']).map((q) => q.text), ['Equipment malfunction', 'Estimated']);
  assert.deepEqual(qualifierLabels(['Eqp', 'P']).map((q) => q.text), ['Equipment malfunction', 'Provisional'], 'legacy codes');
  assert.deepEqual(qualifierLabels(['MAINT']).map((q) => q.text), ['Maintenance']);
  assert.deepEqual(qualifierLabels(['WEIRD']).map((q) => q.text), ['WEIRD']);
  assert.deepEqual(qualifierLabels(null), []);
});

// --- classification and status ------------------------------------------------------

test('classifyType: site type first, then the parameters measured', () => {
  assert.equal(classifyType('ST', ['00065', '00060']), 'stream');
  assert.equal(classifyType('ST-TS', ['00065']), 'tidal');
  assert.equal(classifyType('ES', ['63160']), 'tidal');
  assert.equal(classifyType('OC-CO', ['00065']), 'tidal');
  assert.equal(classifyType('LK', ['00065']), 'lake');
  assert.equal(classifyType('GW', ['72019']), 'well');
  assert.equal(classifyType('GW-TH', ['62611']), 'well');
  assert.equal(classifyType(null, ['72019']), 'well');
  assert.equal(classifyType(null, ['62615']), 'lake');
  assert.equal(classifyType(undefined, ['62620']), 'tidal');
  assert.equal(classifyType(null, ['00065']), 'stream');
});

test('readingStatus: current within 3 hours, delayed within 3 days, then stale', () => {
  const h = 3600e3;
  assert.equal(readingStatus({ time: NOW - h, value: 1 }, NOW), 'current');
  assert.equal(readingStatus({ time: NOW - 5 * h, value: 1 }, NOW), 'delayed');
  assert.equal(readingStatus({ time: NOW - 4 * 24 * h, value: 1 }, NOW), 'stale');
  assert.equal(readingStatus({ time: NOW - h, value: null, qualifiers: ['EQUIP'] }, NOW), 'issue');
  assert.equal(readingStatus(null, NOW), 'stale');
});

test('buildStations: one station per site, primary reading by type, names and types from metadata', () => {
  const readings = ogcAdapter.parseLatest(fixture('usgs-latest-continuous'));
  const locs = ogcAdapter.parseLocations(fixture('usgs-monitoring-locations'));
  const stations = buildStations(readings, locs, NOW);
  const byId = Object.fromEntries(stations.map((s) => [s.id, s]));
  assert.equal(stations.length, 7);

  const congaree = byId['USGS-02169500'];
  assert.equal(congaree.type, 'stream');
  assert.equal(congaree.name, 'CONGAREE RIVER AT COLUMBIA, SC');
  assert.equal(congaree.number, '02169500');
  assert.equal(congaree.primary.param, '00065');
  assert.deepEqual(congaree.readings.map((r) => r.param), ['00065', '63160', '00060']);
  assert.equal(congaree.status, 'current');

  const cooper = byId['USGS-02172053'];
  assert.equal(cooper.type, 'tidal');
  assert.equal(cooper.primary.param, '63160', 'tidal: water level above NAVD88 first');

  assert.equal(byId['USGS-02168500'].type, 'lake');
  assert.equal(byId['USGS-02168500'].primary.param, '62615');
  assert.equal(byId['USGS-343144080184001'].type, 'well');
  assert.equal(byId['USGS-343144080184001'].primary.param, '72019');
  assert.equal(byId['USGS-331022080021801'].status, 'issue');
  assert.equal(byId['USGS-15747000'].status, 'issue');
});

test('buildStations works without metadata (classified by parameter, named by number)', () => {
  const readings = ogcAdapter.parseLatest(fixture('usgs-latest-continuous'));
  const stations = buildStations(readings, new Map(), NOW);
  const well = stations.find((s) => s.id === 'USGS-343144080184001');
  assert.equal(well.type, 'well');
  assert.equal(well.name, 'USGS 343144080184001');
  assert.equal(well.named, false);
});

test('stationsToGeoJSON: points with type, status and an icon name', () => {
  const stations = buildStations(ogcAdapter.parseLatest(fixture('usgs-latest-continuous')),
    ogcAdapter.parseLocations(fixture('usgs-monitoring-locations')), NOW);
  const fc = stationsToGeoJSON(stations);
  assert.equal(fc.type, 'FeatureCollection');
  const f = fc.features.find((x) => x.properties.id === 'USGS-02168500');
  assert.deepEqual(f.geometry, { type: 'Point', coordinates: [-81.220653287341, 34.0520930228321] });
  assert.equal(f.properties.icon, 'water-lake-current');
});

test('stationPageUrl links to the Water Data for the Nation page', () => {
  assert.equal(stationPageUrl('USGS-02169500'), 'https://waterdata.usgs.gov/monitoring-location/USGS-02169500/');
  assert.throws(() => stationPageUrl('x/../y'), RangeError);
});

test('PARAM_CODES lists every parameter once, levels before discharge', () => {
  assert.deepEqual([...PARAM_CODES].sort(), Object.keys(WATER_PARAMS).sort());
  assert.equal(PARAM_CODES[0], '00065');
  assert.equal(PARAM_CODES.at(-1), '00060');
});

test('every parameter has a label; depth to water is drawn with an inverted axis', () => {
  for (const code of PARAM_CODES) assert.ok(WATER_PARAMS[code].label, code);
  assert.equal(WATER_PARAMS['72019'].invert, true);
  assert.ok(!WATER_PARAMS['00065'].invert);
});

// --- areas, caching, debounce --------------------------------------------------------

test('snapBbox widens a view to whole steps; area and containment', () => {
  assert.deepEqual(snapBbox([-80.3, 32.6, -79.7, 33.05]), [-81, 32, -79, 34]);
  assert.deepEqual(snapBbox([-80.3, 32.6, -79.7, 33.05], 0.5), [-80.5, 32.5, -79.5, 33.5]);
  assert.equal(bboxArea([-81, 32, -79, 34]), 4);
  assert.ok(bboxContains([-81, 32, -79, 34], [-80.5, 32.5, -79.5, 33.5]));
  assert.ok(!bboxContains([-80.5, 32.5, -79.5, 33.5], [-81, 32, -79, 34]));
});

function fakeApi() {
  const calls = [];
  const fetch = async (url) => {
    calls.push(url);
    const u = new URL(url);
    let body;
    if (u.pathname.endsWith('/latest-continuous/items')) body = fixture('usgs-latest-continuous');
    else if (u.pathname.endsWith('/monitoring-locations/items')) body = fixture('usgs-monitoring-locations');
    else if (u.pathname.endsWith('/continuous/items')) body = fixture('usgs-continuous-02169500');
    else if (u.pathname.endsWith('/daily/items')) body = fixture('usgs-daily-02169500');
    return { ok: true, json: async () => structuredClone(body) };
  };
  return { calls, fetch };
}

test('client.loadArea fetches once per area, reuses it inside, and refetches after it expires', async () => {
  const api = fakeApi();
  let now = NOW;
  const client = createWaterClient({ fetch: api.fetch, now: () => now });
  const first = await client.loadArea([-80.3, 32.6, -79.7, 33.05]);
  assert.equal(first.status, 'loaded');
  assert.equal(first.stations.length, 7);
  const kinds = api.calls.map((u) => new URL(u).pathname.split('/').at(-2));
  assert.deepEqual(kinds, ['latest-continuous', 'monitoring-locations']);
  assert.equal(params(api.calls[0]).bbox, '-81,32,-79,34');

  const again = await client.loadArea([-80.1, 32.7, -79.9, 32.9]);
  assert.equal(again.status, 'cached');
  assert.equal(api.calls.length, 2);

  now += 11 * 60e3;
  const later = await client.loadArea([-80.1, 32.7, -79.9, 32.9]);
  assert.equal(later.status, 'loaded');
  assert.equal(api.calls.length, 3, 'names are not fetched again');
});

test('client.loadArea shares a request in flight and refuses views that are too large', async () => {
  const api = fakeApi();
  const client = createWaterClient({ fetch: api.fetch, now: () => NOW, maxArea: 150 });
  const [a, b] = await Promise.all([client.loadArea([-80.3, 32.6, -79.7, 33.05]), client.loadArea([-80.2, 32.7, -79.8, 33])]);
  assert.equal(a.stations.length, b.stations.length);
  assert.equal(api.calls.filter((u) => u.includes('latest-continuous')).length, 1);
  const national = await client.loadArea([-125, 24, -66, 50]);
  assert.equal(national.status, 'too-large');
  assert.equal(api.calls.filter((u) => u.includes('latest-continuous')).length, 1);
});

test('client.loadArea asks for names in chunks', async () => {
  const api = fakeApi();
  const client = createWaterClient({ fetch: api.fetch, now: () => NOW, chunk: 3 });
  await client.loadArea([-80.3, 32.6, -79.7, 33.05]);
  const named = api.calls.filter((u) => u.includes('monitoring-locations'));
  assert.equal(named.length, 3);
  assert.deepEqual(named.map((u) => params(u).id.split(',').length), [3, 3, 1]);
});

test('client.loadArea keeps stations when the names request fails', async () => {
  const api = fakeApi();
  const fetch = async (url) => (url.includes('monitoring-locations') ? { ok: false, status: 503 } : api.fetch(url));
  const client = createWaterClient({ fetch, now: () => NOW });
  const r = await client.loadArea([-80.3, 32.6, -79.7, 33.05]);
  assert.equal(r.stations.length, 7);
  assert.equal(r.stations.find((s) => s.id === 'USGS-02168500').type, 'lake', 'classified by parameter');
});

test('client.series caches per station, parameter and range', async () => {
  const api = fakeApi();
  const client = createWaterClient({ fetch: api.fetch, now: () => NOW });
  const s = await client.series('USGS-02169500', '00065', '7d');
  assert.equal(s.points.length, 28);
  assert.equal(s.retrieved, NOW);
  await client.series('USGS-02169500', '00065', '7d');
  assert.equal(api.calls.length, 1);
  const y = await client.series('USGS-02169500', '00065', '1y');
  assert.equal(y.daily, true);
  assert.equal(api.calls.length, 2);
});

test('debounce runs once after the last call', () => {
  const timers = [];
  const clock = {
    setTimeout: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; },
    clearTimeout: (id) => { if (timers[id]) timers[id].live = false; },
  };
  const seen = [];
  const d = debounce((x) => seen.push(x), 400, clock);
  d(1); d(2); d(3);
  assert.deepEqual(timers.map((t) => t.live), [false, false, true]);
  assert.equal(timers[2].ms, 400);
  timers[2].fn();
  assert.deepEqual(seen, [3]);
});
