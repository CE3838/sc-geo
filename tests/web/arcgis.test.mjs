import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  LiveTiles, TileCache, debounce, esriToGeoJSON, fetchAllPages, parseQueryResponse, queryUrl, tileBounds, tilesForBounds,
} from '../../web/arcgis.js';

const LAYER = 'https://services.example.test/arcgis/rest/services/Parcels/FeatureServer/0';

test('queryUrl: envelope in lon/lat, outFields, GeoJSON out, paging by resultOffset', () => {
  const url = new URL(queryUrl(LAYER, {
    bbox: [-79.95, 32.77, -79.94, 32.78], outFields: ['PID', 'ACRES'], offset: 2000, count: 1000,
  }));
  assert.equal(url.origin + url.pathname, `${LAYER}/query`);
  const p = Object.fromEntries(url.searchParams);
  assert.equal(p.geometry, '-79.95,32.77,-79.94,32.78');
  assert.equal(p.geometryType, 'esriGeometryEnvelope');
  assert.equal(p.inSR, '4326');
  assert.equal(p.outSR, '4326');
  assert.equal(p.spatialRel, 'esriSpatialRelIntersects');
  assert.equal(p.outFields, 'PID,ACRES');
  assert.equal(p.where, '1=1');
  assert.equal(p.f, 'geojson');
  assert.equal(p.resultOffset, '2000');
  assert.equal(p.resultRecordCount, '1000');
  assert.equal(p.returnGeometry, 'true');
  assert.equal(p.maxAllowableOffset, undefined);
});

test('queryUrl: optional where, generalization, precision, order and esri JSON', () => {
  const url = new URL(queryUrl(`${LAYER}/`, {
    bbox: [-80, 32, -79, 33], where: "ROUTE_TYPE IN ('US','SC')", outFields: ['*'], format: 'json',
    maxAllowableOffset: 0.0005, precision: 5, orderBy: 'OBJECTID',
  }));
  const p = Object.fromEntries(url.searchParams);
  assert.equal(url.pathname.endsWith('/FeatureServer/0/query'), true);
  assert.equal(p.where, "ROUTE_TYPE IN ('US','SC')");
  assert.equal(p.f, 'json');
  assert.equal(p.maxAllowableOffset, '0.0005');
  assert.equal(p.geometryPrecision, '5');
  assert.equal(p.orderByFields, 'OBJECTID');
  assert.equal(p.resultOffset, undefined);
  // Envelope coordinates are trimmed so cache keys and URLs stay stable.
  const u2 = new URL(queryUrl(LAYER, { bbox: [-79.123456789, 32.1, -79.1, 32.2], outFields: ['A'] }));
  assert.equal(u2.searchParams.get('geometry'), '-79.123457,32.1,-79.1,32.2');
});

test('tilesForBounds and tileBounds: slippy tiles covering a lon/lat box', () => {
  const tiles = tilesForBounds([-79.96, 32.77, -79.92, 32.79], 13);
  assert.ok(tiles.length >= 1 && tiles.length <= 4);
  for (const t of tiles) {
    assert.equal(t.z, 13);
    const [w, s, e, n] = tileBounds(t);
    assert.ok(w < e && s < n);
    assert.ok(e > -79.96 && w < -79.92 && n > 32.77 && s < 32.79, 'tile touches the box');
  }
  const [w, s, e, n] = tileBounds({ x: 0, y: 0, z: 0 });
  assert.equal(w, -180);
  assert.equal(e, 180);
  assert.ok(Math.abs(n - 85.0511) < 1e-3 && Math.abs(s + 85.0511) < 1e-3);
  // A whole-state box at z9: a handful of tiles.
  assert.ok(tilesForBounds([-83.36, 32.03, -78.54, 35.22], 9).length < 60);
});

test('parseQueryResponse: GeoJSON, esri JSON, transfer limit and errors', () => {
  const gj = { type: 'FeatureCollection', features: [{ type: 'Feature', id: 1, properties: { A: 1 }, geometry: null }],
    properties: { exceededTransferLimit: true } };
  assert.deepEqual(parseQueryResponse(gj), { features: gj.features, exceeded: true });
  assert.equal(parseQueryResponse({ type: 'FeatureCollection', features: [], exceededTransferLimit: true }).exceeded, true);
  assert.equal(parseQueryResponse({ type: 'FeatureCollection', features: [] }).exceeded, false);
  const esri = { objectIdFieldName: 'OBJECTID', exceededTransferLimit: true, features: [
    { attributes: { OBJECTID: 7, PIN: '123' }, geometry: { rings: [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]] } }] };
  const parsed = parseQueryResponse(esri);
  assert.equal(parsed.exceeded, true);
  assert.equal(parsed.features[0].id, 7);
  assert.equal(parsed.features[0].geometry.type, 'Polygon');
  assert.throws(() => parseQueryResponse({ error: { code: 499, message: 'Token Required' } }), /Token Required/);
  assert.throws(() => parseQueryResponse('nope'), /response/);
});

test('esriToGeoJSON: rings to polygons with holes, multi-part, paths to lines', () => {
  const cw = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]; // clockwise (outer in esri JSON)
  const hole = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]; // counter-clockwise
  const cw2 = [[20, 0], [20, 5], [25, 5], [25, 0], [20, 0]];
  const fc = esriToGeoJSON({ features: [
    { attributes: { FID: 1 }, geometry: { rings: [cw, hole] } },
    { attributes: { FID: 2 }, geometry: { rings: [cw, cw2] } },
    { attributes: { FID: 3 }, geometry: { paths: [[[0, 0], [1, 1]]] } },
    { attributes: { FID: 4 }, geometry: { paths: [[[0, 0], [1, 1]], [[2, 2], [3, 3]]] } },
    { attributes: { FID: 5 } },
  ] }, 'FID');
  const [a, b, c, d, e] = fc.features;
  assert.equal(a.geometry.type, 'Polygon');
  assert.equal(a.geometry.coordinates.length, 2);
  assert.equal(b.geometry.type, 'MultiPolygon');
  assert.equal(b.geometry.coordinates.length, 2);
  assert.equal(c.geometry.type, 'LineString');
  assert.equal(d.geometry.type, 'MultiLineString');
  assert.equal(e.geometry, null);
  assert.deepEqual([a.id, e.id], [1, 5]);
});

test('fetchAllPages: follows exceededTransferLimit by resultOffset, stops at maxPages', async () => {
  const pages = [
    { type: 'FeatureCollection', features: [{ id: 1 }, { id: 2 }], properties: { exceededTransferLimit: true } },
    { type: 'FeatureCollection', features: [{ id: 3 }], properties: {} },
  ];
  const offsets = [];
  const r = await fetchAllPages(async (url) => pages[offsets.length === 1 ? 0 : 1], (offset) => {
    offsets.push(offset);
    return `u?offset=${offset}`;
  }, { pageSize: 2 });
  assert.deepEqual(offsets, [0, 2]);
  assert.deepEqual(r.features.map((f) => f.id), [1, 2, 3]);
  assert.equal(r.truncated, false);

  let calls = 0;
  const endless = await fetchAllPages(async () => { calls += 1; return pages[0]; }, (o) => `u${o}`, { pageSize: 2, maxPages: 3 });
  assert.equal(calls, 3);
  assert.equal(endless.truncated, true);
  assert.equal(endless.features.length, 6);
});

test('TileCache: least recently used entries go first', () => {
  const c = new TileCache(2);
  c.set('a', 1);
  c.set('b', 2);
  assert.equal(c.get('a'), 1); // a is now newest
  c.set('c', 3);
  assert.equal(c.has('b'), false);
  assert.equal(c.has('a'), true);
  assert.equal(c.size, 2);
});

test('debounce: one call after the quiet period, with the latest arguments', () => {
  const timers = [];
  const clock = {
    setTimeout: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; },
    clearTimeout: (id) => { if (timers[id]) timers[id].live = false; },
  };
  const calls = [];
  const d = debounce((x) => calls.push(x), 300, clock);
  d(1);
  d(2);
  d(3);
  assert.equal(timers.filter((t) => t.live).length, 1);
  assert.equal(timers.at(-1).ms, 300);
  timers.filter((t) => t.live).forEach((t) => { t.live = false; t.fn(); });
  assert.deepEqual(calls, [3]);
  d(4);
  d.cancel();
  assert.equal(timers.filter((t) => t.live).length, 0);
});

test('LiveTiles: fetches each tile once, caches, dedupes features and refuses too many tiles', async () => {
  const fetched = [];
  const live = new LiveTiles({
    tileZoom: 13,
    maxTiles: 8,
    fetchTile: async (tile) => {
      fetched.push(`${tile.x}/${tile.y}`);
      // The same feature (id 1) crosses every tile.
      return [{ type: 'Feature', id: 1, properties: {} }, { type: 'Feature', id: `${tile.x}/${tile.y}`, properties: {} }];
    },
  });
  const box = [-79.96, 32.77, -79.90, 32.80];
  const first = await live.update(box);
  const n = tilesForBounds(box, 13).length;
  assert.equal(fetched.length, n);
  assert.equal(first.features.length, n + 1);
  assert.deepEqual(first.errors, []);
  const again = await live.update(box);
  assert.equal(fetched.length, n, 'cached tiles are not fetched again');
  assert.equal(again.features.length, n + 1);
  // Concurrent updates share in-flight requests.
  const other = new LiveTiles({ tileZoom: 13, fetchTile: async (t) => { fetched.push('x'); return [{ id: `${t.x}` }]; } });
  const before = fetched.length;
  await Promise.all([other.update(box), other.update(box)]);
  assert.equal(fetched.length - before, n);
  const big = await live.update([-81, 32, -79, 34]);
  assert.equal(big.tooMany, true);
  assert.equal(big.features.length, 0);
});

test('LiveTiles: a failing tile is reported, not cached, and retried next time', async () => {
  let fail = true;
  const live = new LiveTiles({ tileZoom: 15, fetchTile: async () => {
    if (fail) throw new Error('HTTP 500');
    return [{ id: 1 }];
  } });
  const box = [-79.931, 32.776, -79.930, 32.777];
  const r = await live.update(box);
  assert.equal(r.features.length, 0);
  assert.match(r.errors[0], /HTTP 500/);
  fail = false;
  const r2 = await live.update(box);
  assert.equal(r2.features.length, 1);
  assert.deepEqual(r2.errors, []);
});
