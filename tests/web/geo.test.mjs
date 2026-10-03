import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCoords, formatScale, onStyleReady, scaleDenominator, streetViewUrl, SC_BOUNDS } from '../../web/geo.js';

test('onStyleReady runs now if the style is loaded, else on style.load (not load)', () => {
  const calls = [];
  const fake = (loaded) => ({ handlers: {}, isStyleLoaded: () => loaded,
    once(type, h) { this.handlers[type] = h; } });
  const ready = fake(true);
  onStyleReady(ready, () => calls.push('now'));
  assert.deepEqual(calls, ['now']);
  const later = fake(false);
  onStyleReady(later, () => calls.push('later'));
  assert.deepEqual(Object.keys(later.handlers), ['style.load']);
  later.handlers['style.load']();
  assert.deepEqual(calls, ['now', 'later']);
  // Style loaded but a source still loading: isStyleLoaded() is false, yet it must run now.
  const busy = { ...fake(false), style: { _loaded: true } };
  onStyleReady(busy, () => calls.push('busy'));
  assert.deepEqual(calls, ['now', 'later', 'busy']);
});

test('scaleDenominator: ground meters per CSS pixel over 0.2646 mm (96 dpi)', () => {
  // Zoom 0 at the equator: 40,075,016.686 m over 512 px.
  const z0 = (40075016.686 / 512) / (0.0254 / 96);
  assert.ok(Math.abs(scaleDenominator(0, 0) - z0) < 1e-6);
  assert.ok(Math.abs(scaleDenominator(1, 60) - z0 / 4) < 1e-6);
});

test('formatScale rounds to two significant digits', () => {
  assert.equal(formatScale(60671.3), '1:61,000');
  assert.equal(formatScale(1234), '1:1,200');
  assert.equal(formatScale(Number.NaN), '');
});

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

import { firstPopupItem } from '../../web/geo.js';

test('firstPopupItem returns the first answer and stops asking', () => {
  const asked = [];
  const item = (name, answer) => (e) => {
    asked.push(name);
    return answer && `${answer}@${e.x}`;
  };
  assert.equal(firstPopupItem([item('a', null), item('b', 'well'), item('c', 'cad')], { x: 1 }), 'well@1');
  assert.deepEqual(asked, ['a', 'b']);
  assert.equal(firstPopupItem([], {}), null);
  assert.equal(firstPopupItem([item('a', null)], {}), null);
});
