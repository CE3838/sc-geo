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
