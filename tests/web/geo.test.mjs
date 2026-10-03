import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCoords, streetViewUrl, SC_BOUNDS } from '../../web/geo.js';

test('formatCoords uses 6 decimals with hemisphere letters', () => {
  assert.equal(formatCoords(-79.9311, 32.7765), '32.776500° N, 79.931100° W');
  assert.equal(formatCoords(10, -5), '5.000000° S, 10.000000° E');
});

test('streetViewUrl opens a pano at lat,lng', () => {
  const url = new URL(streetViewUrl(-79.9311, 32.7765));
  assert.equal(url.origin, 'https://www.google.com');
  assert.equal(url.pathname, '/maps/@');
  assert.equal(url.searchParams.get('api'), '1');
  assert.equal(url.searchParams.get('map_action'), 'pano');
  assert.equal(url.searchParams.get('viewpoint'), '32.776500,-79.931100');
});

test('streetViewUrl rejects non-finite input', () => {
  assert.throws(() => streetViewUrl(NaN, 32));
  assert.throws(() => streetViewUrl(-80, Infinity));
});

test('SC_BOUNDS contains Charleston', () => {
  const [[w, s], [e, n]] = SC_BOUNDS;
  assert.ok(w < -79.93 && -79.93 < e && s < 32.78 && 32.78 < n);
});

import { NAIP_SOURCES, fillTile, shouldFallBack, tileBbox3857, tileForLngLat } from '../../web/geo.js';

test('NAIP_SOURCES are https tile templates', () => {
  assert.ok(NAIP_SOURCES.length >= 2);
  for (const s of NAIP_SOURCES) {
    assert.match(s.url, /^https:\/\//);
    const bbox = s.url.includes('{bbox-epsg-3857}');
    const xyz = ['{z}', '{x}', '{y}'].every((p) => s.url.includes(p));
    assert.ok(bbox || xyz, s.id);
    assert.ok(s.attribution);
  }
  assert.equal(new Set(NAIP_SOURCES.map((s) => s.id)).size, NAIP_SOURCES.length);
});

test('tileForLngLat matches the standard slippy-map scheme', () => {
  assert.deepEqual(tileForLngLat(0, 0, 1), { x: 1, y: 1, z: 1 });
  assert.deepEqual(tileForLngLat(-179.9, 85, 2), { x: 0, y: 0, z: 2 });
  // Downtown Charleston at z16.
  assert.deepEqual(tileForLngLat(-79.93, 32.78, 16), { x: 18217, y: 26445, z: 16 });
});

test('tileBbox3857 gives the tile extent in Web Mercator meters', () => {
  const [w, s, e, n] = tileBbox3857({ x: 0, y: 0, z: 1 });
  const half = 20037508.342789244;
  assert.ok(Math.abs(w + half) < 1e-6 && Math.abs(n - half) < 1e-6);
  assert.ok(Math.abs(e) < 1e-6 && Math.abs(s) < 1e-6);
});

test('fillTile fills bbox and xyz placeholders', () => {
  const t = { x: 1, y: 0, z: 1 };
  assert.equal(fillTile('t/{z}/{y}/{x}', t), 't/1/0/1');
  const [w, s, e, n] = fillTile('b={bbox-epsg-3857}', t).slice(2).split(',').map(Number);
  assert.ok(Math.abs(w) < 1e-6 && Math.abs(s) < 1e-6 && e > 2e7 && n > 2e7);
});

test('shouldFallBack only after repeated errors with no loaded tiles', () => {
  assert.equal(shouldFallBack({ errors: 2, loaded: 0 }), false);
  assert.equal(shouldFallBack({ errors: 3, loaded: 0 }), true);
  assert.equal(shouldFallBack({ errors: 10, loaded: 1 }), false);
});
