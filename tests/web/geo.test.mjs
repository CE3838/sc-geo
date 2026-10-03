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

import { NAIP_SOURCES, fillBbox, mercatorBbox, shouldFallBack } from '../../web/geo.js';

test('NAIP_SOURCES are https templates with a bbox placeholder', () => {
  assert.ok(NAIP_SOURCES.length >= 2);
  for (const s of NAIP_SOURCES) {
    assert.match(s.url, /^https:\/\//);
    assert.ok(s.url.includes('{bbox-epsg-3857}'), s.id);
    assert.ok(s.attribution);
  }
  assert.equal(new Set(NAIP_SOURCES.map((s) => s.id)).size, NAIP_SOURCES.length);
});

test('fillBbox substitutes the placeholder', () => {
  assert.equal(fillBbox('a?bbox={bbox-epsg-3857}&x=1', [1, 2, 3, 4]), 'a?bbox=1,2,3,4&x=1');
});

test('mercatorBbox projects lon/lat to EPSG:3857 meters', () => {
  const [x0, y0, x1, y1] = mercatorBbox([-180, 0, 0, 0]);
  assert.ok(Math.abs(x0 + 20037508.34) < 1);
  for (const v of [x1, y0, y1]) assert.ok(Math.abs(v) < 1e-6);
  const [, cy] = mercatorBbox([-79.93, 32.78, -79.92, 32.79]);
  assert.ok(Math.abs(cy - 3866000) < 2000);
});

test('shouldFallBack only after repeated errors with no loaded tiles', () => {
  assert.equal(shouldFallBack({ errors: 2, loaded: 0 }), false);
  assert.equal(shouldFallBack({ errors: 3, loaded: 0 }), true);
  assert.equal(shouldFallBack({ errors: 10, loaded: 1 }), false);
});
